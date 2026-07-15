import json
import platform
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional

from .files import atomic_write_text

PROFILE_VERSION = 1
MIN_AUDIO_SECONDS = 30.0
MIN_SAMPLES = 2
MAX_SAMPLES = 12


def runtime_identity() -> str:
    try:
        funasr_version = metadata.version("funasr")
    except metadata.PackageNotFoundError:
        funasr_version = "unknown"
    return f"python-{sys.version_info.major}.{sys.version_info.minor}|{platform.system()}-{platform.machine()}|funasr-{funasr_version}"


@dataclass(frozen=True)
class PerformanceKey:
    model_id: str
    model_revision: str
    device: str
    runtime: str

    @property
    def identity(self) -> str:
        return "|".join((self.model_id, self.model_revision, self.device, self.runtime))


class PerformanceProfile:
    """Failure-tolerant local history used only for approximate ASR ETA."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> Dict[str, List[float]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != PROFILE_VERSION or not isinstance(payload.get("profiles"), dict):
                return {}
            result: Dict[str, List[float]] = {}
            for key, values in payload["profiles"].items():
                if not isinstance(key, str) or not isinstance(values, list):
                    continue
                valid = [float(value) for value in values if isinstance(value, (int, float)) and 0 < value < 100]
                if valid:
                    result[key] = valid[-MAX_SAMPLES:]
            return result
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def estimate_seconds(self, key: PerformanceKey, audio_seconds: float) -> Optional[float]:
        values = self._load().get(key.identity, [])
        if len(values) < MIN_SAMPLES or audio_seconds <= 0:
            return None
        return median(values) * audio_seconds

    def record(
        self,
        key: PerformanceKey,
        audio_seconds: float,
        processing_seconds: float,
        *,
        successful: bool = True,
        cache_hit: bool = False,
        cancelled: bool = False,
    ) -> bool:
        if (
            not successful
            or cache_hit
            or cancelled
            or audio_seconds < MIN_AUDIO_SECONDS
            or processing_seconds <= 0
        ):
            return False
        profiles = self._load()
        samples = profiles.setdefault(key.identity, [])
        samples.append(processing_seconds / audio_seconds)
        profiles[key.identity] = samples[-MAX_SAMPLES:]
        payload = {"version": PROFILE_VERSION, "profiles": profiles}
        try:
            atomic_write_text(
                self.path,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                overwrite=True,
            )
        except OSError:
            return False
        return True

