"""Entry point for the bundled Python helper. Never locates a system Python."""

import argparse
from contextlib import redirect_stdout
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import resource
import socket
import subprocess
import sys
import time
import wave


def bundle_root():
    # Frozen execution derives paths from its executable, not a caller's PATH.
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def diagnose():
    root = bundle_root()
    report = {
        "schema_version": 1,
        "frozen": bool(getattr(sys, "frozen", False)),
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "bundle_path": str(root) if root else None,
        "packages": {}, "media": {}, "errors": [],
    }
    try:
        with redirect_stdout(sys.stderr):
            import torch
            import torchaudio
            from funasr import AutoModel
            from opencc import OpenCC
            import transformers
            from faster_whisper import WhisperModel
            from transformers import WhisperProcessor, WhisperForConditionalGeneration
            from transformers.models.qwen3.configuration_qwen3 import Qwen3Config
            from transformers.models.qwen3.modeling_qwen3 import Qwen3ForCausalLM
            from funasr.register import tables
        for name in ("funasr", "torch", "torchaudio", "transformers", "modelscope", "tiktoken", "faster-whisper", "ctranslate2", "av", "onnxruntime"):
            report["packages"][name] = metadata.version(name)
        report["mps_available"] = torch.backends.mps.is_available()
        report["auto_model_importable"] = callable(AutoModel)
        report["whisper_engines_importable"] = all(callable(value) for value in (WhisperModel, WhisperProcessor, WhisperForConditionalGeneration))
        report["qwen3_importable"] = callable(Qwen3Config) and callable(Qwen3ForCausalLM)
        report["traditional_conversion"] = OpenCC("s2twp").convert("字幕转换")
        report["registered_models"] = sorted(tables.model_classes)
    except Exception as error:
        report["errors"].append({"code": "runtime_import_failed", "message": str(error)})
    if root:
        for name in ("ffmpeg", "ffprobe"):
            executable = root / "Contents/Resources/media" / name
            try:
                completed = subprocess.run([str(executable), "-version"], capture_output=True,
                                           text=True, check=True, timeout=15)
                report["media"][name] = completed.stdout.splitlines()[0]
            except (OSError, subprocess.SubprocessError) as error:
                report["errors"].append({"code": "media_unavailable", "component": name, "message": str(error)})
    else:
        report["errors"].append({"code": "not_bundled", "message": "Run the helper inside the installed App."})
    report["ready"] = not report["errors"] and report["architecture"] == "arm64"
    return report


def smoke(config):
    """Maintainer validation of real models through the packaged adapters."""
    from asr_srt.adapters import AdapterRequest
    from asr_desktop.offline import disable_network, local_adapter

    disable_network()
    roots = config["component_paths"]
    catalog = json.loads(Path(__file__).with_name("data").joinpath("models.json").read_text())
    from asr_srt.registry import registration, execution
    definition = config.get("model_definition") or registration(config["model"], catalog)
    revisions = {key: catalog["components"][key]["revision"] for key in roots}
    adapter = local_adapter(config["model"], roots, revisions, definition=definition)
    audio = Path(config["audio"])
    with wave.open(str(audio), "rb") as stream:
        duration_ms = round(stream.getnframes() / stream.getframerate() * 1000)
    spans = []
    started = time.monotonic()
    with redirect_stdout(sys.stderr):
        transcript = adapter.transcribe(AdapterRequest(
            audio_path=audio, duration_ms=duration_ms, language="中文",
            hotwords=(), device=config["device"], cache_key=config["snapshot_id"],
            stage_callback=lambda name, seconds: spans.append({"name": name, "seconds": seconds})))
    return {"schema_version": 1, "model": config["model"], "device": config["device"],
            "snapshot_id": config["snapshot_id"], "revision": config["revision"],
            "duration_ms": duration_ms, "elapsed_seconds": time.monotonic() - started,
            "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024),
            "network_blocked": True, "spans": spans, "transcript": json.loads(transcript.to_json())}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="asr-desktop-runtime")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--smoke-config", type=Path)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--worker-config", type=Path)
    args = parser.parse_args(argv)
    root = bundle_root()
    if root:
        os.environ["PATH"] = str(root / "Contents/Resources/media") + ":/usr/bin:/bin"
    if args.serve:
        from asr_desktop.coordinator import serve
        serve()
        return 0
    if args.worker_config:
        from asr_desktop.worker import run
        return run(args.worker_config)
    if args.smoke_config:
        with redirect_stdout(sys.stderr):
            result = smoke(json.loads(args.smoke_config.read_text()))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if not args.diagnose:
        parser.error("an operation is required")
    report = diagnose()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
