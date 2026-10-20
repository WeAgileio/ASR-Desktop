#!/usr/bin/env python3
"""Create an explicitly development-only, ad-hoc App disk image without publishing."""

import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve()
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if not info.get("ASRDesktopDevelopmentMode") or info.get("LSEnvironment"):
        raise SystemExit("Use an ordinary development App, never an isolated validation profile")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    required = [app / "Contents/MacOS" / name for name in ("ASRDesktopApp", "asr-desktop", "ASRDesktopHelper")]
    required += [app / "Contents/Resources/media" / name for name in ("ffmpeg", "ffprobe")]
    required += [app / "Contents/Resources/runtime/asr-desktop-runtime/asr-desktop-runtime"]
    for executable in required:
        subprocess.run(["/usr/bin/lipo", "-verify_arch", "arm64", str(executable)], check=True)
    if not (app / "Contents/Resources/licenses/inventory.json").is_file():
        raise SystemExit("Collect third-party notices before packaging")
    weights = [str(path) for path in app.rglob("*") if path.suffix in (".pt", ".safetensors", ".onnx") and path.is_file()]
    if weights:
        raise SystemExit("Do not bundle model weights: " + repr(weights))
    target = ROOT / "build/desktop/ASR-Desktop-development-arm64.dmg"
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="asr-dmg-source-", dir="/private/tmp") as directory:
        source = Path(directory)
        subprocess.run(["/bin/cp", "-cR", str(app), str(source / app.name)], check=True)
        (source / "Applications").symlink_to("/Applications")
        (source / "Development Build.txt").write_text("ASR Desktop development build\nApple Silicon only.\nAd-hoc signed, not notarized.\nFormal distribution and minimum-OS acceptance are pending.\nModels download after installation.\n")
        subprocess.run(["/usr/bin/hdiutil", "create", "-volname", "ASR Desktop Dev", "-fs", "APFS", "-format", "UDZO",
                        "-srcfolder", str(source), str(target)], check=True)
    subprocess.run(["/usr/bin/hdiutil", "verify", str(target)], check=True)
    report = {"dmg": str(target), "app": str(app), "mode": "development", "formal_distribution": False,
              "image_verified": True, "model_weights_bundled": False, "native_architecture": "arm64", "notices_bundled": True}
    (ROOT / "build/desktop/dmg-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    main()
