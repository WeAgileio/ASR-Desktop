#!/usr/bin/env python3
"""Run an explicit local model smoke test and print JSON metrics."""

import argparse
import json
import os
import platform
import resource
import time
import wave
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--model", choices=("fun-asr-nano", "paraformer"), required=True)
    parser.add_argument("--device", choices=("mps", "cpu"), required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".model-cache"))
    args = parser.parse_args()
    cache = args.cache_dir.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MODELSCOPE_CACHE", str(cache))
    os.environ.setdefault("HF_HOME", str(cache / "huggingface"))

    from asr_srt.adapters import AdapterRequest, create_adapter

    with wave.open(str(args.audio), "rb") as stream:
        duration_ms = round(stream.getnframes() / stream.getframerate() * 1000)
    started = time.monotonic()
    result = create_adapter(args.model).transcribe(AdapterRequest(
        audio_path=args.audio,
        duration_ms=duration_ms,
        language="中文",
        hotwords=("FunASR",),
        device=args.device,
        cache_key="smoke-test",
    ))
    elapsed = time.monotonic() - started
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    print(json.dumps({
        "macos": platform.mac_ver()[0],
        "machine": platform.machine(),
        "model": args.model,
        "model_id": result.metadata.model_id,
        "model_revision": result.metadata.model_revision,
        "device": result.metadata.device,
        "duration_ms": duration_ms,
        "processing_seconds_including_load": round(elapsed, 3),
        "real_time_factor_including_load": round(elapsed / (duration_ms / 1000), 3),
        "peak_rss_mb": round(peak_mb, 1),
        "text": result.full_text,
        "timestamp_units": len(result.units),
        "first_timestamp": result.units[0].__dict__ if result.units else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
