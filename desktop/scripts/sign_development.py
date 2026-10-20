#!/usr/bin/env python3
"""Stage and ad-hoc sign a local development App; never notarizes or publishes it."""

import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-place", action="store_true", help="only for a build directory outside cloud synchronization")
    parser.add_argument("--validation-environment", type=Path, help="isolated GUI validation only; writes environment into the staged copy")
    args = parser.parse_args()
    if args.validation_environment and args.in_place:
        parser.error("Validation environment is allowed only in an isolated staged copy")
    source = (ROOT / "build/desktop/ASR Desktop.app").resolve()
    if args.in_place:
        app = source
    else:
        stage = Path(tempfile.mkdtemp(prefix="asr-desktop-dev-", dir="/private/tmp"))
        app = stage / "ASR Desktop.app"
        subprocess.run(["/bin/cp", "-cR", str(source), str(app)], check=True)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != "io.asrsrt.desktop":
        raise SystemExit("Unexpected development application identity")
    if args.validation_environment:
        environment = json.loads(args.validation_environment.read_text())
        allowed = {"ASR_DESKTOP_RUN_DIR", "ASR_DESKTOP_DATA_DIR", "ASR_DESKTOP_CACHE_DIR"}
        if info.get("ASRDesktopDevelopmentMode") is not True or set(environment) != allowed or any(not isinstance(v, str) or not v.startswith("/") for v in environment.values()):
            raise SystemExit("GUI validation requires exactly three absolute isolated development paths")
        info["LSEnvironment"] = environment
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    listing = subprocess.check_output(["/usr/bin/xattr", "-lr", str(app)], text=True)
    removed = 0
    # Remove only code-signing-incompatible Finder metadata from build outputs.
    # In particular, never clear quarantine or all extended attributes.
    for line in listing.splitlines():
        line = line.rstrip()
        for attribute in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
            suffix = ": " + attribute + ":"
            if line.endswith(suffix):
                target = Path(line[:-len(suffix)])
                if target != app and app not in target.resolve().parents:
                    raise SystemExit("Metadata outside development App")
                subprocess.run(["/usr/bin/xattr", "-s", "-d", attribute, str(target)], check=True)
                removed += 1
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", "--identifier", "io.asrsrt.desktop", str(app)], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    report = {"signing": "ad-hoc", "formal_distribution": False, "verified": True,
              "finder_metadata_removed": removed, "app": str(app)}
    if args.validation_environment:
        report["validation_environment"] = environment
    (ROOT / "build/desktop/development-signing.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
