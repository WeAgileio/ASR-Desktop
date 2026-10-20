#!/usr/bin/env python3
"""Exercise the frozen helper and standalone media tools without developer paths."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import wave


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=ROOT / "build/desktop/ASR Desktop.app")
    args = parser.parse_args()
    app = args.app.resolve()
    environment = os.environ.copy()
    environment.update({"PATH": "/usr/bin:/bin", "PYTHONPATH": "/nonexistent-asr-python",
                        "PYTHONHOME": "/nonexistent-asr-python", "HF_HUB_OFFLINE": "1",
                        "TRANSFORMERS_OFFLINE": "1"})
    helper = app / "Contents/MacOS/ASRDesktopHelper"
    completed = subprocess.run([str(helper), "--diagnose"], env=environment, cwd="/private/tmp",
                               capture_output=True, text=True, timeout=180)
    report_path = ROOT / "build/desktop/runtime-verification.json"
    stderr_path = ROOT / "build/desktop/runtime-verification.stderr.log"
    stderr_path.write_text(completed.stderr)
    try:
        report = json.loads(completed.stdout)
    except ValueError:
        report = {"ready": False, "stdout": completed.stdout}
    report["exit_code"] = completed.returncode
    report["developer_path_removed"] = True
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if completed.returncode or not report.get("ready") or not report.get("frozen"):
        raise SystemExit("Frozen runtime validation failed; inspect " + str(report_path))
    with tempfile.TemporaryDirectory(prefix="asr-media-") as directory:
        source = Path(directory) / "input with spaces.wav"
        target = Path(directory) / "output.wav"
        with wave.open(str(source), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(44100)
            output.writeframes(b"\0" * 4410 * 2 * 2)
        media = app / "Contents/Resources/media"
        subprocess.run([str(media / "ffmpeg"), "-v", "error", "-i", str(source), "-vn", "-ac", "1",
                        "-ar", "16000", "-c:a", "pcm_s16le", str(target)], env=environment, check=True)
        probe = subprocess.run([str(media / "ffprobe"), "-v", "error", "-show_entries",
                                "stream=sample_rate,channels", "-of", "json", str(target)],
                               env=environment, check=True, capture_output=True, text=True)
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream["sample_rate"] == "16000" and stream["channels"] == 1, stream
        report["media_normalization_verified"] = True
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report_path)


if __name__ == "__main__":
    main()
