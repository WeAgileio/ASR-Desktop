"""Explicit native RQ/MPS smoke test; uses an isolated Redis queue.

Run with PYTHONPATH=src:evaluation and the native worker interpreter.
No Drive writes and no transcript text is included in the report.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import threading
import time
import uuid


def host_metrics():
    result = {}
    for name, command in {
        "swap": ["sysctl", "vm.swapusage"],
        "memory_pressure": ["memory_pressure", "-Q"],
    }.items():
        p = subprocess.run(command, capture_output=True, text=True, timeout=10)
        result[name] = p.stdout.strip() if p.returncode == 0 else None
    return result


def transcribe_sample(audio, directory):
    # Imports must occur in the spawned child, never in the RQ parent.
    from asr_srt.config import JobConfig
    from asr_srt.workflow import LocalTranscriptionService
    from rq import get_current_job
    job = get_current_job()
    started = time.time()
    beats = []
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(1):
            beats.append(time.time())
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    events = []
    before = host_metrics()
    try:
        result = LocalTranscriptionService(progress=events.append).run(JobConfig(
            input_path=Path(audio), device="mps", cache_dir=Path(directory) / "cache",
            output_path=Path(directory) / (job.id + ".srt"), use_cache=False,
        ))
        return {
            "pid": os.getpid(), "started": started, "finished": time.time(),
            "device": result.transcript.metadata.device,
            "duration_ms": result.transcript.duration_ms,
            "text_characters": len(result.transcript.full_text),
            "cues": len(result.cues), "heartbeat_count": len(beats),
            "heartbeat_max_gap_seconds": max(
                (b - a for a, b in zip([started] + beats, beats + [time.time()])), default=0),
            "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2,
            "before": before, "after": host_metrics(),
            "phases": sorted({e.phase for e in events}),
        }
    finally:
        stop.set()
        thread.join(timeout=5)


def main():
    from redis import Redis
    from rq import Queue, SpawnWorker
    from rq.serializers import JSONSerializer
    import psutil
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--redis-url", default="redis://127.0.0.1:16379/0")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    redis = Redis.from_url(args.redis_url)
    queue = Queue("asr-smoke-" + uuid.uuid4().hex, connection=redis, serializer=JSONSerializer)
    jobs = [queue.enqueue("rq_smoke.transcribe_sample", str(args.audio.resolve()),
                          str(args.output_dir.resolve()), job_timeout=600, result_ttl=3600)
            for _ in range(2)]
    worker = SpawnWorker([queue], connection=redis, serializer=JSONSerializer,
                         job_monitoring_interval=5)
    worker.work(burst=True)
    results = []
    for job in jobs:
        job.refresh()
        if not job.is_finished:
            raise RuntimeError(f"Smoke job {job.id} failed: {job.exc_info}")
        result = job.return_value()
        result["child_exited"] = not psutil.pid_exists(result["pid"])
        assert result["child_exited"] and result["device"] == "mps"
        assert result["text_characters"] > 0 and result["heartbeat_count"] > 0
        assert result["heartbeat_max_gap_seconds"] < 90
        results.append(result)
    assert results[0]["finished"] <= results[1]["started"], "Jobs overlapped"
    report = {"host": subprocess.check_output(
        ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip(),
        "target_hardware_acceptance": False, "jobs": results}
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
