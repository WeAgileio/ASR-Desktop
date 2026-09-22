from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from asr_service.store import Store, Conflict
from asr_service.native import execute
from asr_service.drive import DriveError
from asr_service.dispatch import dispatch_once
from rq.exceptions import NoSuchJobError


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "db")
        b = self.store.batch({"source": "src", "destination": "dst"})
        scan = self.store.scan_claim()
        self.store.scan_update(
            b,
            scan["token"],
            media=[
                {
                    "id": "file",
                    "name": "one.mp3",
                    "path": "one.mp3",
                    "version": "v1",
                    "size": 10,
                }
            ],
        )
        self.id = self.store.get("batches", b)["jobs"][0]["id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_bounded_retry_and_manual_reset(self):
        for failure in range(1, 5):
            with self.store.connect(True) as c:
                c.execute("UPDATE jobs SET next_retry=0")
            token = str(failure)
            self.store.claim(self.id, 0, token)
            self.store.finish(self.id, token, "retry_wait", "transient")
            record = self.store.get("jobs", self.id)
            self.assertEqual(
                record["status"], "retry_wait" if failure <= 3 else "failed"
            )
            if failure <= 3:
                self.assertGreater(record["next_retry"], time.time())
        self.store.retry(self.id)
        self.assertEqual(self.store.get("jobs", self.id)["failures"], 0)
        self.assertEqual(self.store.get("jobs", self.id)["generation"], 1)

    def test_recovery_fences_old_publication_and_preserves_pause(self):
        self.store.claim(self.id, 0, "old")
        self.store.pause(True)
        self.store.recover()
        with self.assertRaises(Conflict):
            self.store.reserve(self.id, "old", "transcript.txt", "remote")
        self.assertTrue(Store(self.root / "db").overview()["paused"])
        with self.assertRaises(Conflict):
            self.store.claim(self.id, 1, "new")
        self.store.pause(False)
        self.store.claim(self.id, 1, "new")

    def test_queue_loss_recreates_only_unfinished_work(self):
        q = Mock()
        q.connection = None
        with patch("asr_service.dispatch.Job.fetch", side_effect=NoSuchJobError):
            dispatch_once(self.store, q)
            dispatch_once(self.store, q)
        self.assertEqual(q.enqueue.call_count, 2)
        self.assertEqual(
            q.enqueue.call_args_list[0].kwargs["job_id"],
            q.enqueue.call_args_list[1].kwargs["job_id"],
        )
        self.store.claim(self.id, 0, "token")
        self.assertEqual(self.store.dispatch_rows(), [])

    def test_capacity_failure_blocks_before_download(self):
        store = self.store

        class Client:
            def call(self, action, **body):
                if action == "claim":
                    return store.claim(body["id"], body["generation"], body["token"])
                if action == "finish":
                    return store.finish(
                        body["id"], body["token"], body["state"], body.get("error", "")
                    )

            def close(self):
                pass

        drive = Mock()
        with (
            patch.dict("os.environ", {"ASR_WORKSPACE": str(self.root)}),
            patch("asr_service.native.Client", Client),
            patch("asr_service.native.Drive", return_value=drive),
            patch("asr_service.native.shutil.disk_usage", return_value=Mock(free=0)),
        ):
            self.assertEqual(execute(self.id, 0), {"state": "blocked"})
        drive.download.assert_not_called()
        self.assertIn("空間不足", store.get("jobs", self.id)["error"])

    def test_scan_while_media_job_active(self):
        self.store.claim(self.id, 0, "token")
        b = self.store.batch({"source": "another", "destination": "dst"})
        scan = self.store.scan_claim()
        self.assertEqual(scan["id"], b)
        self.store.scan_update(b, scan["token"], media=[])
        self.assertEqual(self.store.get("jobs", self.id)["status"], "downloading")

    def test_bad_media_fails_without_automatic_retry(self):
        from asr_srt.errors import JobError

        store = self.store

        class Client:
            def call(self, action, **b):
                if action == "claim":
                    return store.claim(b["id"], b["generation"], b["token"])
                if action == "event":
                    return store.event(
                        b["id"],
                        b["token"],
                        b["sequence"],
                        b.get("phase"),
                        b.get("progress"),
                    )
                if action == "finish":
                    return store.finish(
                        b["id"], b["token"], b["state"], b.get("error", "")
                    )

            def close(self):
                pass

        drive = Mock()
        drive.download.side_effect = lambda item, path: (
            path.write_bytes(b"bad") or "hash"
        )
        with (
            patch.dict("os.environ", {"ASR_WORKSPACE": str(self.root)}),
            patch("asr_service.native.Client", Client),
            patch("asr_service.native.Drive", return_value=drive),
            patch(
                "asr_service.native.infer",
                side_effect=JobError("validation", "bad media"),
            ),
            patch("rq.get_current_job", return_value=Mock(retries_left=3)),
        ):
            self.assertEqual(execute(self.id, 0), {"state": "failed"})
        self.assertEqual(store.get("jobs", self.id)["failures"], 0)

    def test_publication_stops_when_authority_unavailable(self):
        from asr_service.native import deliver
        import httpx

        reporter = Mock()
        reporter.event.side_effect = httpx.ConnectError("offline")
        drive = Mock()
        client = Mock()
        with self.assertRaises(httpx.ConnectError):
            deliver(
                client,
                drive,
                self.id,
                "token",
                self.store.get("jobs", self.id)["payload"],
                self.root,
                reporter,
                {},
            )
        drive.ensure.assert_not_called()
        drive.generate_id.assert_not_called()
        client.call.assert_not_called()

    def test_drive_upload_uses_related_multipart(self):
        from asr_service.drive import Drive, file_md5

        path = self.root / "transcript.txt"
        path.write_text("繁體文字")
        drive = Drive(session=Mock())
        current = {
            "appProperties": {"identity": "identity"},
            "parents": ["parent"],
            "mimeType": "text/plain",
            "md5Checksum": file_md5(path),
        }
        drive.metadata = Mock(
            side_effect=[DriveError("Drive HTTP 404", blocked=True), current]
        )
        drive.request = Mock()
        self.assertEqual(
            drive.ensure("remote", "transcript.txt", "parent", "identity", path),
            file_md5(path),
        )
        call = drive.request.call_args
        self.assertTrue(
            call.kwargs["headers"]["Content-Type"].startswith(
                "multipart/related; boundary="
            )
        )
        self.assertIn("繁體文字".encode(), call.kwargs["data"])
        self.assertIn(b'"id": "remote"', call.kwargs["data"])

    def test_revoked_upload_permission_resumes_without_inference(self):
        from asr_service.drive import file_md5

        store = self.store

        class Client:
            def call(self, action, **body):
                if action == "get":
                    return store.get("jobs", body["id"])
                return getattr(store, action)(**body)

            def close(self):
                pass

        class Drive:
            def __init__(self):
                self.session = Mock()
                self.objects = {}
                self.counter = 0
                self.revoked = True

            def download(self, item, path):
                path.write_bytes(b"audio")
                return file_md5(path)

            def generate_id(self):
                self.counter += 1
                return "remote-" + str(self.counter)

            def ensure(self, id, name, parent, identity, path=None):
                if name == "subtitles.srt" and self.revoked:
                    raise DriveError("Drive HTTP 403", blocked=True)
                self.objects[id] = name
                return file_md5(path) if path else ""

        drive = Drive()

        def infer(payload, audio, directory, reporter):
            for name in ("transcript.txt", "subtitles.srt"):
                (directory / name).write_text("fixture")
            return {"model_id": "fixture"}

        with (
            patch.dict("os.environ", {"ASR_WORKSPACE": str(self.root)}),
            patch("asr_service.native.Client", Client),
            patch("asr_service.native.Drive", return_value=drive),
            patch("asr_service.native.infer", side_effect=infer) as inference,
        ):
            self.assertEqual(execute(self.id, 0), {"state": "blocked"})
            self.assertNotIn("completion.json", drive.objects.values())
            store.retry(self.id)
            drive.revoked = False
            self.assertEqual(execute(self.id, 1), {"completed": True})
            self.assertEqual(inference.call_count, 1)
            self.assertEqual(len(drive.objects), 5)
