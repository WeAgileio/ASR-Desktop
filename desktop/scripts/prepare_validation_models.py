#!/usr/bin/env python3
"""Prepare verified build-only model snapshots without changing user hub caches."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


def matches(path, asset):
    if not path.is_file() or path.stat().st_size != asset["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == asset["sha256"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache/modelscope/hub/models")
    args = parser.parse_args()
    catalog = json.loads((ROOT / "src/asr_desktop/data/models.json").read_text())
    output = ROOT / "build/desktop/validation-models"
    components = {}
    for name, component in catalog["components"].items():
        directory = output / name / component["revision"]
        for asset in component["assets"]:
            relative = Path(asset["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe model asset path")
            destination = directory / relative
            if matches(destination, asset):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            partial = destination.with_name(destination.name + ".download")
            cached = args.cache / component["repository"] / relative
            if matches(cached, asset):
                # APFS copy-on-write gives validation its own file, not a writable
                # hard link into the user's working model cache.
                cloned = subprocess.run(["/bin/cp", "-c", str(cached), str(partial)], capture_output=True)
                if cloned.returncode:
                    shutil.copyfile(cached, partial)
            else:
                print(f"Downloading {name}/{asset['path']} ({asset['size']} bytes)", flush=True)
                with urllib.request.urlopen(asset["url"], timeout=90) as source, partial.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            if not matches(partial, asset):
                raise ValueError("Rejected asset: " + str(relative))
            partial.replace(destination)
        components[name] = str(directory)
        print(f"Verified {name}: {len(component['assets'])} assets", flush=True)
    manifest = {"schema_version": 1, "component_paths": components,
                "snapshots": {model["id"]: model["snapshot_id"] for model in catalog["models"]}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output / "manifest.json")


if __name__ == "__main__":
    main()
