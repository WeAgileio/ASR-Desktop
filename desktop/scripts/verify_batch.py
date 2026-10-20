#!/usr/bin/env python3
"""Maintainer integration test: packaged CLI -> coordinator -> real worker -> exports."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from asr_desktop.models import ModelStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=ROOT / "build/desktop/ASR Desktop.app")
    args = parser.parse_args()
    app = args.app.resolve()
    base = ROOT / "build/desktop/batch-integration"
    base.mkdir(parents=True, exist_ok=True)
    data = base / ("data-" + str(time.time_ns()))
    catalog = json.loads((ROOT / "src/asr_desktop/data/models.json").read_text())
    manifest = json.loads((ROOT / "build/desktop/validation-models/manifest.json").read_text())
    def forbidden(*args, **kwargs):
        raise AssertionError("Integration model fixtures must not use network")
    store = ModelStore(data / "models", catalog, opener=forbidden)
    for model in catalog["models"]:
        for component in model["components"]:
            source = Path(manifest["component_paths"][component])
            target = store.root / "staging" / model["snapshot_id"] / component
            target.mkdir(parents=True, exist_ok=True)
            for asset in catalog["components"][component]["assets"]:
                destination = target / asset["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["/bin/cp", "-c", str(source / asset["path"]), str(destination)], check=True)
        assert store.prepare(model["id"])["ready"]
    cli = app / "Contents/MacOS/asr-desktop"
    with tempfile.TemporaryDirectory(prefix="asr-batch-control-", dir="/private/tmp") as directory:
        environment = os.environ.copy()
        environment.update(PATH="/usr/bin:/bin", ASR_DESKTOP_RUN_DIR=directory, ASR_DESKTOP_DATA_DIR=str(data),
                           ASR_DESKTOP_CACHE_DIR=str(base / "media-cache"), PYTHONHOME="/invalid-python", PYTHONPATH="/invalid-python")
        def run(arguments, expected=0):
            result = subprocess.run([str(cli), *arguments, "--json"], env=environment, capture_output=True, text=True, timeout=180)
            if result.returncode != expected:
                raise AssertionError({"arguments": arguments, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
            # wait/watch may produce several NDJSON records; regular commands produce one.
            values = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            return values[-1]
        started = False
        report = {"app": str(app), "data": str(data), "cases": []}
        try:
            run(["service", "start"])
            started = True
            models = run(["models", "list"])
            assert all(model["ready"] for model in models["result"])
            for model in ("paraformer", "fun-asr-nano"):
                destination = base / (model + "-" + str(time.time_ns()))
                sources = [ROOT / "build/desktop/smoke-models/zh.wav", ROOT / "build/desktop/smoke-models/mixed.wav"]
                response = run(["submit", *(str(p) for p in sources), "--output-dir", str(destination),
                                "--model", model, "--formats", "txt,srt,json", "--device", "auto"])
                identifier = response["result"]["id"]
                run(["queue", "resume"])
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    batch = run(["jobs", "show", identifier])["result"]
                    states = batch["counts"]
                    if sum(states.get(s, 0) for s in ("completed", "failed", "cancelled", "interrupted")) == 2:
                        break
                    time.sleep(.5)
                assert batch["counts"] == {"completed": 2}, batch
                for job in batch["jobs"]:
                    assert job["actual_device"] == "cpu" and job["device_reason"] == "insufficient_evidence", job
                    for fmt, path in job["outputs"].items():
                        output = Path(path)
                        assert output.is_file() and output.stat().st_size > 0
                        if fmt == "txt":
                            assert "台灣繁體" in output.read_text()
                        if fmt == "srt":
                            assert " --> " in output.read_text()
                        if fmt == "json":
                            assert json.loads(output.read_text())["full_text"].strip()
                report["cases"].append({"model": model, "batch_id": identifier, "counts": batch["counts"],
                                        "outputs": [j["outputs"] for j in batch["jobs"]]})
                (base / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps(report["cases"][-1], ensure_ascii=False), flush=True)
        finally:
            if started:
                run(["service", "stop", "--force"])
        print(base / "report.json")


if __name__ == "__main__":
    main()
