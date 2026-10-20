#!/usr/bin/env python3
"""Run packaged CPU/MPS model smoke cases on public model-provided examples."""

import json
import os
from pathlib import Path
import platform
import subprocess
import wave


ROOT = Path(__file__).resolve().parents[2]


def main():
    app = ROOT / "build/desktop/ASR Desktop.app"
    output = ROOT / "build/desktop/smoke-models"
    output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((ROOT / "src/asr_desktop/data/models.json").read_text())
    manifest = json.loads((ROOT / "build/desktop/validation-models/manifest.json").read_text())
    examples = Path.home() / ".cache/modelscope/hub/models/FunAudioLLM/Fun-ASR-Nano-2512/example"
    media = app / "Contents/Resources/media"
    helper = app / "Contents/MacOS/ASRDesktopHelper"
    environment = os.environ.copy()
    environment.update({"PATH": "/usr/bin:/bin", "PYTHONPATH": "/nonexistent-asr-python",
                        "PYTHONHOME": "/nonexistent-asr-python", "HF_HUB_OFFLINE": "1",
                        "TRANSFORMERS_OFFLINE": "1"})
    waves = []
    for language in ("zh", "en"):
        source = examples / (language + ".mp3")
        if not source.is_file():
            raise SystemExit("Missing public model example: " + str(source))
        destination = output / (language + ".wav")
        subprocess.run([str(media / "ffmpeg"), "-v", "error", "-y", "-i", str(source),
                        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)],
                       env=environment, check=True)
        waves.append(destination)
    mixed = output / "mixed.wav"
    with wave.open(str(mixed), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        for path in waves:
            with wave.open(str(path), "rb") as source:
                target.writeframes(source.readframes(source.getnframes()))
    records = []
    for model in catalog["models"]:
        if manifest["snapshots"][model["id"]] != model["snapshot_id"]:
            raise ValueError("Validation model manifest is stale")
        primary = "nano" if model["id"] == "fun-asr-nano" else "paraformer"
        for device in ("cpu", "mps"):
            for case, audio in (("mandarin", waves[0]), ("mixed", mixed)):
                identifier = f"{model['id']}-{device}-{case}"
                config = {"model": model["id"], "device": device, "audio": str(audio),
                          "component_paths": {key:manifest["component_paths"][key] for key in model["components"]},
                          "revision": catalog["components"][primary]["revision"], "snapshot_id": model["snapshot_id"]}
                config_path = output / (identifier + ".config.json")
                config_path.write_text(json.dumps(config, indent=2) + "\n")
                print("Running " + identifier, flush=True)
                try:
                    completed = subprocess.run([str(helper), "--smoke-config", str(config_path)],
                                               cwd="/private/tmp", env=environment, capture_output=True,
                                               text=True, timeout=600)
                    (output / (identifier + ".stderr.log")).write_text(completed.stderr)
                    (output / (identifier + ".stdout.json")).write_text(completed.stdout)
                    record = {"case": identifier, "exit_code": completed.returncode}
                    if completed.returncode == 0:
                        result = json.loads(completed.stdout)
                        transcript = result["transcript"]
                        assert transcript["full_text"].strip()
                        assert transcript["units"]
                        previous = -1
                        for unit in transcript["units"]:
                            assert 0 <= unit["start_ms"] <= unit["end_ms"] <= result["duration_ms"]
                            assert unit["start_ms"] >= previous
                            previous = unit["start_ms"]
                        record.update(success=True, elapsed_seconds=result["elapsed_seconds"],
                                      units=len(transcript["units"]), peak_rss_mb=result["peak_rss_mb"])
                    else:
                        record.update(success=False, error=completed.stderr.splitlines()[-1:] or ["unknown"])
                except (subprocess.TimeoutExpired, ValueError, AssertionError) as error:
                    record = {"case": identifier, "success": False, "error": str(error)}
                records.append(record)
                report = {"machine": platform.machine(), "macos": platform.mac_ver()[0],
                          "scope": "Short public-example smoke only; not a long-form quality or performance baseline.",
                          "records": records}
                (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
                print(json.dumps(record), flush=True)
    if not all(record.get("success") for record in records):
        raise SystemExit("One or more model/device cases failed; inspect the compatibility report.")


if __name__ == "__main__":
    main()
