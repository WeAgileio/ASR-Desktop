import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from asr_desktop.models import ModelStore


class HTTPResumeTests(unittest.TestCase):
    def test_real_interrupted_http_response_resumes_validated_range(self):
        payload = b"test immutable weight bytes" * 1000
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                offset = int(self.headers.get("Range", "bytes=0-")[6:-1])
                seen.append({"offset": offset, "if_range": self.headers.get("If-Range")})
                self.send_response(206 if offset else 200)
                self.send_header("ETag", '"immutable-fixture"')
                self.send_header("Content-Length", str(len(payload) - offset))
                if offset:
                    self.send_header("Content-Range", f"bytes {offset}-{len(payload)-1}/{len(payload)}")
                self.end_headers()
                self.wfile.write(payload[offset:] if offset else payload[:7000])
                self.close_connection = True
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                assets = [{"path": "model.pt", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                           "url": f"http://127.0.0.1:{server.server_port}/model.pt"}]
                components = {"test": {"revision": "a" * 40, "assets": assets}}
                snapshot = hashlib.sha256(json.dumps(components, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                catalog = {"components": components, "models": [{"id": "fixture", "snapshot_id": snapshot,
                           "components": ["test"], "download_bytes": len(payload)}]}
                store = ModelStore(Path(directory).resolve() / "models", catalog)
                with self.assertRaises(OSError):
                    store.prepare("fixture")
                self.assertEqual(store.status("fixture")["state"], "failed")
                partial = store.root / "staging" / snapshot / "test/model.pt.partial"
                self.assertEqual(partial.stat().st_size, 7000)
                self.assertTrue(store.prepare("fixture")["ready"])
                self.assertEqual(seen, [{"offset": 0, "if_range": None}, {"offset": 7000, "if_range": '"immutable-fixture"'}])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
