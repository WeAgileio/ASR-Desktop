"""One inference process group at a time, driven by the coordinator thread."""

import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time

import psutil

from .database import StateError, encode, new_id
from .models import ModelError, atomic_json


def group_members(group):
    members = []
    for process in psutil.process_iter(["pid", "uids", "status"]):
        try:
            if process.info["uids"].real == os.getuid() and process.info["status"] != psutil.STATUS_ZOMBIE and os.getpgid(process.pid) == group:
                members.append(process.pid)
        except (OSError, psutil.Error):
            pass
    return members


def terminate_group(group, sig):
    try:
        os.killpg(group, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin may report EPERM for a group containing only reaped/zombie members.
        # A live member still makes this a real failure, never permission to advance.
        if group_members(group):
            raise


class Scheduler:
    def __init__(self, workspace, command_factory=None, cancel_grace=5):
        self.workspace, self.db = workspace, workspace.database
        self.command_factory = command_factory or self.worker_command
        self.cancel_grace = cancel_grace
        self.active = None
        self.stopping = False
        self._recover()

    @staticmethod
    def worker_command(config):
        if getattr(sys, "frozen", False):
            return [sys.executable, "--worker-config", str(config)]
        return [sys.executable, "-m", "asr_desktop.worker", str(config)]

    def _recover(self):
        rows = self.db.connection.execute("SELECT * FROM attempts WHERE state='running'").fetchall()
        for row in rows:
            info = json.loads(row["details"])
            config_path = info["config_path"]
            groups = set()
            for process in psutil.process_iter(["pid", "cmdline", "uids"]):
                try:
                    if (process.info["uids"].real == os.getuid() and config_path in (process.info["cmdline"] or [])
                            and process.pid != os.getpid()):
                        group = os.getpgid(process.pid)
                        if group != process.pid:
                            raise StateError("unsafe_worker_group", "Old worker is not isolated; stop it before resuming")
                        groups.add(group)
                except (psutil.Error, ProcessLookupError):
                    pass
            for group in groups:
                terminate_group(group, signal.SIGTERM)
                deadline = time.monotonic() + self.cancel_grace
                while group_members(group) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if group_members(group):
                    terminate_group(group, signal.SIGKILL)
                deadline = time.monotonic() + self.cancel_grace
                while group_members(group) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if group_members(group):
                    raise StateError("worker_not_reaped", "An old worker group is still alive; queue remains paused")
            with self.db.transaction():
                self.db.connection.execute("UPDATE attempts SET state='interrupted' WHERE id=?", (row["id"],))
                self.db.update_job(row["job_id"], "interrupted", {"error": {"code": "service_interrupted", "message": "Retry explicitly to recover"}})

    def request_stop(self, force=False):
        self.stopping = True
        with self.db.transaction():
            self.db.set_setting("queue_paused", True)
            if force and self.active:
                self.db.update_job(self.active["job_id"], "cancelling")

    @property
    def idle(self):
        return self.active is None

    def tick(self):
        if self.active:
            self._observe()
        if self.active or self.stopping or self.db.setting("queue_paused"):
            return
        rows = self.db.connection.execute("SELECT id FROM jobs WHERE state IN ('queued','blocked') ORDER BY created,id").fetchall()
        for row in rows:
            job = self.db.job(row[0])
            if not self.workspace.models.status(job["snapshot"])["ready"]:
                if job["state"] != "blocked":
                    self.db.update_job(job["id"], "blocked")
                continue
            try:
                paths = self.workspace.models.local_paths(job["snapshot"])
            except ModelError as error:
                self.db.update_job(job["id"], "blocked", {"error": {"code": error.code, "message": str(error)}})
                continue
            try:
                self._start(job, paths)
            except OSError as error:
                self.db.update_job(job["id"], "failed", {"error": {"code": "worker_start_failed", "message": str(error)}})
                continue
            return

    def _start(self, job, paths):
        attempt = new_id("attempt")
        directory = self.workspace.root / "attempts" / attempt
        directory.mkdir(parents=True, mode=0o700)
        config_path = directory / "config.json"
        config = {"job": job, "attempt_id": attempt, "workspace": str(self.workspace.root),
                  "component_paths": paths, "cancel_file": str(directory / "cancel"),
                  "result_path": str(directory / "result.json"),
                  "media_cache": str(Path(os.environ.get("ASR_DESKTOP_CACHE_DIR", str(Path.home() / "Library/Caches/ASR Desktop"))) / job["id"])}
        config["device_decision"] = self.workspace.device.explain(job["snapshot"], job["settings"], job["duration_ms"] / 1000)
        atomic_json(config_path, config)
        with self.db.transaction():
            self.db.connection.execute("INSERT INTO attempts VALUES(?,?,?,?,?)", (attempt, job["id"], time.time(), "running", encode({"config_path": str(config_path)})))
            self.db.update_job(job["id"], "running", {"error": None}, attempt_id=attempt)
        log = (directory / "stderr.log").open("wb")
        try:
            process = subprocess.Popen(self.command_factory(config_path), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=log, start_new_session=True)
        except OSError:
            log.close()
            self.db.connection.execute("UPDATE attempts SET state='failed' WHERE id=?", (attempt,))
            raise
        inbox = queue.Queue()
        def read_events():
            try:
                for line in iter(lambda: process.stdout.readline(65537), b""):
                    if len(line) <= 65536:
                        try:
                            inbox.put(json.loads(line))
                        except ValueError:
                            pass
            finally:
                process.stdout.close()
        reader = threading.Thread(target=read_events, daemon=True)
        self.active = {"job_id": job["id"], "attempt_id": attempt, "directory": directory, "process": process,
                       "log": log, "inbox": inbox, "reader": reader, "cancel_started": None,
                       "last_progress": 0, "pending_progress": None, "orphan_cleanup": False}
        self.active["device_decision"] = config["device_decision"]
        reader.start()
        try:
            created = psutil.Process(process.pid).create_time()
        except psutil.NoSuchProcess:
            created = None
        self.db.connection.execute("UPDATE attempts SET details=? WHERE id=?",
                                   (encode({"config_path": str(config_path), "pid": process.pid,
                                            "created": created}), attempt))

    def _progress(self, value):
        active = self.active
        job = self.db.job(active["job_id"])
        if job["attempt_id"] != active["attempt_id"]:
            return
        payload = {key: val for key, val in job.items() if key not in ("id", "batch_id", "created", "state", "snapshot", "attempt_id")}
        payload["progress"] = value
        with self.db.transaction():
            self.db.connection.execute("UPDATE jobs SET details=? WHERE id=?", (encode(payload), job["id"]))
            self.db.event("job.progress", job["id"], {"attempt_id": active["attempt_id"], "batch_id": job["batch_id"], **value})

    def _observe(self):
        active = self.active
        process = active["process"]
        while True:
            try:
                event = active["inbox"].get_nowait()
            except queue.Empty:
                break
            if event.get("attempt_id") == active["attempt_id"] and event.get("kind") == "progress":
                active["pending_progress"] = event["value"]
                if event["value"].get("status") in ("completed", "failed", "skipped"):
                    self._progress(active["pending_progress"])
                    active["pending_progress"] = None
        now = time.monotonic()
        if active["pending_progress"] and now - active["last_progress"] >= 0.25:
            self._progress(active["pending_progress"])
            active["pending_progress"] = None
            active["last_progress"] = now
        job = self.db.job(active["job_id"])
        if job["state"] == "cancelling":
            if active["cancel_started"] is None:
                (active["directory"] / "cancel").touch(mode=0o600)
                active["cancel_started"] = now
            elapsed = now - active["cancel_started"]
            if elapsed >= self.cancel_grace:
                terminate_group(process.pid, signal.SIGTERM)
            if elapsed >= 2 * self.cancel_grace:
                terminate_group(process.pid, signal.SIGKILL)
        if process.poll() is None:
            return
        # A leader exiting does not establish that its FFmpeg/other descendants have exited.
        if group_members(process.pid):
            active["orphan_cleanup"] = True
            terminate_group(process.pid, signal.SIGKILL)
            return
        active["reader"].join(timeout=1)
        active["log"].close()
        try:
            result = json.loads((active["directory"] / "result.json").read_text())
            if result.get("attempt_id") != active["attempt_id"] or result.get("state") not in ("completed", "failed", "cancelled"):
                raise ValueError("Invalid worker result")
        except (OSError, ValueError):
            result = {"state": "interrupted", "error": {"code": "worker_interrupted", "message": "Worker exited without a valid final result; retry explicitly"}}
        if job["state"] == "cancelling":
            result = {"state": "cancelled", "error": {"code": "cancelled", "message": "Worker group stopped"}}
        state = result.pop("state")
        result.pop("attempt_id", None)
        with self.db.transaction():
            self.workspace.device.record(job, active["device_decision"], {"state": state, **result})
            self.db.accept_attempt_event(job["id"], active["attempt_id"], state, result)
            self.db.connection.execute("UPDATE attempts SET state=? WHERE id=?", (state, active["attempt_id"]))
            if state == "interrupted":
                self.db.set_setting("queue_paused", True)
        self.active = None
        self.db.prune_events()
