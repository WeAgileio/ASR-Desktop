#!/usr/bin/env python3
"""Refresh official Whisper assets, retaining existing FunASR snapshots.

Only this explicit maintainer operation resolves branches. Inference never does.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "taiwan-tongues": ("adi-gov-tw/Taiwan-Tongues-ASR-CE-v1.0", "Taiwan Tongues ASR CE", "faster-whisper",
                        ["config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.json"]),
    "breeze-asr-25": ("MediaTek-Research/Breeze-ASR-25", "Breeze ASR 25", "transformers-whisper",
                      ["config.json", "generation_config.json", "model.safetensors", "preprocessor_config.json",
                       "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json",
                       "normalizer.json", "merges.txt", "vocab.json"]),
}


def read(url):
    with urlopen(url, timeout=60) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "src/asr_desktop/data/models.json")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    for identifier, (repository, name, engine, files) in SOURCES.items():
        info = json.loads(read("https://huggingface.co/api/models/" + repository + "?blobs=true"))
        revision = info["sha"]
        entries = {entry["rfilename"]: entry for entry in info["siblings"]}
        assets = []
        for path in files + ["README.md", "LICENSE"]:
            entry = entries[path]
            url = "https://huggingface.co/" + repository + "/resolve/" + revision + "/" + quote(path)
            digest = entry.get("lfs", {}).get("sha256")
            if digest is None:
                data = read(url)
                if len(data) != entry["size"]:
                    raise ValueError("Asset metadata size mismatch: " + path)
                digest = hashlib.sha256(data).hexdigest()
            assets.append({"path": path, "url": url, "size": entry["size"], "sha256": digest})
        component = {"repository": repository, "revision": revision, "assets": assets,
                     "license_source": "https://huggingface.co/" + repository + "/blob/" + revision + "/LICENSE"}
        catalog["components"][identifier] = component
        execution = {"engine": engine, "primary": identifier, "devices": ["cpu"], "hotwords": False,
                     "required_files": {identifier: files},
                     "parameters": {"compute_type": "int8", "beam_size": 5} if engine == "faster-whisper" else {"num_beams": 1}}
        identity = {"components": {identifier: component}, "execution": execution}
        snapshot = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        requirements = {"platform": "macOS 14 以上，Apple Silicon（M1 以上）", "cpu": "支援 CPU 本機離線推論",
                        "gpu": "此版本未提供 GPU／MPS 加速", "minimum_memory": "最低記憶體需求尚未實測驗證",
                        "recommended_memory": "建議 32 GB RAM（官方 CPU 建議，非最低需求）" if identifier == "taiwan-tongues" else "建議 16 GB RAM 以上（工程估算，非已驗證最低需求）",
                        "source": "https://github.com/adi-gov-tw/Taiwan-Tongues-ASR-CE#建議硬體規格" if identifier == "taiwan-tongues" else "https://huggingface.co/MediaTek-Research/Breeze-ASR-25",
                        "notes": "實際用量隨錄音長度與解碼設定而變，CPU 轉錄可能耗時。"}
        model = {"id": identifier, "display_name": name, "components": [identifier], "snapshot_schema": 2,
                 "snapshot_id": snapshot, "execution": execution, "requirements": requirements,
                 "download_bytes": sum(asset["size"] for asset in assets)}
        catalog["models"] = [m for m in catalog["models"] if m["id"] != identifier] + [model]
        print(identifier, revision, model["download_bytes"], flush=True)
    for model in catalog["models"]:
        if model["id"] not in SOURCES:
            model.setdefault("display_name", {"fun-asr-nano": "Fun-ASR-Nano", "paraformer": "Paraformer"}.get(model["id"], model["id"]))
            model.setdefault("requirements", {"platform": "macOS 14 以上，Apple Silicon（M1 以上）",
                "cpu": "支援 CPU 本機離線推論", "gpu": "可選 MPS；相容性依模型與電腦而異",
                "minimum_memory": "最低記憶體需求尚未實測驗證", "recommended_memory": "建議 16 GB RAM 以上（工程估算）",
                "notes": "下載量與準備空間如下；記憶體建議不作為執行門檻。"})
    args.catalog.write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
