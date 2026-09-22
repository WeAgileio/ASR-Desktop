"""Native host entry points; model imports occur only inside the spawned job."""

from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import shutil
import threading
import time
import httpx
from .client import Client
from .config import workspace
from .drive import Drive, DriveError, file_md5

log = logging.getLogger(__name__)


@contextmanager
def host_lock(name):
    path = workspace() / name
    with path.open("a+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def atomic_json(path, data):
    from asr_srt.files import atomic_write_text

    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


class Reporter:
    def __init__(self, client, id, token):
        self.client, self.id, self.token = client, id, token
        self.sequence = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.last_progress = 0

    def event(self, phase=None, progress=None):
        with self.lock:
            self.sequence += 1
            return self.client.call(
                "event",
                id=self.id,
                token=self.token,
                sequence=self.sequence,
                phase=phase,
                progress=progress,
            )

    def loop(self):
        while not self.stop.wait(15):
            try:
                self.event()
                self.client.call("control", name="worker")
            except Exception as exc:
                log.warning("Heartbeat unavailable: %s", type(exc).__name__)

    def callback(self, event):
        now = time.monotonic()
        if now - self.last_progress < 2 and event.status == "running":
            return
        self.last_progress = now
        try:
            self.event(progress=asdict(event))
        except Exception as exc:
            log.warning("Progress deferred: %s", type(exc).__name__)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=35)


def infer(payload, audio, directory, reporter):
    from asr_srt.config import JobConfig
    from asr_srt.domain import SubtitleSettings
    from asr_srt.workflow import LocalTranscriptionService
    from .outputs import export_text

    settings = payload["settings"]
    result = LocalTranscriptionService(progress=reporter.callback).run(
        JobConfig(
            input_path=audio,
            model=settings["model"],
            device=settings["device"],
            hotwords=tuple(settings["hotwords"]),
            output_path=directory / "subtitles.srt",
            cache_dir=workspace() / "cache",
            overwrite=True,
            subtitle=SubtitleSettings(
                max_display_units=settings["max_units"],
                max_duration_ms=settings["max_duration_ms"],
                target_min_duration_ms=min(1000, settings["max_duration_ms"]),
            ),
        )
    )
    export_text(result.transcript, directory / "transcript.txt")
    return asdict(result.transcript.metadata)


def deliver(client, drive, id, token, payload, directory, reporter, manifest):
    def publish(kind, name, parent, identity, path=None):
        reporter.event()  # Must revalidate authority before each external mutation.
        reserved = client.call(
            "reserve", id=id, token=token, kind=kind, remote_id=drive.generate_id()
        )
        manifest.setdefault("remote", {})[kind] = reserved["remote_id"]
        atomic_json(directory / "manifest.json", manifest)
        checksum = drive.ensure(reserved["remote_id"], name, parent, identity, path)
        client.call(
            "verify",
            id=id,
            token=token,
            kind=kind,
            remote_id=reserved["remote_id"],
            checksum=checksum,
        )
        return reserved["remote_id"]

    from .models import fingerprint

    source_identity = fingerprint([payload["source"], payload["destination"]])
    folder = publish(
        "source_folder",
        payload["media"]["name"][:150] + "__" + payload["source"][:12],
        payload["destination"],
        source_identity,
    )
    version = publish("version_folder", id[:20], folder, id)
    for kind in ("transcript.txt", "subtitles.srt"):
        publish(kind, kind, version, id + ":" + kind, directory / kind)
    completion = {
        "source_id": payload["source"],
        "source_version": payload["version"],
        "settings": payload["settings"],
        "model": manifest["model"],
        "reviewed": False,
        "artifacts": manifest["checksums"],
    }
    atomic_json(directory / "completion.json", completion)
    publish(
        "completion.json",
        "completion.json",
        version,
        id + ":completion.json",
        directory / "completion.json",
    )


