"""Disposable inference process. Never writes the coordinator database."""

from contextlib import redirect_stdout
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sys
import time

from .database import StateError
from .exports import Delivery
from .intake import source_matches
from .models import atomic_json
from .offline import disable_network, local_adapter
from .resources import ResourceMonitor


def run(config_path):
    config = json.loads(Path(config_path).read_text())
    job, attempt = config["job"], config["attempt_id"]
    cancelled = False
    output = sys.stdout
    last_progress = 0
    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGUSR1, cancel)
    def check():
        if cancelled or Path(config["cancel_file"]).exists():
            raise StateError("cancelled", "Transcription cancelled")
    def emit(kind, value):
        output.write(json.dumps({"attempt_id": attempt, "kind": kind, "value": value}, ensure_ascii=False) + "\n")
        output.flush()
    def progress(event):
        nonlocal last_progress
        check()
        now = time.monotonic()
        if event.terminal or now - last_progress >= 0.25:
            emit("progress", asdict(event))
            last_progress = now
    started = time.monotonic()
    monitor = ResourceMonitor()
    monitor.start()
    try:
        disable_network()
        check()
        if not source_matches(job["source"], job["fingerprint"]):
            raise StateError("source_changed", "Source content changed after acceptance; submit it again")
        delivery = Delivery(job, config["workspace"])
        delivery.preflight()
        with redirect_stdout(sys.stderr):
            from asr_srt.config import JobConfig
            from asr_srt.device import DeviceDecision
            from asr_srt.domain import SubtitleSettings
            from asr_srt.workflow import LocalTranscriptionService
            options = job["settings"]
            revisions = {key: value["revision"] for key, value in job["model_definition"]["component_definitions"].items()}
            def factory(model):
                adapter = local_adapter(model, config["component_paths"], revisions)
                # Include all auxiliaries in core cache/checkpoint identity.
                adapter.model_revision = job["snapshot"]
                return adapter
            decision = config["device_decision"]
            device, reason = decision["device"], decision["reason"]
            config_value = JobConfig(input_path=Path(job["source"]), model=options["model"], device=device,
                                     language=options["language"], hotwords=tuple(options["hotwords"]),
                                     output_path=delivery.root / "internal.srt", cache_dir=delivery.root / "cache",
                                     overwrite=True, traditional=False,
                                     subtitle=SubtitleSettings(max_display_units=options["max_chars"],
                                                               max_duration_ms=options["max_duration_ms"],
                                                               target_min_duration_ms=min(1000, options["max_duration_ms"])))
            service = LocalTranscriptionService(adapter_factory=factory, progress=progress, cancel_check=check,
                                                 media_cache_dir=Path(config["media_cache"]),
                                                 device_resolver=lambda requested: DeviceDecision(requested, device, decision["fallback_allowed"], reason))
            result = service.run(config_value)
            check()
            if not source_matches(job["source"], job["fingerprint"]):
                raise StateError("source_changed", "Source changed during transcription")
            ledger = delivery.publish(result.transcript, check)
        summary = {"state": "completed", "actual_device": result.transcript.metadata.device,
                   "device_reason": "mps_compatibility_cpu_fallback" if device == "mps" and result.transcript.metadata.device == "cpu" and not result.cache_hit else reason,
                   "cache_hit": result.cache_hit,
                   "elapsed_seconds": time.monotonic() - started, "outputs_ledger": ledger,
                   "performance_spans": [asdict(span) for span in result.performance_spans]}
    except Exception as error:
        from asr_srt.errors import MPSCompatibilityError
        cause = error
        mps_error = isinstance(error, MPSCompatibilityError)
        while cause.__cause__ is not None:
            cause = cause.__cause__
            mps_error = mps_error or isinstance(cause, MPSCompatibilityError)
        code = "mps_compatibility" if mps_error else getattr(cause, "code", "transcription_failed")
        summary = {"state": "cancelled" if cancelled or code == "cancelled" else "failed",
                   "error": {"code": code, "message": str(error)}, "elapsed_seconds": time.monotonic() - started}
    summary["resources"] = monitor.finish()
    atomic_json(Path(config["result_path"]), {"attempt_id": attempt, **summary})
    emit("finished", summary)
    return 0 if summary["state"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
