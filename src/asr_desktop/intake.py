"""Read-only batch preview and immutable source/output planning."""

import hashlib
import json
import os
from pathlib import Path
import subprocess

from .database import DEFAULTS, StateError
from .models import digest_file


def settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise StateError("invalid_settings", "Unknown transcription setting")
    result = {**DEFAULTS, **value}
    if result["model"] not in ("fun-asr-nano", "paraformer") or result["device"] not in ("auto", "cpu", "gpu", "mps"):
        raise StateError("invalid_settings", "Unknown model or device")
    if (not isinstance(result["formats"], list) or not result["formats"] or
        any(f not in ("txt", "srt", "json") for f in result["formats"]) or len(set(result["formats"])) != len(result["formats"])):
        raise StateError("invalid_settings", "Choose unique txt/srt/json formats")
    if result["script"] not in ("traditional", "simplified", "original"):
        raise StateError("invalid_settings", "Unknown output script")
    if type(result["overwrite"]) is not bool or type(result["max_chars"]) is not int or not 1 <= result["max_chars"] <= 100:
        raise StateError("invalid_settings", "Invalid overwrite or subtitle width")
    if type(result["max_duration_ms"]) is not int or not 250 <= result["max_duration_ms"] <= 30000:
        raise StateError("invalid_settings", "Invalid subtitle duration")
    if (not isinstance(result["language"], str) or not result["language"] or len(result["language"]) > 64 or
        not isinstance(result["hotwords"], list) or any(not isinstance(w, str) or len(w) > 200 for w in result["hotwords"])):
        raise StateError("invalid_settings", "Invalid language or hotwords")
    return result


def fingerprint(path):
    before = path.stat()
    digest = digest_file(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise StateError("source_changed", "Source changed while reading")
    return {"sha256": digest, "size": after.st_size, "mtime_ns": after.st_mtime_ns}


def source_matches(path, expected):
    current = fingerprint(Path(path))
    return current["sha256"] == expected["sha256"] and current["size"] == expected["size"]


def probe(path, executable):
    completed = subprocess.run([str(executable), "-v", "error", "-show_entries", "format=duration:stream=codec_type,duration",
                                "-of", "json", str(path)], capture_output=True, text=True, timeout=30)
    if completed.returncode:
        raise StateError("invalid_media", "FFprobe cannot decode this input")
    value = json.loads(completed.stdout)
    audio = [stream for stream in value.get("streams", []) if stream.get("codec_type") == "audio"]
    if not audio:
        raise StateError("unsupported_media", "This file has no audio stream")
    try:
        duration = float(value.get("format", {}).get("duration", audio[0].get("duration", 0)))
        if not 0 < duration < float("inf"):
            raise ValueError()
    except (TypeError, ValueError):
        raise StateError("invalid_media", "A finite positive media duration is required")
    return round(duration * 1000)


def preview(paths, output_dir, options, ffprobe, recursive=False):
    options = settings(options)
    if not isinstance(paths, list) or not paths or any(not isinstance(p, str) for p in paths):
        raise StateError("invalid_arguments", "Provide at least one source path")
    if not isinstance(output_dir, str) or not output_dir:
        raise StateError("invalid_arguments", "Choose an output directory")
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and not output.is_dir():
        raise StateError("output_unavailable", "Output must be a directory")
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    if not os.access(ancestor, os.W_OK | os.X_OK):
        raise StateError("output_unavailable", "Output directory is not writable")
    entries, seen = [], set()
    def add(path, root):
        if path.is_symlink():
            entries.append({"source": str(path), "status": "symlink_excluded"})
            return
        resolved = path.resolve()
        if str(resolved) in seen:
            entries.append({"source": str(resolved), "status": "duplicate"})
            return
        seen.add(str(resolved))
        if not resolved.is_file():
            entries.append({"source": str(resolved), "status": "invalid", "error": "Not a regular file"})
            return
        try:
            duration = probe(resolved, ffprobe)
            identity = hashlib.sha256(str(resolved).encode()).hexdigest()[:12]
            # Stable suffix across all roots and batches prevents same-stem collisions.
            relative = path.relative_to(root).parent if root else Path()
            stem = resolved.stem + "-" + identity
            outputs = {fmt: str(output / relative / (stem + "." + fmt)) for fmt in options["formats"]}
            source_info = fingerprint(resolved)
            if any(Path(target).resolve() == resolved for target in outputs.values()):
                raise StateError("source_output_overlap", "Output cannot replace its source")
            entries.append({"source": str(resolved), "status": "valid", "duration_ms": duration,
                            "fingerprint": source_info, "outputs": outputs})
        except (StateError, OSError, ValueError, subprocess.SubprocessError) as error:
            entries.append({"source": str(resolved), "status": "invalid", "error": str(error),
                            "error_code": getattr(error, "code", "input_unavailable")})
    for source in paths:
        path = Path(source).expanduser().absolute()
        if path.is_symlink():
            add(path, None)
        elif path.is_dir():
            # os.walk does not follow directory symlinks; still report them explicitly.
            for directory, subdirs, files in os.walk(path, followlinks=False):
                for name in sorted(subdirs):
                    candidate = Path(directory) / name
                    if candidate.is_symlink():
                        add(candidate, path)
                subdirs[:] = sorted(d for d in subdirs if not (Path(directory) / d).is_symlink()) if recursive else []
                for name in sorted(files):
                    add(Path(directory) / name, path)
        else:
            add(path, None)
    return {"entries": entries, "valid_count": sum(e["status"] == "valid" for e in entries),
            "output_dir": str(output), "settings": options}
