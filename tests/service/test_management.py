import base64
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from asr_service.api import create_app
from asr_service.config import APIConfig
from asr_service.dashboard import create_dashboard
from asr_service.native import scan_once, cleanup
from asr_service.store import Store


class ManagementTest(unittest.TestCase):
    def test_dashboard_rejects_mutations_including_get(self):
        with patch("rq_dashboard.web.setup_rq_connection"):
            app = create_dashboard("p" * 32, "redis://localhost:1/0")
            c = app.test_client()
            self.assertEqual(c.get("/").status_code, 401)
            auth = {
                "Authorization": "Basic "
                + base64.b64encode(("admin:" + ("p" * 32)).encode()).decode()
            }
            self.assertEqual(c.get("/requeue/asr", headers=auth).status_code, 403)
            self.assertEqual(c.post("/job/a/requeue", headers=auth).status_code, 403)
            self.assertEqual(
                c.post("/queue/asr/failed/empty", headers=auth).status_code, 403
            )

    def test_web_and_pause_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = APIConfig(Path(tmp) / "db", "p" * 32, "w" * 32, "s" * 32, "", False)
            with TestClient(create_app(cfg)) as c:
                c.auth = ("admin", "p" * 32)
                page = c.get("/")
                self.assertEqual(page.status_code, 200)
                self.assertIn("新增轉錄批次", page.text)
                token = c.cookies["asr_csrf"]
                self.assertEqual(
                    c.post(
                        "/api/pause",
                        json={"paused": True},
                        headers={"x-csrf-token": token},
                    ).status_code,
                    200,
                )
            self.assertTrue(Store(cfg.db).overview()["paused"])

    def test_scanner_dispatch_and_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "db")
            id = store.batch(
                {"source": "src", "destination": "dst", "interval_seconds": 120}
            )

            class Client:
                def call(self, action, **body):
                    if action == "scan-claim":
                        return store.scan_claim()
                    return store.scan_update(**body)

            class Drive:
                def scan(self, *a):
                    return (
                        [
                            {
                                "id": "file",
                                "name": "one",
                                "path": "one",
                                "version": "a",
                                "size": 1,
                            }
                        ],
                        0,
                    )

            self.assertTrue(scan_once(Client(), Drive()))
            store.rescan(id)
            self.assertTrue(scan_once(Client(), Drive()))
            self.assertEqual(len(store.get("batches", id)["jobs"]), 1)
            self.assertFalse(scan_once(Client(), Drive()))

    def test_cleanup_preserves_undelivered(self):
        import json

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("os.environ", {"ASR_WORKSPACE": tmp, "ASR_RETENTION_DAYS": "0"}),
        ):
            jobs = Path(tmp) / "jobs"
            jobs.mkdir()
            for name, state in [("one", "uploading"), ("two", "completed")]:
                p = jobs / name
                p.mkdir()
                (p / "manifest.json").write_text(json.dumps({"completed_at": 1}))

            class Client:
                def call(self, action, **body):
                    return {
                        "status": "uploading" if body["id"] == "one" else "completed"
                    }

                def close(self):
                    pass

            with patch("asr_service.native.Client", Client):
                cleanup()
            self.assertTrue((jobs / "one").exists())
            self.assertFalse((jobs / "two").exists())


if __name__ == "__main__":
    unittest.main()
