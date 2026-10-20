#!/usr/bin/env python3
"""Collect installed distribution notices and the pinned Python license into the App."""

from importlib import metadata
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    target = ROOT / "build/desktop/ASR Desktop.app/Contents/Resources/licenses"
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for lock in ("runtime.lock", "build.lock"):
        for line in (ROOT / "desktop/requirements" / lock).read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, version = line.split("==", 1)
            if any(row["name"] == name for row in rows):
                continue
            distribution = metadata.distribution(name)
            if distribution.version != version:
                raise SystemExit("Run notice collection in the locked packaging environment")
            package = target / name
            package.mkdir(exist_ok=True)
            (package / "METADATA.txt").write_text(distribution.read_text("METADATA") or json.dumps(dict(distribution.metadata), ensure_ascii=False))
            files = []
            for entry in distribution.files or []:
                path = Path(str(entry))
                if (path.name.lower().startswith(("license", "copying", "notice", "copyright"))
                    and path.suffix.lower() not in (".py", ".pyc", ".so", ".dylib", ".exe", ".a", ".lib") and ".." not in path.parts):
                    source = distribution.locate_file(entry)
                    if source.is_file():
                        output = package / path
                        output.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, output)
                        files.append(str(output.relative_to(target)))
            rows.append({"name": name, "version": version, "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License"),
                         "notices": files, "project_url": distribution.metadata.get_all("Project-URL") or []})
    python_license = Path(sys.base_prefix) / "lib/python3.11/LICENSE.txt"
    shutil.copyfile(python_license, target / "Python-LICENSE.txt")
    (target / "inventory.json").write_text(json.dumps({"python": sys.version, "distributions": rows}, ensure_ascii=False, indent=2) + "\n")
    media = json.loads((ROOT / "desktop/requirements/media.json").read_text())
    (target / "README.txt").write_text(
        "ASR Desktop third-party notices\n\nPython: Python-LICENSE.txt\n"
        "Python distributions: inventory.json and package subdirectories\n"
        "PyInstaller bootloader: pyinstaller notices, including its distribution exception\n"
        "FFmpeg/FFprobe: ../media/ licenses and build provenance\n"
        "Pinned FFmpeg source/build configuration: " + json.dumps(media, ensure_ascii=False, indent=2) + "\n"
        "Models are downloaded separately. Their immutable catalog records include provider license-source URLs.\n")
    print(target)


if __name__ == "__main__":
    main()
