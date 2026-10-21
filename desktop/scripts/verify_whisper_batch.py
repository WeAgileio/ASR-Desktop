#!/usr/bin/env python3
"""Verify prepared Whisper models through the packaged CLI and actual workers."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    base = ROOT / "build/desktop/local-whisper"
    cli = args.app.resolve() / "Contents/MacOS/asr-desktop"
    with tempfile.TemporaryDirectory(prefix="asr-whisper-batch-", dir="/private/tmp") as run_dir:
        env = {**os.environ, "ASR_DESKTOP_RUN_DIR": run_dir, "ASR_DESKTOP_DATA_DIR": str(base),
               "ASR_DESKTOP_CACHE_DIR": str(base / "batch-cache"), "PATH": "/usr/bin:/bin",
               "PYTHONHOME": "/nonexistent-asr", "PYTHONPATH": "/nonexistent-asr"}
        def run(*arguments):
            result = subprocess.run([str(cli), *arguments, "--json"], env=env,
                                    capture_output=True, text=True, timeout=900)
            if result.returncode:
                raise AssertionError({"args": arguments, "stdout": result.stdout, "stderr": result.stderr})
            return json.loads(result.stdout.splitlines()[-1])["result"]
        # Close any GUI-only validation service before using this same isolated DB.
        # The caller must stop that service explicitly; never affect a user's service.
        run("service", "start")
        report = {"app": str(args.app.resolve()), "cases": []}
        try:
            models = run("models", "list")
            report["models"] = [{key: model.get(key) for key in ("id", "ready", "requirements", "execution")} for model in models]
            assert len(models) == 4
            for model in models:
                assert model["requirements"]["platform"] and model["requirements"]["minimum_memory"]
            run("queue", "resume")
            for identifier in ("taiwan-tongues", "breeze-asr-25"):
                selected = next(model for model in models if model["id"] == identifier)
                assert selected["ready"] and selected["execution"]["devices"] == ["cpu"]
                output = base / "batch-outputs" / (identifier + "-" + str(time.time_ns()))
                result = run("submit", str(base / "sample.wav"), "--output-dir", str(output),
                             "--model", identifier, "--device", "auto", "--formats", "txt,srt,json", "--wait")
                assert result["counts"] == {"completed": 1}, result
                job = result["jobs"][0]
                assert job["actual_device"] == "cpu", job
                assert job["device_reason"] == "model_cpu_only", job
                for fmt, path in job["outputs"].items():
                    value = Path(path).read_text()
                    assert value.strip()
                    if fmt == "srt":
                        assert " --> " in value
                    if fmt == "json":
                        assert json.loads(value)["units"]
                report["cases"].append({"model": identifier, "job_id": job["id"],
                    "device": job["actual_device"], "outputs": job["outputs"], "state": job["state"]})
                print(identifier + " packaged CLI / worker / TXT / SRT / JSON OK", flush=True)
            (base / "batch-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            run("queue", "pause")
            run("service", "stop")


if __name__ == "__main__":
    main()
