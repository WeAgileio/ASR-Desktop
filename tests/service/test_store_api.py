import concurrent.futures
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

# The lightweight API suite runs independently of the model environment.
from asr_service.config import APIConfig
from asr_service.store import Store, Conflict
from asr_service.api import create_app
from fastapi.testclient import TestClient


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "db.sqlite3"
        self.store = Store(self.path)
        self.payload = {"source": "source123", "destination": "destination123"}

    def tearDown(self):
        self.tmp.cleanup()

    def populate(self):
        id = self.store.batch(self.payload)
        scan = self.store.scan_claim()
        self.store.scan_update(
            id,
            scan["token"],
            media=[
                {
                    "id": "file123",
                    "name": "a.mp3",
                    "path": "a.mp3",
                    "version": "md5:x",
                    "size": 12,
                }
            ],
        )
        return self.store.get("batches", id)["jobs"][0]["id"]

    def test_migration_and_foreign_key(self):
        Store(self.path)
        with self.store.connect(True) as c:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO batch_jobs VALUES('missing','missing',0)")

    def test_dedupe_and_outbox(self):
        job = self.populate()
        again = self.populate()
        self.assertEqual(job, again)
        self.assertEqual(len(self.store.dispatch_rows()), 1)

    def test_claim_fencing_and_pause(self):
        job = self.populate()
        self.store.pause(True)
        with self.assertRaises(Conflict):
            self.store.claim(job, 0, "first")
        self.store.pause(False)
        self.store.claim(job, 0, "first")
        self.store.claim(job, 0, "first")
        with self.assertRaises(Conflict):
            self.store.claim(job, 0, "second")
        self.store.event(job, "first", 2, "transcribing", {"current": 10})
        self.store.event(job, "first", 1, progress={"current": 1})
        self.assertEqual(self.store.get("jobs", job)["progress"]["current"], 10)
        with self.assertRaises(Conflict):
            self.store.event(job, "first", 3, "downloading")
        self.store.recover()
        with self.assertRaises(Conflict):
            self.store.event(job, "first", 4)

    def test_completion_requires_delivery(self):
        job = self.populate()
        self.store.claim(job, 0, "first")
        with self.assertRaises(Conflict):
            self.store.finish(job, "first", "completed")
        self.store.event(job, "first", 1, "uploading")
        for kind in [
            "version_folder",
            "transcript.txt",
            "subtitles.srt",
            "completion.json",
        ]:
            self.store.reserve(job, "first", kind, kind)
            self.store.verify(job, "first", kind, kind, "hash")
        self.store.finish(job, "first", "completed")
        self.store.finish(job, "first", "completed")

    def test_concurrent_claim_and_backup(self):
        job = self.populate()

        def claim(token):
            try:
                self.store.claim(job, 0, token)
                return True
            except Conflict:
                return False

        with concurrent.futures.ThreadPoolExecutor(4) as pool:
            self.assertEqual(sum(pool.map(claim, ["a", "b", "c", "d"])), 1)
        backup = Path(self.tmp.name) / "backup.sqlite3"
        self.store.backup(backup)
        self.assertEqual(Store(backup).get("jobs", job)["status"], "downloading")

    def test_scan_lease_and_partial_failure(self):
        id = self.store.batch(self.payload)
        s = self.store.scan_claim()
        with self.assertRaises(Conflict):
            self.store.scan_update(id, "wrong", media=[])
        self.store.scan_update(id, s["token"], error="permission", blocked=True)
        self.assertEqual(self.store.get("batches", id)["jobs"], [])


class APITest(unittest.TestCase):
    def test_auth_csrf_validation_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = APIConfig(
                Path(tmp) / "db", "p" * 32, "w" * 32, "s" * 32, "", False
            )
            with TestClient(create_app(config)) as client:
                self.assertEqual(client.get("/api/overview").status_code, 401)
                client.auth = ("admin", "p" * 32)
                # Obtain CSRF directly for this API test; browser rendering is tested later.
                from itsdangerous import URLSafeTimedSerializer

                csrf = URLSafeTimedSerializer("s" * 32, salt="asr-csrf").dumps("nonce")
                client.cookies.set("asr_csrf", csrf)
                payload = {"source": "source123", "destination": "destination123"}
                self.assertEqual(
                    client.post("/api/batches", json=payload).status_code, 403
                )
                headers = {"x-csrf-token": csrf}
                self.assertEqual(
                    client.post(
                        "/api/batches", headers=headers, json=payload
                    ).status_code,
                    200,
                )
                bad = {**payload, "source": "https://example.com/drive/folders/abc"}
                self.assertEqual(
                    client.post("/api/batches", headers=headers, json=bad).status_code,
                    422,
                )
                self.assertEqual(
                    client.post("/worker/recover", json={}).status_code, 401
                )
                self.assertEqual(
                    client.post(
                        "/worker/shell",
                        auth=None,
                        headers={"Authorization": "Bearer " + "w" * 32},
                        json={},
                    ).status_code,
                    404,
                )
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("funasr", sys.modules)


if __name__ == "__main__":
    unittest.main()
