#!/usr/bin/env python3
"""Exercise explicit development bootstrap in a private, isolated control directory."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    args = parser.parse_args()
    app = args.app.resolve()
    with (app / "Contents/Info.plist").open("rb") as stream:
        assert plistlib.load(stream).get("ASRDesktopDevelopmentMode") is True
    cli = app / "Contents/MacOS/asr-desktop"
    with tempfile.TemporaryDirectory(prefix="asr-dev-lifecycle-", dir="/private/tmp") as directory:
        environment = os.environ.copy()
        environment.update(PATH="/usr/bin:/bin", ASR_DESKTOP_RUN_DIR=directory,
                           ASR_DESKTOP_DATA_DIR=str(Path(directory) / "data"),
                           PYTHONHOME="/nonexistent-python", PYTHONPATH="/nonexistent-python")
        def request(action):
            result = subprocess.run([str(cli), "service", action], env=environment,
                                    capture_output=True, text=True, timeout=15, check=True)
            reply = json.loads(result.stdout)
            assert reply["success"], reply
            return reply["result"]
        started = False
        try:
            first = request("start")
            started = True
            assert first["uid"] == os.getuid() and first["service_mode"] == "development", first
            # Each request above exits its CLI process before the next one starts.
            time.sleep(1)
            after_exit = request("status")
            second = request("start")
            assert first["pid"] == after_exit["pid"] == second["pid"]
            socket_path = Path(directory) / "control.sock"
            assert socket_path.stat().st_mode & 0o777 == 0o600
            assert Path(directory).stat().st_mode & 0o777 == 0o700
            request("stop")
            for _ in range(100):
                if not socket_path.exists():
                    break
                time.sleep(0.05)
            assert not socket_path.exists(), "Stop must clean up the control socket"
            started = False
            unavailable = subprocess.run([str(cli), "service", "status"], env=environment,
                                         capture_output=True, text=True, timeout=10)
            assert unavailable.returncode == 3
            report = {"service_mode": "development", "app": str(app), "uid": os.getuid(),
                      "pid": first["pid"], "client_exit_survival": True, "singleton": True,
                      "private_permissions": True, "stop_cleanup": True,
                      "status_after_stop_exit_code": unavailable.returncode,
                      "managed_service_acceptance": False}
            target = ROOT / "build/desktop/development-service-verification.json"
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(target)
        finally:
            if started:
                request("stop")


if __name__ == "__main__":
    main()
