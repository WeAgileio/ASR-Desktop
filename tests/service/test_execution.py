from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from asr_service.native import deliver, host_lock
from asr_service.store import Store
from asr_service.drive import Drive, SourceChanged
from asr_service.dispatch import dispatch_once
from rq.exceptions import NoSuchJobError


class LocalClient:
    def __init__(self, store):
        self.store = store

    def call(self, action, **kw):
        if action == "event":
            return self.store.event(
                kw["id"],
                kw["token"],
                kw["sequence"],
                kw.get("phase"),
                kw.get("progress"),
            )
        if action == "reserve":
            return self.store.reserve(
                kw["id"], kw["token"], kw["kind"], kw["remote_id"]
            )
        if action == "verify":
            return self.store.verify(
                kw["id"], kw["token"], kw["kind"], kw["remote_id"], kw["checksum"]
            )


class ExecutionTest(unittest.TestCase):
    def test_queue_failure_and_lost_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "db")
            batch = store.batch({"source": "source", "destination": "dest"})
            scan = store.scan_claim()
            store.scan_update(
                batch,
                scan["token"],
                media=[
                    {
                        "id": "file",
                        "name": "a.mp3",
                        "path": "a.mp3",
                        "version": "v1",
                        "size": 0,
                    }
                ],
            )

            class Queue:
                connection = None

                def __init__(self):
                    self.calls = 0

                def enqueue(self, *a, **kw):
                    self.calls += 1
                    raise ConnectionError("lost ack")

            queue = Queue()
            with patch("asr_service.dispatch.Job.fetch", side_effect=NoSuchJobError):
                with self.assertRaises(ConnectionError):
                    dispatch_once(store, queue)
            self.assertEqual(store.dispatch_rows()[0]["sent"], 0)

            class Existing:
                def get_status(self):
                    class Status:
                        value = "queued"

                    return Status()

            with patch("asr_service.dispatch.Job.fetch", return_value=Existing()):
                dispatch_once(store, queue)
            self.assertEqual(queue.calls, 1)
            self.assertEqual(store.dispatch_rows()[0]["sent"], 1)

    def test_delivery_lost_create_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / "db")
            b = store.batch({"source": "source", "destination": "dest"})
            scan = store.scan_claim()
            store.scan_update(
                b,
                scan["token"],
                media=[
                    {
                        "id": "file",
                        "name": "a.mp3",
                        "path": "a.mp3",
                        "version": "v1",
                        "size": 0,
                    }
                ],
            )
            record = store.get("batches", b)["jobs"][0]
            id = record["id"]
            store.claim(id, 0, "token")
            store.event(id, "token", 0, "uploading")

            class Reporter:
                def event(self):
                    pass

            class FakeDrive:
                def __init__(self):
                    self.counter = 0
                    self.remote = {}
                    self.fail = True

                def generate_id(self):
                    self.counter += 1
                    return str(self.counter)

                def ensure(self, id, name, parent, identity, path=None):
                    self.remote[id] = (name, parent, identity)
                    if name == "subtitles.srt" and self.fail:
                        self.fail = False
                        raise ConnectionError("response lost after create")
                    return "checksum"

            drive = FakeDrive()
            client = LocalClient(store)
            manifest = {
                "model": {},
                "checksums": {"transcript.txt": "x", "subtitles.srt": "y"},
            }
            for name in manifest["checksums"]:
                (root / name).write_text("text")
            with self.assertRaises(ConnectionError):
                deliver(
                    client,
                    drive,
                    id,
                    "token",
                    record["payload"],
                    root,
                    Reporter(),
                    manifest,
                )
            deliver(
                client,
                drive,
                id,
                "token",
                record["payload"],
                root,
                Reporter(),
                manifest,
            )
            self.assertEqual(len(drive.remote), 5)
            store.finish(id, "token", "completed")

    def test_host_lock_is_exclusive(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict("os.environ", {"ASR_WORKSPACE": tmp}),
        ):
            with host_lock("execution.lock"):
                with self.assertRaises(BlockingIOError):
                    with host_lock("execution.lock"):
                        pass

    def test_source_changes_during_download(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def iter_content(self, n):
                yield b"abc"

        drive = Drive(session=object())
        versions = iter([{"md5Checksum": "old"}, {"md5Checksum": "new"}])
        drive.metadata = lambda id: next(versions)
        drive.request = lambda *a, **kw: Response()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source"
            with self.assertRaises(SourceChanged):
                drive.download(
                    {"id": "file", "version": "md5:old", "size": 3, "md5": "old"}, path
                )
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
