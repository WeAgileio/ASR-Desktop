import json
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from .errors import DependencyError, MediaError, ValidationError


@dataclass(frozen=True)
class MediaInfo:
    duration_ms: int
    audio_codec: str


def _parse_clock(value: str) -> Optional[float]:
    try:
        hours, minutes, seconds = value.split(":", 2)
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


def parse_ffmpeg_progress(lines: Iterable[str]) -> Iterator[float]:
    """Return completed media-time snapshots from FFmpeg's progress protocol."""
    current = {}
    for raw in lines:
        line = str(raw).strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        current[key] = value
        if key != "progress":
            continue
        seconds: Optional[float] = None
        # Despite its historical name, out_time_ms is expressed in microseconds.
        for candidate in ("out_time_us", "out_time_ms"):
            if candidate in current:
                try:
                    seconds = float(current[candidate]) / 1_000_000
                except (TypeError, ValueError):
                    pass
                break
        if seconds is None and "out_time" in current:
            seconds = _parse_clock(current["out_time"])
        if seconds is not None and seconds >= 0:
            yield seconds
        current = {}


def _report_media_times(
    lines: Iterable[str],
    duration_ms: Optional[int],
    progress: Optional[Callable[[float, float], None]],
) -> None:
    if not progress or not duration_ms or duration_ms <= 0:
        return
    total = duration_ms / 1000
    for seconds in parse_ffmpeg_progress(lines):
        # 100% is reserved for successful process exit and output validation.
        progress(min(max(seconds, 0.0), total * 0.999999), total)


def validate_source(path: Path) -> Path:
    path = Path(path)
    if not path.exists():
        raise ValidationError(f"Input does not exist: {path}")
    if not path.is_file():
        raise ValidationError(f"Input is not a file: {path}")
    if not os.access(str(path), os.R_OK):
        raise ValidationError(f"Input is not readable: {path}")
    return path


def require_binary(name: str) -> str:
    location = shutil.which(name)
    if not location:
        raise DependencyError(
            f"{name} is required. Install FFmpeg on macOS with: brew install ffmpeg"
        )
    return location


def probe_media(
    path: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> MediaInfo:
    path = validate_source(path)
    ffprobe = require_binary("ffprobe")
    command = [
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=codec_name:format=duration", "-of", "json", str(path),
    ]
    try:
        completed = runner(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MediaError(f"Unable to run ffprobe: {exc}") from exc
    if completed.returncode != 0:
        raise MediaError(f"ffprobe failed: {completed.stderr.strip() or 'unknown error'}")
    try:
        data = json.loads(completed.stdout)
        streams = data.get("streams") or []
        if not streams:
            raise MediaError("Input has no decodable audio stream")
        try:
            duration = float((data.get("format") or {}).get("duration", 0))
        except (ValueError, TypeError):
            duration = 0
        duration = max(0.0, duration)
        codec = str(streams[0].get("codec_name") or "unknown")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MediaError(f"Invalid ffprobe output: {exc}") from exc
    return MediaInfo(duration_ms=round(duration * 1000), audio_codec=codec)


def probe_wav_duration(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
    except (OSError, wave.Error) as exc:
        raise MediaError(f"Unable to determine extracted audio duration: {exc}") from exc
    if frames <= 0 or rate <= 0:
        raise MediaError("Extracted audio duration is unavailable or zero")
    return round(frames / rate * 1000)


def extract_audio(
    source: Path,
    destination: Path,
    runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    *,
    duration_ms: Optional[int] = None,
    progress: Optional[Callable[[float, float], None]] = None,
) -> Path:
    source = validate_source(source)
    ffmpeg = require_binary("ffmpeg")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=".wav", dir=str(destination.parent)
    )
    os.close(fd)
    temp_path = Path(temporary)
    try:
        command = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-nostats",
            "-progress", "pipe:1",
            "-i", str(source), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(temp_path),
        ]
        try:
            if runner is not None:
                completed = runner(command, capture_output=True, text=True, check=False)
                _report_media_times(completed.stdout.splitlines(), duration_ms, progress)
                returncode = completed.returncode
                stderr = completed.stderr
            else:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                _report_media_times(process.stdout or (), duration_ms, progress)
                if process.stdout:
                    process.stdout.close()
                stderr = (process.stderr.read() if process.stderr else "")
                if process.stderr:
                    process.stderr.close()
                returncode = process.wait()
        except OSError as exc:
            raise MediaError(f"Unable to run FFmpeg: {exc}") from exc
        if returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
            raise MediaError(f"FFmpeg extraction failed: {stderr.strip() or 'unknown error'}")
        os.replace(str(temp_path), str(destination))
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
    return destination


def extract_audio_chunk(
    source_wav: Path,
    destination: Path,
    start_ms: int,
    end_ms: int,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    source_wav = validate_source(source_wav)
    if start_ms < 0 or end_ms <= start_ms:
        raise ValidationError("Audio chunk boundaries are invalid")
    ffmpeg = require_binary("ffmpeg")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-ss", f"{start_ms / 1000:.3f}", "-t", f"{(end_ms-start_ms) / 1000:.3f}",
               "-i", str(source_wav), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
               str(destination)]
    try:
        completed = runner(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MediaError(f"Unable to extract audio chunk: {exc}") from exc
    if completed.returncode != 0 or not destination.exists() or destination.stat().st_size == 0:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        raise MediaError(f"Audio chunk extraction failed: {completed.stderr.strip() or 'unknown error'}")
    return destination


def detect_silence(
    source_wav: Path,
    duration_ms: int,
    minimum_silence_ms: int,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
):
    from .longform import parse_silence_intervals
    ffmpeg = require_binary("ffmpeg")
    command = [ffmpeg, "-nostdin", "-hide_banner", "-i", str(validate_source(source_wav)),
               "-af", f"silencedetect=noise=-35dB:d={minimum_silence_ms / 1000:.3f}",
               "-f", "null", "-"]
    completed = runner(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise MediaError(f"Silence detection failed: {completed.stderr.strip() or 'unknown error'}")
    return parse_silence_intervals(completed.stderr.splitlines(), duration_ms)
