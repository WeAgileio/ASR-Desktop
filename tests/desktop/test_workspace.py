import json
from pathlib import Path
import sqlite3
import re
import tempfile
import unittest
from unittest.mock import patch

from asr_desktop.database import Database, SCHEMA_VERSION, StateError
from asr_desktop.intake import preview
from asr_desktop.workspace import Workspace
from asr_desktop.models import ModelError


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = Workspace(self.root / "data", self.root / "ffprobe")
        self.source = self.root / "中文 with spaces.wav"
        self.source.write_bytes(b"example audio")

    def tearDown(self):
        self.workspace.database.close()
        self.temp.cleanup()

    def request(self, operation, arguments=None, request_id="request-1"):
        return self.workspace.dispatch({"protocol_version": 1, "id": request_id,
                                        "operation": operation, "arguments": arguments or {}})

    def submit(self, **kwargs):
        args = {"paths": [str(self.source)], "output_dir": str(self.root / "output"), **kwargs}
        with patch("asr_desktop.intake.probe", return_value=1234):
            return self.request("submit", args)

    def test_request_replay_and_atomic_rollback(self):
        batch = self.submit()
        self.assertEqual(self.submit(), batch)
        self.assertEqual(len(self.request("jobs.list")["jobs"]), 1)
        with self.assertRaises(StateError) as error:
            self.request("queue.resume")
        self.assertEqual(error.exception.code, "request_id_conflict")
        db = self.workspace.database
        def fail():
            db.set_setting("queue_paused", False)
            raise RuntimeError("transaction failed")
        with self.assertRaises(RuntimeError):
            db.command("failure", "queue.resume", {}, fail)
        self.assertTrue(db.setting("queue_paused"))
        self.assertIsNone(db.connection.execute("SELECT id FROM requests WHERE id='failure'").fetchone())

    def test_settings_and_source_are_frozen(self):
        batch = self.submit()
        job = self.request("jobs.show", {"id": batch["job_ids"][0]})
        self.assertEqual(job["state"], "blocked")
        self.request("settings.set", {"settings": {"device": "gpu", "formats": ["json"]}}, "settings")
        self.assertEqual(self.request("jobs.show", {"id": job["id"]})["settings"]["device"], "auto")
        self.request("jobs.cancel", {"id": job["id"]}, "cancel")
        self.source.write_bytes(b"changed source")
        with self.assertRaises(StateError) as error:
            self.request("jobs.retry", {"id": job["id"]}, "retry")
        self.assertEqual(error.exception.code, "source_changed")

    def test_active_references_block_model_removal_but_history_does_not(self):
        batch = self.submit()
        with self.assertRaises(ModelError) as error:
            self.workspace.models.remove("fun-asr-nano")
        self.assertEqual(error.exception.code, "model_in_use")
        self.assertEqual(error.exception.details["job_ids"], batch["job_ids"])
        self.request("jobs.cancel", {"id": batch["id"]}, "cancel")
        self.workspace.models.remove("fun-asr-nano")
        self.assertEqual(self.request("jobs.show", {"id": batch["job_ids"][0]})["state"], "cancelled")

    def test_cursor_replay_reset_and_authoritative_snapshot(self):
        self.submit()
        db = self.workspace.database
        first = db.events()
        self.assertGreater(len(first["events"]), 0)
        self.assertEqual(db.events(first["cursor"])["events"], [])
        self.request("queue.resume", request_id="resume")
        db.prune_events(retain=1)
        reset = db.events(0)
        self.assertTrue(reset["reset"])
        self.assertEqual(len(reset["snapshot"]["jobs"]), 1)
        self.assertFalse(reset["snapshot"]["queue_paused"])

    def test_stale_attempt_event_cannot_modify_job(self):
        batch = self.submit()
        db = self.workspace.database
        identifier = batch["job_ids"][0]
        db.update_job(identifier, "running", attempt_id="attempt-new")
        self.assertFalse(db.accept_attempt_event(identifier, "attempt-old", "completed", {}))
        self.assertEqual(db.job(identifier)["state"], "running")

    def test_calibration_uses_frozen_same_source_and_serial_queue(self):
        with patch("asr_desktop.intake.probe", return_value=60000):
            control = self.request("device.calibrate", {"paths": [str(self.source)], "settings": {"model": "paraformer"}})
        jobs = self.request("jobs.show", {"id": control["id"]})["jobs"]
        self.assertEqual([j["settings"]["device"] for j in jobs], ["cpu", "gpu"])
        self.assertEqual(jobs[0]["fingerprint"], jobs[1]["fingerprint"])
        self.assertEqual(jobs[0]["snapshot"], jobs[1]["snapshot"])
        self.assertTrue(self.workspace.database.setting("queue_paused"))

    def test_all_protocol_json_examples_parse_against_envelope_contract(self):
        from asr_desktop.workspace import OPERATIONS
        documentation = Path(__file__).resolve().parents[2] / "desktop/PROTOCOL.md"
        examples = re.findall(r"```json\n(.*?)\n```", documentation.read_text(), re.S)
        self.assertEqual(len(examples), 2)
        for text in examples:
            value = json.loads(text)
            self.assertEqual(value["protocol_version"], 1)
            self.assertIsInstance(value["id"], str)
            if "operation" in value:
                self.assertIn(value["operation"], OPERATIONS)
                self.assertIsInstance(value["arguments"], dict)
            else:
                self.assertTrue(value["success"])
                self.assertIn("id", value["result"])

    def test_preview_deduplicates_roots_excludes_symlinks_and_invalid_media(self):
        folder = self.root / "input"
        folder.mkdir()
        (folder / "same.mp3").write_bytes(b"audio")
        (folder / "same.wav").write_bytes(b"audio")
        (folder / "bad.txt").write_text("bad")
        (folder / "link.mp3").symlink_to(folder / "same.mp3")
        nested = folder / "nested"
        nested.mkdir()
        (nested / "child.mp3").write_bytes(b"audio")
        def media(path, executable):
            if path.suffix == ".txt":
                raise StateError("invalid_media", "No audio")
            return 1000
        with patch("asr_desktop.intake.probe", side_effect=media):
            result = preview([str(folder), str(folder / "same.mp3")], str(self.root / "out"), {}, "probe")
            recursive = preview([str(folder)], str(self.root / "out"), {}, "probe", recursive=True)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(recursive["valid_count"], 3)
        states = [entry["status"] for entry in result["entries"]]
        self.assertIn("symlink_excluded", states)
        self.assertIn("invalid", states)
        self.assertIn("duplicate", states)
        outputs = [entry["outputs"]["txt"] for entry in result["entries"] if entry["status"] == "valid"]
        # Same stem but different extensions have distinct source identities.
        self.assertEqual(len(set(outputs)), 2)


class SchemaTests(unittest.TestCase):
    def test_newer_schema_refuses_writes_and_upgrade_creates_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "workspace.db"
            conn = sqlite3.connect(path)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
            conn.close()
            before = path.read_bytes()
            with self.assertRaises(StateError):
                Database(path)
            self.assertEqual(path.read_bytes(), before)
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA user_version=0")
            conn.close()
            db = Database(path)
            self.assertTrue(db.upgrade_backup.is_file())
            backup = sqlite3.connect(db.upgrade_backup)
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 0)
            backup.close()
            db.close()


if __name__ == "__main__":
    unittest.main()
