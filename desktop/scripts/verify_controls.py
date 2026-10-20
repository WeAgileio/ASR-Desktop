#!/usr/bin/env python3
"""Exercise real packaged cancellation/retry/calibration and observer contracts."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=ROOT / "build/desktop/ASR Desktop.app")
    args = parser.parse_args()
    app = args.app.resolve()
    prior = json.loads((ROOT / "build/desktop/batch-integration/report.json").read_text())
    output = ROOT / "build/desktop/control-integration"
    output.mkdir(parents=True, exist_ok=True)
    cli = app / "Contents/MacOS/asr-desktop"
    with tempfile.TemporaryDirectory(prefix="asr-control-integration-", dir="/private/tmp") as directory:
        env = {**os.environ, "PATH": "/usr/bin:/bin", "ASR_DESKTOP_RUN_DIR": directory,
               "ASR_DESKTOP_DATA_DIR": prior["data"], "ASR_DESKTOP_CACHE_DIR": str(output / "media-cache")}
        def command(arguments, expected=0):
            result = subprocess.run([str(cli), *arguments, "--json"], env=env, capture_output=True, text=True, timeout=180)
            assert result.returncode == expected, {"args": arguments, "code": result.returncode, "out": result.stdout, "err": result.stderr}
            values = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            return values[-1] if values else {}
        def until(identifier, states):
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                job = command(["jobs", "show", identifier])["result"]
                if job["state"] in states:
                    return job
                time.sleep(.1)
            raise AssertionError("Timed out waiting for " + identifier)
        command(["service", "start"])
        report = {}
        try:
            command(["settings", "set", "device", "bananas"], expected=2)
            source = ROOT / "build/desktop/smoke-models/mixed.wav"
            batch = command(["submit", str(source), "--output-dir", str(output / ("cancel-" + str(time.time_ns()))), "--model", "fun-asr-nano"])["result"]
            identifier = batch["job_ids"][0]
            command(["queue", "resume"])
            until(identifier, {"running"})
            refusal = command(["models", "remove", "fun-asr-nano"], expected=3)
            assert refusal["error"]["code"] == "model_in_use"
            command(["jobs", "cancel", identifier])
            assert until(identifier, {"cancelled", "failed", "completed"})["state"] == "cancelled"
            command(["jobs", "watch", identifier], expected=1)
            report["cancelled_job"] = identifier
            request = ["jobs", "retry", identifier, "--request-id", "control-integration-retry-" + str(time.time_ns())]
            first = command(request)
            second = command(request)
            assert first["result"] == second["result"]
            until(identifier, {"running"})
            with (output / "observer.ndjson").open("wb") as stream, (output / "observer.stderr").open("wb") as errors:
                observer = subprocess.Popen([str(cli), "jobs", "watch", identifier], env=env, stdout=stream, stderr=errors)
                time.sleep(.5)
                observer.send_signal(signal.SIGINT)
                assert observer.wait(timeout=5) == 130
            active = command(["jobs", "show", identifier])["result"]
            assert active["state"] in ("running", "completed")
            result = until(identifier, {"completed", "failed", "cancelled"})
            assert result["state"] == "completed", result
            report.update(retry_idempotency=True, observer_exit_code=130, observation_did_not_cancel_job=True,
                          real_retry_completed=True, model_removal_refused_while_active=True)
            calibration = command(["device", "calibrate", str(source), "--model", "paraformer"])["result"]
            for job_id, expected in zip(calibration["job_ids"], ("cpu", "mps")):
                job = until(job_id, {"completed", "failed", "cancelled"})
                assert job["state"] == "completed" and job["actual_device"] == expected, job
            report["calibration"] = calibration
            explanation = command(["device", "explain"])["result"]
            assert explanation["device"] == "cpu" and explanation["eligible_mps"] == 0
            report["auto_remains_cpu_without_quality_baseline"] = True
            conflict_output = output / ("partial-failure-" + str(time.time_ns()))
            sources = [ROOT / "build/desktop/smoke-models/zh.wav", source]
            options = ["--output-dir", str(conflict_output), "--model", "paraformer"]
            plan = command(["submit", *(str(p) for p in sources), *options, "--preview"])["result"]
            conflict_path = Path(plan["entries"][0]["outputs"]["txt"])
            conflict_path.parent.mkdir(parents=True, exist_ok=True)
            conflict_path.write_text("existing output fixture")
            partial = command(["submit", *(str(p) for p in sources), *options])["result"]
            partial_result = command(["jobs", "watch", partial["id"]], expected=1)["result"]
            assert partial_result["counts"] == {"completed": 1, "failed": 1}
            assert conflict_path.read_text() == "existing output fixture"
            report["partial_failure_continued_and_preserved_existing_output"] = True
            report["tested_exit_codes"] = [0, 1, 2, 3, 130]
            link_directory = output / ("bin-" + str(time.time_ns()))
            command(["cli", "install", "--directory", str(link_directory)])
            assert (link_directory / "asr-desktop").is_symlink()
            conflict = output / ("conflict-" + str(time.time_ns()))
            conflict.mkdir()
            (conflict / "asr-desktop").write_text("existing command")
            command(["cli", "install", "--directory", str(conflict)], expected=3)
            assert (conflict / "asr-desktop").read_text() == "existing command"
            report["command_link_did_not_overwrite_conflict"] = True
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(output / "report.json")
        finally:
            command(["service", "stop", "--force"])


if __name__ == "__main__":
    main()
