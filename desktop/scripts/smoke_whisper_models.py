#!/usr/bin/env python3
"""Run each real CPU model in an offline disposable source or frozen helper."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from asr_desktop.models import ModelStore
from asr_srt.domain import Transcript, SubtitleSettings
from asr_srt.srt import render_srt
from asr_srt.subtitle import segment_transcript

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path)
    parser.add_argument("--model", action="append", choices=("taiwan-tongues", "breeze-asr-25"))
    parser.add_argument("--audio", type=Path, default=ROOT / "build/desktop/local-whisper/sample.wav")
    args = parser.parse_args()
    root = ROOT / "build/desktop/local-whisper"
    output = root / ("frozen-smoke" if args.helper else "source-smoke")
    output.mkdir(parents=True, exist_ok=True)
    store = ModelStore(root / "models")
    reports = []
    for identifier in args.model or ("taiwan-tongues", "breeze-asr-25"):
        definition = store.definition(identifier)
        paths = store.local_paths(identifier)
        config = {"model": identifier, "model_definition": definition, "component_paths": paths,
                  "snapshot_id": definition["snapshot_id"], "revision": definition["component_definitions"][identifier]["revision"],
                  "audio": str(args.audio.resolve()), "device": "cpu"}
        config_path = output / (identifier + "-config.json")
        config_path.write_text(json.dumps(config))
        command = [str(args.helper.resolve())] if args.helper else [sys.executable, str(ROOT / "desktop/runtime_entry.py")]
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}
        if args.helper:
            env.update(PATH="/usr/bin:/bin", PYTHONPATH="/nonexistent-asr", PYTHONHOME="/nonexistent-asr")
        with (output / (identifier + "-stderr.log")).open("w") as log:
            result = subprocess.run(command + ["--smoke-config", str(config_path)], env=env,
                                    stdout=subprocess.PIPE, stderr=log, text=True, timeout=1800)
        if result.returncode:
            raise RuntimeError(f"{identifier} failed; inspect {output / (identifier + '-stderr.log')}")
        report = json.loads(result.stdout)
        transcript = Transcript.from_dict(report["transcript"])
        if not transcript.full_text.strip() or not transcript.units:
            raise RuntimeError("Real speech produced no timestamped transcript: " + identifier)
        (output / (identifier + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        (output / (identifier + ".srt")).write_text(render_srt(segment_transcript(transcript, SubtitleSettings())))
        reports.append({k: v for k, v in report.items() if k != "transcript"})
        print(identifier, transcript.full_text, "CPU offline OK", flush=True)
    (output / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
