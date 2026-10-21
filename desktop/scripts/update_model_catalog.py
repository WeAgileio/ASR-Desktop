#!/usr/bin/env python3
"""Resolve public model snapshots to immutable commits and hashed file manifests.

This is a maintainer build operation. Installed Apps use the resulting catalog
and never resolve a moving branch during inference.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote, urlencode
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
REPOSITORIES = {
    "nano": "FunAudioLLM/Fun-ASR-Nano-2512",
    "paraformer": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "punctuation": "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
}


def fetch(url):
    with urlopen(url, timeout=60) as response:
        payload = json.load(response)
    if payload.get("Code") != 200:
        raise ValueError("Model metadata request failed: " + str(payload.get("Message")))
    return payload["Data"]


def needed(path):
    parts = Path(path).parts
    if not parts or path.startswith("/") or ".." in parts:
        raise ValueError("Unsafe model asset path: " + path)
    if any(part.startswith(".") for part in parts):
        return False
    if parts[0] in {"example", "examples", "images", "fig", ".gitattributes", ".gitignore"}:
        return False
    if Path(path).suffix.lower() in {".wav", ".mp3", ".mp4", ".png", ".jpg", ".jpeg", ".onnx"}:
        return False
    if Path(path).suffix.lower() in {".py", ".sh", ".exe", ".dylib", ".so"}:
        raise ValueError("Model requires executable code that is not bundled: " + path)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-cache", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "src/asr_desktop/data/models.json")
    args = parser.parse_args()
    previous = json.loads(args.output.read_text()) if args.output.exists() else {"models": [], "components": {}}
    components = {}
    for identifier, repository in REPOSITORIES.items():
        api = "https://modelscope.cn/api/v1/models/" + repository
        revision = fetch(api + "/commits?Ref=master&PageNumber=1&PageSize=1")["Commit"][0]["Id"]
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("Expected an immutable commit ID")
        entries = fetch(api + "/repo/files?" + urlencode({"Revision": revision, "Recursive": "true"}))["Files"]
        assets = []
        for entry in entries:
            if entry["Type"] != "blob" or not needed(entry["Path"]):
                continue
            if not re.fullmatch(r"[a-f0-9]{64}", entry["Sha256"]) or entry["Size"] <= 0:
                raise ValueError("Missing model asset size/hash: " + entry["Path"])
            path = entry["Path"]
            asset = {"path": path, "sha256": entry["Sha256"], "size": entry["Size"],
                     "url": api + "/repo?" + urlencode({"Revision": revision, "FilePath": path})}
            if args.verify_cache:
                local = args.verify_cache / repository / path
                if not local.is_file():
                    raise ValueError("Missing cached asset: " + str(local))
                digest = hashlib.sha256()
                with local.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if local.stat().st_size != asset["size"] or digest.hexdigest() != asset["sha256"]:
                    raise ValueError("Cached asset does not match selected snapshot: " + str(local))
            assets.append(asset)
        if not {"model.pt", "config.yaml"} <= {asset["path"] for asset in assets}:
            raise ValueError("Missing required model weights/configuration")
        components[identifier] = {
            "repository": repository, "revision": revision,
            "license_source": "https://modelscope.cn/models/" + quote(repository, safe="/") + "/file/view/" + revision + "/README.md",
            "assets": sorted(assets, key=lambda item: item["path"]),
        }
        print(f"{identifier}: {revision}, {len(assets)} assets", flush=True)
    models = []
    for name, component_ids in (("fun-asr-nano", ["nano", "vad"]),
                                ("paraformer", ["paraformer", "vad", "punctuation"])):
        identity = {key: components[key] for key in component_ids}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        models.append({"id": name, "snapshot_id": digest, "components": component_ids,
                       "download_bytes": sum(asset["size"] for key in component_ids for asset in components[key]["assets"])})
    # A FunASR refresh must not erase separately maintained engine registrations.
    for model in models:
        old = next((m for m in previous["models"] if m["id"] == model["id"]), {})
        model.update({key: old[key] for key in ("display_name", "requirements") if key in old})
    models.extend(model for model in previous["models"] if model["id"] not in {m["id"] for m in models})
    components = {**previous["components"], **components}
    catalog = {"schema_version": 1, "default_model": "fun-asr-nano", "components": components, "models": models}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    temporary.replace(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
