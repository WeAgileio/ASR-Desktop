#!/usr/bin/env python3
"""Freeze the locked inference environment and install it into the development App."""

import argparse
import hashlib
from importlib import metadata
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build" / "desktop"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--clean", action="store_true", help="discard PyInstaller analysis caches")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--freeze-only", action="store_true")
    mode.add_argument("--install-only", action="store_true")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("Run this build with the pinned Python 3.11 packaging environment.")
    for filename in ("runtime.lock", "build.lock"):
        for line in (ROOT / "desktop/requirements" / filename).read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, expected = line.split("==", 1)
            actual = metadata.version(name)
            if actual != expected:
                raise SystemExit(f"Version mismatch: {name}: expected {expected}, found {actual}")
    if args.check_only:
        return
    app = BUILD / "ASR Desktop.app"
    if not (app / "Contents/Info.plist").exists():
        raise SystemExit("Build the native App first: python3 desktop/scripts/build_app.py")
    media = BUILD / "media"
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(BUILD / "cache/pyinstaller")
    def fingerprints():
        inputs = list((ROOT / "src/asr_desktop").rglob("*.py")) + list((ROOT / "src/asr_desktop/data").glob("*.json"))
        inputs += list((ROOT / "src/asr_srt").rglob("*.py")) + list((ROOT / "desktop/packaging/hooks").glob("*.py"))
        inputs += list((ROOT / "desktop/requirements").glob("*")) + [ROOT / "desktop/runtime_entry.py"]
        return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs if path.is_file()}
    source_identity = fingerprints()
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir",
        "--name", "asr-desktop-runtime", "--target-architecture", "arm64",
        "--distpath", str(BUILD / "frozen"), "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD / "spec"), "--paths", str(ROOT / "src"),
        "--additional-hooks-dir", str(ROOT / "desktop/packaging/hooks"),
        "--collect-data", "asr_desktop",
        "--add-data", str(ROOT / "src/asr_desktop/data") + ":asr_desktop/data",
        "--collect-data", "tiktoken_ext", "--collect-data", "transformers",
        "--hidden-import", "transformers.models.qwen3.configuration_qwen3",
        "--hidden-import", "transformers.models.qwen3.modeling_qwen3",
        "--hidden-import", "transformers.models.qwen2.tokenization_qwen2_fast",
        "--copy-metadata", "modelscope", "--copy-metadata", "tiktoken",
        "--copy-metadata", "opencc-python-reimplemented",
        "--exclude-module", "tensorflow", "--exclude-module", "jax",
        "--exclude-module", "IPython", "--exclude-module", "pytest",
        "--exclude-module", "tkinter", str(ROOT / "desktop/runtime_entry.py"),
    ]
    for line in (ROOT / "desktop/requirements/runtime.lock").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            command[3:3] = ["--copy-metadata", line.split("==", 1)[0]]
    if args.clean:
        command.insert(3, "--clean")
    if not args.install_only:
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
        if fingerprints() != source_identity:
            raise SystemExit("Runtime sources changed during freezing. Rebuild before installing this artifact.")
        (BUILD / "runtime-build-inputs.json").write_text(json.dumps(source_identity, sort_keys=True, indent=2) + "\n")
    if args.freeze_only:
        print(BUILD / "frozen/asr-desktop-runtime")
        return
    if not all((media / name).is_file() for name in ("ffmpeg", "ffprobe")):
        raise SystemExit("Build standalone media tools first: python3 desktop/scripts/build_media.py")
    resources = app / "Contents/Resources"
    shutil.copytree(BUILD / "frozen/asr-desktop-runtime", resources / "runtime/asr-desktop-runtime", dirs_exist_ok=True)
    shutil.copytree(media, resources / "media", dirs_exist_ok=True)
    print(app)


if __name__ == "__main__":
    main()
