#!/usr/bin/env python3
"""Mount a development image read-only and audit relocation and native dependencies."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MAGIC = {bytes.fromhex(value) for value in ("cffaedfe", "cefaedfe", "feedfacf", "feedface", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=ROOT / "build/desktop/ASR-Desktop-development-arm64.dmg")
    image = parser.parse_args().image.resolve()
    with tempfile.TemporaryDirectory(prefix="asr-dmg-review-", dir="/private/tmp") as directory:
        mount = Path(directory) / "volume"
        mount.mkdir()
        attached = False
        try:
            subprocess.run(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(image)], check=True)
            attached = True
            app = mount / "ASR Desktop.app"
            subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            binaries, violations = [], []
            for path in app.rglob("*"):
                if path.is_symlink() or not path.is_file():
                    continue
                with path.open("rb") as stream:
                    magic = stream.read(4)
                if magic not in MAGIC:
                    continue
                subprocess.run(["/usr/bin/lipo", str(path), "-verify_arch", "arm64"], check=True, capture_output=True)
                lines = subprocess.check_output(["/usr/bin/otool", "-L", str(path)], text=True).splitlines()[1:]
                for line in lines:
                    dependency = line.strip().split(" (", 1)[0]
                    if dependency.startswith("/") and not dependency.startswith(("/usr/lib/", "/System/Library/")):
                        violations.append({"binary": str(path.relative_to(app)), "dependency": dependency})
                binaries.append(str(path.relative_to(app)))
            assert not violations, violations
            env = {**os.environ, "PATH": "/usr/bin:/bin", "PYTHONHOME": "/invalid-python", "PYTHONPATH": "/invalid-python"}
            result = subprocess.run([str(app / "Contents/MacOS/asr-desktop"), "diagnose", "--json"], env=env,
                                    capture_output=True, text=True, timeout=180)
            report = json.loads(result.stdout)
            assert result.returncode == 0 and report["ready"] and report["runtime"]["frozen"], report
            assert Path(report["installation"]["bundle_path"]).resolve() == app.resolve()
            assert (app / "Contents/Resources/licenses/inventory.json").is_file()
            record = {"image": str(image), "read_only_mount": True, "signature_verified": True,
                      "native_binary_count": len(binaries), "arm64_verified": True,
                      "external_absolute_dependencies": violations, "relocated_frozen_diagnose_ready": True,
                      "developer_path_removed": True, "formal_distribution": False}
            target = ROOT / "build/desktop/dmg-mount-verification.json"
            target.write_text(json.dumps(record, indent=2) + "\n")
            print(target)
        finally:
            if attached:
                subprocess.run(["/usr/bin/hdiutil", "detach", str(mount)], check=True)


if __name__ == "__main__":
    main()
