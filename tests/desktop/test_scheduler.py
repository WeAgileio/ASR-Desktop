import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from asr_desktop.scheduler import Scheduler, group_members
from asr_desktop.database import StateError
from asr_desktop.workspace import Workspace


WORKER = '''
import json, os, signal, subprocess, sys, time
from pathlib import Path
config = json.loads(Path(sys.argv[1]).read_text())
mode = config['job']['source'].split('/')[-1]
if mode == 'stubborn.wav':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'])
    Path(config['result_path']).with_name('child.pid').write_text(str(child.pid))
    time.sleep(60)
else:
    if mode == 'bursty.wav':
        for i in range(100):
            print(json.dumps({'attempt_id': config['attempt_id'], 'kind': 'progress', 'value': {'phase':'test', 'status':'running', 'current':i, 'total':100}}))
        sys.stdout.flush()
    time.sleep(.08)
    state = 'failed' if mode == 'bad.wav' else 'completed'
    Path(config['result_path']).write_text(json.dumps({'attempt_id': config['attempt_id'], 'state': state}))
'''


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = Workspace(self.root / "data", self.root / "probe")
        self.script = self.root / "controlled_worker.py"
        self.script.write_text(WORKER)
        self.scheduler = Scheduler(self.workspace, lambda config: [sys.executable, str(self.script), str(config)], cancel_grace=0.1)

    def tearDown(self):
        if self.scheduler.active:
            self.scheduler.request_stop(force=True)
            self.pump(lambda: self.scheduler.idle)
        self.workspace.database.close()
        self.temp.cleanup()

    def pump(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.scheduler.tick()
            if condition():
                return
            time.sleep(.02)
        self.fail("Scheduler condition timed out")

    def submit(self, names):
        paths = []
        for name in names:
            path = self.root / name
            path.write_bytes(b"source audio")
            paths.append(str(path))
        with patch("asr_desktop.intake.probe", return_value=1000):
            result = self.workspace.dispatch({"id": "submit-" + str(time.time_ns()), "operation": "submit",
                "arguments": {"paths": paths, "output_dir": str(self.root / "outputs")}})
        return result["job_ids"]

    def ready(self):
        return patch.multiple(self.workspace.models, status=lambda snapshot: {"ready": True}, local_paths=lambda snapshot: {})

    def test_serial_fifo_failure_continues_and_pause_survives(self):
        ids = self.submit(["bad.wav", "good.wav"])
        db = self.workspace.database
        with self.ready():
            self.scheduler.tick()
            self.assertIsNone(self.scheduler.active)  # Initial persisted pause.
            db.set_setting("queue_paused", False)
            self.scheduler.tick()
            self.assertEqual(self.scheduler.active["job_id"], ids[0])
            first_pid = self.scheduler.active["process"].pid
            db.set_setting("queue_paused", True)
            self.pump(lambda: db.job(ids[0])["state"] == "failed")
            self.assertIsNone(self.scheduler.active)
            self.assertFalse(group_members(first_pid))
            self.assertEqual(db.job(ids[1])["state"], "blocked")
            db.set_setting("queue_paused", False)
            self.pump(lambda: db.job(ids[1])["state"] == "completed")

    def test_missing_model_does_not_occupy_slot(self):
        ids = self.submit(["one.wav", "two.wav"])
        db = self.workspace.database
        # Distinguish the blocked job's pinned snapshot from the next ready job.
        db.connection.execute("UPDATE jobs SET snapshot='missing' WHERE id=?", (ids[0],))
        db.set_setting("queue_paused", False)
        with patch.multiple(self.workspace.models, status=lambda snapshot: {"ready": snapshot != "missing"}, local_paths=lambda snapshot: {}):
            self.pump(lambda: db.job(ids[1])["state"] == "completed")
        self.assertEqual(db.job(ids[0])["state"], "blocked")

    def test_bursty_progress_coalesces_without_losing_latest_state(self):
        ids = self.submit(["bursty.wav"])
        db = self.workspace.database
        db.set_setting("queue_paused", False)
        with self.ready():
            self.pump(lambda: db.job(ids[0])["state"] == "completed")
        count = db.connection.execute("SELECT COUNT(*) FROM events WHERE kind='job.progress'").fetchone()[0]
        self.assertLess(count, 5)
        self.assertEqual(db.job(ids[0])["progress"]["current"], 99)

    def test_graceful_stop_finishes_current_without_claiming_next(self):
        ids = self.submit(["first.wav", "second.wav"])
        db = self.workspace.database
        db.set_setting("queue_paused", False)
        with self.ready():
            self.scheduler.tick()
            self.scheduler.request_stop()
            self.pump(lambda: self.scheduler.idle)
        self.assertEqual(db.job(ids[0])["state"], "completed")
        self.assertEqual(db.job(ids[1])["state"], "blocked")
        self.assertTrue(db.setting("queue_paused"))

    def test_cancel_reaps_stubborn_group_before_next_job(self):
        ids = self.submit(["stubborn.wav", "good.wav"])
        db = self.workspace.database
        db.set_setting("queue_paused", False)
        with self.ready():
            self.scheduler.tick()
            active = self.scheduler.active
            self.pump(lambda: (active["directory"] / "child.pid").exists())
            pid = active["process"].pid
            self.workspace.dispatch({"id": "cancel", "operation": "jobs.cancel", "arguments": {"id": ids[0]}})
            self.pump(lambda: db.job(ids[0])["state"] == "cancelled")
            self.assertFalse(group_members(pid))
            self.pump(lambda: db.job(ids[1])["state"] == "completed")

    def test_remove_requires_reaped_group_and_reconfirmation(self):
        ids = self.submit(["stubborn.wav", "good.wav"])
        db = self.workspace.database
        selector = {"ids": [ids[0]]}
        token = db.selection(selector)[0]["target_token"]
        def remove(token, request_id):
            return self.workspace.dispatch({"operation": "jobs.remove", "id": request_id,
                                            "arguments": {"selector": selector, "target_token": token}})
        with self.ready():
            db.set_setting("queue_paused", False)
            self.scheduler.tick()
            active = self.scheduler.active
            self.pump(lambda: (active["directory"] / "child.pid").exists())
            with self.assertRaises(StateError) as caught:
                remove(token, "stale-remove")
            self.assertEqual(caught.exception.code, "selection_changed")
            self.workspace.dispatch({"id": "cancel-for-remove", "operation": "jobs.cancel", "arguments": {"id": ids[0]}})
            with self.assertRaises(StateError) as caught:
                remove(db.selection(selector)[0]["target_token"], "active-remove")
            self.assertEqual(caught.exception.code, "worker_not_reaped")
            self.assertTrue(group_members(active["process"].pid))
            self.pump(lambda: db.job(ids[0])["state"] == "cancelled")
            self.assertFalse(group_members(active["process"].pid))
            self.assertEqual(remove(db.selection(selector)[0]["target_token"], "stopped-remove")["removed_count"], 1)
            self.pump(lambda: db.job(ids[1])["state"] == "completed")

    def test_recovery_reaps_old_worker_and_requires_explicit_retry(self):
        ids = self.submit(["stubborn.wav"])
        db = self.workspace.database
        db.set_setting("queue_paused", False)
        with self.ready():
            self.scheduler.tick()
            old = self.scheduler.active
            self.pump(lambda: (old["directory"] / "child.pid").exists())
            recovered = Scheduler(self.workspace, cancel_grace=.1)
            old["process"].wait(timeout=3)
            old["reader"].join(timeout=1)
            old["log"].close()
            self.scheduler.active = None
            self.assertEqual(db.job(ids[0])["state"], "interrupted")
            self.assertFalse(group_members(old["process"].pid))
            self.assertTrue(recovered.idle)
            self.assertNotEqual(db.job(ids[0])["state"], "queued")


if __name__ == "__main__":
    unittest.main()