def execute(id, generation):
    from rq import get_current_job
    from asr_srt.errors import JobError

    with host_lock("execution.lock"):
        client = Client()
        drive = None
        token = secrets.token_hex(24)
        try:
            try:
                record = client.call("claim", id=id, generation=generation, token=token)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 409:
                    return {"skipped": True}
                raise
            payload = record["payload"]
            directory = workspace() / "jobs" / id
            directory.mkdir(parents=True, exist_ok=True)
            manifest_path = directory / "manifest.json"
            try:
                manifest = json.loads(manifest_path.read_text())
            except (FileNotFoundError, ValueError):
                manifest = {}
            with Reporter(client, id, token) as reporter:
                try:
                    drive = Drive()
                    ready = manifest.get("checksums") and all(
                        (directory / name).is_file()
                        and file_md5(directory / name) == checksum
                        for name, checksum in manifest["checksums"].items()
                    )
                    if not ready:
                        required = (
                            max(
                                1024**3,
                                int(os.environ.get("ASR_MIN_FREE_BYTES", 5 * 1024**3)),
                            )
                            + payload["media"]["size"]
                        )
                        if shutil.disk_usage(workspace()).free < required:
                            raise DriveError("工作磁碟可用空間不足", blocked=True)
                        suffix = Path(payload["media"]["name"]).suffix.lower()
                        if len(suffix) > 10 or not suffix[1:].isalnum():
                            suffix = ".media"
                        audio = directory / ("source" + suffix)
                        if not (
                            audio.exists()
                            and manifest.get("source_md5") == file_md5(audio)
                        ):
                            checksum = drive.download(payload["media"], audio)
                            manifest["source_md5"] = checksum
                            atomic_json(manifest_path, manifest)
                        reporter.event("transcribing")
                        manifest["model"] = infer(payload, audio, directory, reporter)
                        manifest["checksums"] = {
                            name: file_md5(directory / name)
                            for name in ("transcript.txt", "subtitles.srt")
                        }
                        atomic_json(manifest_path, manifest)
                    reporter.event("uploading")
                    deliver(
                        client, drive, id, token, payload, directory, reporter, manifest
                    )
                    reporter.event()
                    try:
                        client.call("finish", id=id, token=token, state="completed")
                    except httpx.TransportError:
                        # The API may have committed before the response was lost.
                        if client.call("get", id=id)["status"] != "completed":
                            raise
                    manifest["completed_at"] = time.time()
                    atomic_json(manifest_path, manifest)
                    return {"completed": True}
                except Exception as exc:
                    current = get_current_job()
                    blocked = isinstance(exc, DriveError) and exc.blocked
                    invalid = isinstance(exc, JobError) and exc.phase in (
                        "validation",
                        "audio-extraction",
                    )
                    state = (
                        "blocked"
                        if blocked
                        else "failed"
                        if invalid or not current or not current.retries_left
                        else "retry_wait"
                    )
                    # Only curated messages reach the operator; arbitrary exceptions stay classified.
                    message = (
                        str(exc) if isinstance(exc, DriveError) else type(exc).__name__
                    )
                    client.call(
                        "finish", id=id, token=token, state=state, error=message
                    )
                    if state == "retry_wait":
                        raise RuntimeError(
                            "Transient task failure; retained local checkpoint"
                        ) from None
                    return {"state": state}
        finally:
            if drive is not None:
                drive.session.close()
            client.close()


def worker():
    from rq.exceptions import StopRequested

    try:
        _worker_loop()
    except (KeyboardInterrupt, StopRequested):
        return


def _worker_loop():
    from redis import Redis
    from rq import Queue, SpawnWorker
    from rq.serializers import JSONSerializer

    # The supervisor never imports torch. Each spawned job holds execution.lock.
    with host_lock("supervisor.lock"):
        delay = 1
        while True:
            client = Client()
            try:
                with host_lock("execution.lock"):
                    client.call("recover")
                control = client.call("control", name="worker")
                if control["paused"]:
                    time.sleep(3)
                    continue
                connection = Redis.from_url(
                    os.environ.get("ASR_REDIS_URL", "redis://127.0.0.1:16379/0"),
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                queue = Queue("asr", connection=connection, serializer=JSONSerializer)
                runner = SpawnWorker(
                    [queue],
                    connection=connection,
                    serializer=JSONSerializer,
                    job_monitoring_interval=5,
                )
                handlers = {
                    s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)
                }
                try:
                    runner.work(burst=True, max_jobs=1, with_scheduler=True)
                finally:
                    for signum, handler in handlers.items():
                        signal.signal(signum, handler)
                if runner._stop_requested:
                    return
                delay = 1
            except KeyboardInterrupt:
                return
            except Exception as exc:
                log.warning("Worker waiting: %s", type(exc).__name__)
                delay = min(30, delay * 2)
            finally:
                client.close()
            time.sleep(delay)


def scan_once(client, drive):
    scan = client.call("scan-claim")
    if scan is None:
        return False
    stop = threading.Event()
    lost = threading.Event()

    def beat():
        while not stop.wait(15):
            try:
                client.call("scan-update", id=scan["id"], token=scan["token"])
            except Exception:
                lost.set()

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        payload = scan["payload"]
        media, skipped = drive.scan(payload["source"], payload["destination"])
        if lost.is_set():
            raise RuntimeError("Scan heartbeat lost")
        client.call(
            "scan-update",
            id=scan["id"],
            token=scan["token"],
            media=media,
            skipped=skipped,
        )
    except Exception as exc:
        client.call(
            "scan-update",
            id=scan["id"],
            token=scan["token"],
            error=str(exc) if isinstance(exc, DriveError) else type(exc).__name__,
            blocked=isinstance(exc, DriveError) and exc.blocked,
        )
    finally:
        stop.set()
        thread.join(timeout=35)
    return True


def scanner():
    with host_lock("scanner.lock"):
        delay = 1
        while True:
            client = Client()
            drive = None
            try:
                client.call("control", name="scanner")
                drive = Drive()
                scan_once(client, drive)
                delay = 3
            except KeyboardInterrupt:
                return
            except Exception as exc:
                log.warning("Scanner waiting: %s", type(exc).__name__)
                delay = min(30, delay * 2)
            finally:
                client.close()
                if drive is not None:
                    drive.session.close()
            time.sleep(delay)


def cleanup():
    # Acquire the same lock as jobs, and query durable completion before deleting.
    client = Client()
    try:
        with host_lock("execution.lock"):
            cutoff = (
                time.time() - int(os.environ.get("ASR_RETENTION_DAYS", "7")) * 86400
            )
            for directory in (workspace() / "jobs").glob("*"):
                if not directory.is_dir() or directory.is_symlink():
                    continue
                try:
                    data = json.loads((directory / "manifest.json").read_text())
                    if data.get("completed_at", float("inf")) > cutoff:
                        continue
                    record = client.call("get", id=directory.name)
                    if record["status"] == "completed":
                        shutil.rmtree(directory)
                except (OSError, ValueError, httpx.HTTPError):
                    continue
    finally:
        client.close()
