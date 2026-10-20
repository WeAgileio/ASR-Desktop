import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from asr_desktop.coordinator import prepare_directory


@unittest.skipUnless(sys.platform == "darwin", "Mac-specific local peer identity")
class CoordinatorBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="asr-control-test-")
        self.root = Path(self.temporary.name) / "private"
        self.environment = os.environ.copy()
        self.environment["ASR_DESKTOP_RUN_DIR"] = str(self.root)
        self.environment["ASR_DESKTOP_DATA_DIR"] = str(Path(self.temporary.name) / "data")
        self.environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
        self.process = subprocess.Popen([sys.executable, "-m", "asr_desktop.coordinator"],
                                        env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(100):
            if (self.root / "control.sock").exists():
                return
            if self.process.poll() is not None:
                self.fail(self.process.stderr.read().decode())
            time.sleep(0.02)
        self.fail("Coordinator did not start")

    def tearDown(self):
        try:
            if self.process.poll() is None:
                try:
                    self.request("service.stop")
                except OSError:
                    self.process.terminate()
            self.process.wait(timeout=5)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process.stderr.close()
            self.temporary.cleanup()

    def request(self, operation, version=1):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(self.root / "control.sock"))
            connection.sendall(json.dumps({"protocol_version": version, "id": "test", "operation": operation}).encode()+b"\n")
            data = bytearray()
            while b"\n" not in data:
                block = connection.recv(4096)
                if not block:
                    self.fail("Service closed without a response")
                data.extend(block)
            return json.loads(data)

    def test_health_uses_private_socket_and_actual_peer(self):
        reply = self.request("service.status")
        self.assertTrue(reply["success"])
        self.assertEqual(reply["result"]["pid"], self.process.pid)
        self.assertEqual(reply["result"]["uid"], os.getuid())
        self.assertTrue(reply["result"]["execution_ready"])
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.root / "control.sock").stat().st_mode), 0o600)

    def test_wrong_protocol_cannot_stop_service(self):
        reply = self.request("service.stop", version=999)
        self.assertFalse(reply["success"])
        self.assertEqual(reply["error"]["code"], "protocol_mismatch")
        self.assertTrue(self.request("service.status")["success"])

    def test_second_coordinator_cannot_replace_live_socket(self):
        second = subprocess.run([sys.executable, "-m", "asr_desktop.coordinator"], env=self.environment,
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already owns", second.stderr)
        self.assertEqual(self.request("service.status")["result"]["pid"], self.process.pid)

    def test_distinct_socket_cannot_create_a_second_database_writer(self):
        environment = {**self.environment, "ASR_DESKTOP_RUN_DIR": str(Path(self.temporary.name) / "other")}
        second = subprocess.run([sys.executable, "-m", "asr_desktop.coordinator"], env=environment,
                                capture_output=True, text=True, timeout=5)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("already owns this data directory", second.stderr)
        self.assertEqual(self.request("service.status")["result"]["pid"], self.process.pid)

    def test_foreign_peer_identity_cannot_mutate_the_service(self):
        root = Path(self.temporary.name) / "foreign-peer"
        environment = {**self.environment, "ASR_DESKTOP_RUN_DIR": str(root),
                       "ASR_DESKTOP_DATA_DIR": str(Path(self.temporary.name) / "foreign-data")}
        # Keep a real private transport; control only the OS identity result at its boundary.
        code = "import os; from asr_desktop import coordinator as c; c.peer_uid=lambda connection: os.getuid()+1; c.serve()"
        process = subprocess.Popen([sys.executable, "-c", code], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                if (root / "control.sock").exists():
                    break
                if process.poll() is not None:
                    self.fail(process.stderr.read().decode())
                time.sleep(.02)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(3)
                connection.connect(str(root / "control.sock"))
                connection.sendall(b'{"protocol_version":1,"id":"foreign","operation":"service.stop"}\n')
                result = json.loads(connection.recv(65536))
            self.assertFalse(result["success"])
            self.assertIn("another user", result["error"]["message"])
            self.assertIsNone(process.poll())
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            process.stderr.close()

    def test_stop_terminates_service_and_removes_socket(self):
        self.assertTrue(self.request("service.stop")["success"])
        self.assertEqual(self.process.wait(timeout=5), 0)
        self.assertFalse((self.root / "control.sock").exists())

    def test_unsafe_control_directory_is_not_repaired_silently(self):
        unsafe = Path(self.temporary.name) / "public"
        unsafe.mkdir(mode=0o755)
        with self.assertRaises(PermissionError):
            prepare_directory(unsafe)
        link = Path(self.temporary.name) / "link"
        link.symlink_to(self.root)
        with self.assertRaises(PermissionError):
            prepare_directory(link)


if __name__ == "__main__":
    unittest.main()
