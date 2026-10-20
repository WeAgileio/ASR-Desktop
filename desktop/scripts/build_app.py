#!/usr/bin/env python3
"""Build the native arm64 targets and assemble a development application."""

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "desktop"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=("debug", "release"), default="release")
    parser.add_argument("--test", action="store_true", help="run the native tests instead of assembling the App")
    parser.add_argument("--distribution", action="store_true", help="require the managed service instead of development launch")
    args = parser.parse_args()
    cache = BUILD / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CLANG_MODULE_CACHE_PATH"] = str(cache / "clang")
    environment["SWIFTPM_MODULECACHE_OVERRIDE"] = str(cache / "swift")
    command = [
        "swift", "test" if args.test else "build", "--package-path", str(ROOT / "desktop"),
        "--scratch-path", str(BUILD / "swift"),
        "--cache-path", str(cache / "packages"),
        "--config-path", str(cache / "config"),
        "--security-path", str(cache / "security"),
        "--configuration", args.configuration,
        "--triple", "arm64-apple-macosx14.0",
    ]
    subprocess.run(command, env=environment, check=True)
    if args.test:
        return
    binaries = Path(subprocess.check_output(command + ["--show-bin-path"], env=environment, text=True).strip())
    app = BUILD / "ASR Desktop.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    for name in ("ASRDesktopApp", "asr-desktop", "ASRDesktopHelper"):
        shutil.copy2(binaries / name, macos / name)
        subprocess.run(["/usr/bin/lipo", "-verify_arch", "arm64", str(macos / name)], check=True)
    with (app / "Contents" / "Info.plist").open("wb") as output:
        plistlib.dump({
            "CFBundleIdentifier": "io.asrsrt.desktop",
            "CFBundleName": "ASR Desktop",
            "CFBundleDisplayName": "ASR Desktop",
            "CFBundleExecutable": "ASRDesktopApp",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "LSMinimumSystemVersion": "14.0",
            "NSHighResolutionCapable": True,
            "ASRDesktopDevelopmentMode": not args.distribution,
        }, output)
    agents = app / "Contents/Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    with (agents / "io.asrsrt.desktop.agent.plist").open("wb") as output:
        plistlib.dump({
            "Label": "io.asrsrt.desktop.agent",
            "BundleProgram": "Contents/MacOS/ASRDesktopHelper",
            "ProgramArguments": ["ASRDesktopHelper", "--serve"],
            "RunAtLoad": True,
            "ProcessType": "Background",
        }, output)
    print(app)


if __name__ == "__main__":
    main()
