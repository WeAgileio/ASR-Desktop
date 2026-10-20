import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from asr_desktop.models import ModelError, ModelStore


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None, fail_after=None):
        super().__init__(data)
        self.status, self.headers, self.fail_after = status, headers or {"ETag": '"stable"'}, fail_after

    def read(self, size=-1):
        if self.fail_after is not None and self.tell() >= self.fail_after:
            raise OSError("connection interrupted")
        return super().read(min(size, self.fail_after) if self.fail_after else size)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / "models"
        self.contents = {"config.yaml": b"test config", "tokenizer/model.pt": b"model payload"}
        assets = [{"path": name, "url": "https://models.invalid/" + name,
                   "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in self.contents.items()]
        components = {"test": {"revision": "a" * 40, "assets": assets}}
        self.snapshot = hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.catalog = {"schema_version": 1, "components": components,
                        "models": [{"id": "test", "snapshot_id": self.snapshot, "components": ["test"],
                                    "download_bytes": sum(map(len, self.contents.values()))}]}
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def opener(self, request, timeout):
        self.calls.append(request)
        name = request.full_url.removeprefix("https://models.invalid/")
        return Response(self.contents[name])

    def store(self, **kwargs):
        return ModelStore(self.root, self.catalog, opener=kwargs.pop("opener", self.opener), **kwargs)

    def test_complete_assets_and_integrity_required(self):
        store = self.store()
        self.assertFalse(store.status("test")["ready"])
        self.assertTrue(store.prepare("test")["ready"])
        paths = store.local_paths("test")
        target = Path(paths["test"]) / "tokenizer/model.pt"
        target.write_bytes(b"brokenpayloadd")
        with self.assertRaises(ModelError) as error:
            store.local_paths("test")
        self.assertEqual(error.exception.code, "model_not_ready")
        self.assertFalse(store.status("test")["ready"])
        self.assertTrue(store.prepare("test")["ready"])

    def test_capacity_failure_and_offline_are_recoverable(self):
        store = self.store(free_bytes=lambda: 0)
        with self.assertRaises(ModelError):
            store.prepare("test")
        self.assertEqual(store.status("test")["error"]["code"], "insufficient_space")
        self.assertFalse(self.calls)
        def offline(*args, **kwargs):
            raise OSError("offline")
        with self.assertRaises(OSError):
            self.store(opener=offline).prepare("test")
        self.assertFalse(store.status("test")["ready"])
        self.assertTrue(self.store().prepare("test")["ready"])

    def test_two_clients_share_one_preparation(self):
        entered, release = threading.Event(), threading.Event()
        def delayed(request, timeout):
            entered.set()
            release.wait(5)
            return self.opener(request, timeout)
        first, second = self.store(opener=delayed), self.store(opener=delayed)
        first.start("test")
        self.assertTrue(entered.wait(5))
        self.assertEqual(second.start("test")["snapshot_id"], self.snapshot)
        self.assertTrue(second.active(self.snapshot))
        with self.assertRaises(ModelError) as error:
            second.remove("test")
        self.assertEqual(error.exception.code, "model_busy")
        release.set()
        first._threads[self.snapshot].join(5)
        self.assertTrue(second.status("test")["ready"])
        self.assertEqual(len(self.calls), 2)

    def test_partial_resumes_only_with_matching_range_and_etag(self):
        store = self.store()
        asset = self.catalog["components"]["test"]["assets"][1]
        path = self.root / "transfer"
        def interrupted(request, timeout):
            return Response(self.contents[asset["path"]], fail_after=5)
        store.opener = interrupted
        with self.assertRaises(OSError):
            store._download(asset, path, lambda count: None)
        def resumed(request, timeout):
            self.assertEqual(request.get_header("Range"), "bytes=5-")
            self.assertEqual(request.get_header("If-range"), '"stable"')
            payload = self.contents[asset["path"]]
            return Response(payload[5:], 206, {"ETag": '"stable"',
                            "Content-Range": f"bytes 5-{len(payload)-1}/{len(payload)}"})
        store.opener = resumed
        store._download(asset, path, lambda count: None)
        self.assertEqual(path.read_bytes(), self.contents[asset["path"]])

    def test_unsupported_ranges_restart_single_asset(self):
        store = self.store()
        asset = self.catalog["components"]["test"]["assets"][0]
        path = self.root / "transfer"
        path.with_name("transfer.partial").write_bytes(b"test")
        path.with_name("transfer.transfer.json").write_text(json.dumps({
            "sha256": asset["sha256"], "url": asset["url"], "etag": '"stable"'}))
        store._download(asset, path, lambda count: None)
        self.assertEqual(path.read_bytes(), self.contents[asset["path"]])
        self.assertEqual(self.calls[0].get_header("Range"), "bytes=4-")

    def test_source_change_discards_partial_and_retry_restarts(self):
        store = self.store()
        asset = self.catalog["components"]["test"]["assets"][0]
        path = self.root / "transfer"
        path.with_name("transfer.partial").write_bytes(b"test")
        path.with_name("transfer.transfer.json").write_text(json.dumps({
            "sha256": asset["sha256"], "url": asset["url"], "etag": '"stable"'}))
        store.opener = lambda *a, **k: Response(b"other", 206, {"ETag": '"changed"'})
        with self.assertRaises(ModelError):
            store._download(asset, path, lambda count: None)
        self.assertFalse(path.with_name("transfer.partial").exists())
        store.opener = self.opener
        store._download(asset, path, lambda count: None)
        self.assertIsNone(self.calls[0].get_header("Range"))

    def test_checksum_failure_never_publishes_ready(self):
        store = self.store(opener=lambda *a, **k: Response(b"X" * 11))
        with self.assertRaises(ModelError):
            store.prepare("test")
        self.assertFalse(store.status("test")["ready"])
        self.assertEqual(store.status("test")["error"]["code"], "checksum_mismatch")

    def test_rejected_range_retries_once_without_range(self):
        store = self.store()
        asset = self.catalog["components"]["test"]["assets"][0]
        path = self.root / "transfer"
        path.with_name("transfer.partial").write_bytes(b"test")
        path.with_name("transfer.transfer.json").write_text(json.dumps({"sha256": asset["sha256"], "url": asset["url"], "etag": '"stable"'}))
        requests = []
        def response(request, timeout):
            requests.append(request)
            if request.get_header("Range"):
                raise HTTPError(request.full_url, 416, "Range unsupported", {}, None)
            return self.opener(request, timeout)
        store.opener = response
        store._download(asset, path, lambda count: None)
        self.assertEqual(len(requests), 2)
        self.assertIsNone(requests[1].get_header("Range"))
        self.assertEqual(path.read_bytes(), self.contents[asset["path"]])

    def test_publication_interruption_is_recoverable(self):
        store = self.store()
        from asr_desktop import models
        replace = models.os.replace
        def interrupted(source, target):
            if Path(target).parent.name == "snapshots":
                raise OSError("interrupted publication")
            return replace(source, target)
        with patch.object(models.os, "replace", side_effect=interrupted), self.assertRaises(OSError):
            store.prepare("test")
        self.assertFalse(store.status("test")["ready"])
        calls = len(self.calls)
        self.assertTrue(store.prepare("test")["ready"])
        self.assertEqual(len(self.calls), calls)  # Completed assets were reused.

    def test_old_snapshot_survives_catalog_updates_and_reference_checks(self):
        store = self.store()
        store.prepare("test")
        new_catalog = json.loads(json.dumps(self.catalog))
        new_catalog["components"]["test"]["revision"] = "b" * 40
        identity = hashlib.sha256(json.dumps(new_catalog["components"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        new_catalog["models"][0]["snapshot_id"] = identity
        upgraded = ModelStore(self.root, new_catalog, references=lambda snapshot: ["job-1"])
        self.assertTrue(upgraded.status(self.snapshot)["ready"])
        self.assertFalse(upgraded.status("test")["ready"])
        with self.assertRaises(ModelError) as error:
            upgraded.remove(self.snapshot)
        self.assertEqual(error.exception.details["job_ids"], ["job-1"])
        store.remove(self.snapshot)
        self.assertFalse(store.status(self.snapshot)["ready"])

    def test_no_network_for_local_paths_and_missing_auxiliary_asset(self):
        store = self.store()
        store.prepare("test")
        def forbidden(*args, **kwargs):
            self.fail("Inference must never call the downloader")
        store.opener = forbidden
        paths = store.local_paths("test")
        (Path(paths["test"]) / "config.yaml").unlink()
        with self.assertRaises(ModelError):
            store.local_paths("test")


if __name__ == "__main__":
    unittest.main()
