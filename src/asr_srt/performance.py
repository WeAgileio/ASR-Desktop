import json
import math
import platform
import resource
import sys
import time
from contextlib import contextmanager
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
METRICS_VERSION = 1


@dataclass(frozen=True)
class PerformanceSpan:
    name: str
    seconds: float

    def __post_init__(self):
        if not self.name or self.seconds < 0:
            raise ValueError("Performance spans require a name and non-negative duration")


@dataclass(frozen=True)
class ResourceSnapshot:
    peak_rss_mb: float
    memory_pressure: Optional[float] = None
    swap_used_mb: Optional[float] = None
    version: int = METRICS_VERSION


class StageRecorder:
    def __init__(self):
        self.spans: List[PerformanceSpan] = []

    @contextmanager
    def measure(self, name: str):
        started = time.monotonic()
        try:
            yield
        finally:
            self.record(name, time.monotonic() - started)

    def record(self, name: str, seconds: float) -> None:
        self.spans.append(PerformanceSpan(name, max(0.0, seconds)))


def resource_snapshot() -> ResourceSnapshot:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    peak = value / (1024 * 1024) if platform.system() == "Darwin" else value / 1024
    return ResourceSnapshot(round(peak, 3))


@dataclass(frozen=True)
class LongFormPerformanceKey:
    model_id: str
    model_revision: str
    runtime: str
    device: str
    duration_band: str
    planner_version: int
    tuning: str = "default"

    @property
    def identity(self):
        return "|".join(map(str, (self.model_id, self.model_revision, self.runtime,
                                  self.device, self.duration_band, self.planner_version,
                                  self.tuning)))


class LongFormPerformanceProfile:
    VERSION = 1
    MIN_SAMPLES = 2

    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
            return data.get("profiles", {}) if data.get("version") == self.VERSION else {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def record(self, key, *, rtf, peak_rss_mb, swap_grew=False, successful=True):
        if not successful or rtf <= 0 or peak_rss_mb < 0:
            return False
        profiles = self._load()
        values = profiles.setdefault(key.identity, [])
        values.append({"rtf": rtf, "peak_rss_mb": peak_rss_mb,
                       "swap_grew": bool(swap_grew)})
        profiles[key.identity] = values[-MAX_SAMPLES:]
        atomic_write_text(self.path, json.dumps({"version": self.VERSION, "profiles": profiles},
                                                sort_keys=True, indent=2) + "\n")
        return True

    def eligible_rtf(self, key, *, max_peak_rss_mb=float("inf")):
        values = self._load().get(key.identity, [])
        valid = [item for item in values if isinstance(item, dict)
                 and isinstance(item.get("rtf"), (int, float)) and item["rtf"] > 0
                 and isinstance(item.get("peak_rss_mb"), (int, float))
                 and item["peak_rss_mb"] <= max_peak_rss_mb and not item.get("swap_grew")]
        if len(valid) < self.MIN_SAMPLES:
            return None
        return median(item["rtf"] for item in valid)

    def choose_device(self, cpu_key, mps_key, *, max_peak_rss_mb=float("inf")):
        cpu = self.eligible_rtf(cpu_key, max_peak_rss_mb=max_peak_rss_mb)
        mps = self.eligible_rtf(mps_key, max_peak_rss_mb=max_peak_rss_mb)
        if cpu is None or mps is None:
            return None
        return "cpu" if cpu <= mps else "mps"


def duration_band(seconds):
    if seconds < 600:
        return "under-10m"
    if seconds < 3600:
        return "10m-60m"
    return "over-60m"


def tuning_eligible(*, baseline_rtf, candidate_rtf, peak_rss_mb, max_peak_rss_mb,
                    swap_grew=False, quality_ok=True, timestamps_ok=True,
                    minimum_improvement=0.10):
    reasons = []
    if candidate_rtf > baseline_rtf * (1 - minimum_improvement):
        reasons.append("insufficient RTF improvement")
    if peak_rss_mb > max_peak_rss_mb:
        reasons.append("peak memory guardrail exceeded")
    if swap_grew:
        reasons.append("swap increased")
    if not quality_ok:
        reasons.append("transcript quality regression")
    if not timestamps_ok:
        reasons.append("timestamp regression")
    return not reasons, tuple(reasons)


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

    def estimate_rtf(self, key: PerformanceKey) -> Optional[float]:
        values = self._load().get(key.identity, [])
        if len(values) < MIN_SAMPLES:
            return None
        estimate = median(values)
        return estimate if math.isfinite(estimate) and estimate > 0 else None

    def estimate_seconds(self, key: PerformanceKey, audio_seconds: float) -> Optional[float]:
        estimate = self.estimate_rtf(key)
        if estimate is None or not math.isfinite(audio_seconds) or audio_seconds <= 0:
            return None
        return estimate * audio_seconds

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


class EtaEstimator:
    """Estimate remaining wall time without coupling ETA to progress units."""

    def __init__(self, audio_seconds: float, historical_rtf: Optional[float] = None):
        self.audio_seconds = self._positive(audio_seconds)
        self.historical_rtf = self._positive(historical_rtf)
        self.effective_rtf = self.historical_rtf
        self._smoothed_eta: Optional[float] = None

    @staticmethod
    def _positive(value: Optional[float]) -> Optional[float]:
        if value is None or not isinstance(value, (int, float)):
            return None
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None

    @property
    def initial_eta_seconds(self) -> Optional[float]:
        if self.audio_seconds is None or self.historical_rtf is None:
            return None
        return self.audio_seconds * self.historical_rtf

    def recalibrate(self, committed_audio_seconds: float, processing_seconds: float) -> Optional[float]:
        committed = self._positive(committed_audio_seconds)
        processing = self._positive(processing_seconds)
        if self.audio_seconds is None or committed is None or processing is None:
            return self.effective_rtf
        observed = processing / committed
        confidence = min(1.0, committed / self.audio_seconds)
        if self.historical_rtf is None:
            self.effective_rtf = observed
        else:
            self.effective_rtf = self.historical_rtf * (1.0 - confidence) + observed * confidence
        self._smoothed_eta = None
        return self.effective_rtf

    def remaining_seconds(self, completed_audio_seconds: float, *, smooth: bool = True) -> Optional[float]:
        if self.audio_seconds is None or self.effective_rtf is None:
            return None
        if not isinstance(completed_audio_seconds, (int, float)) or not math.isfinite(completed_audio_seconds):
            return None
        remaining_audio = max(0.0, self.audio_seconds - max(0.0, float(completed_audio_seconds)))
        estimate = remaining_audio * self.effective_rtf
        if remaining_audio > 0:
            estimate = max(0.1, estimate)
        if not smooth or self._smoothed_eta is None:
            self._smoothed_eta = estimate
            return estimate
        lower = self._smoothed_eta * 0.75
        upper = self._smoothed_eta * 1.25
        self._smoothed_eta = min(upper, max(lower, estimate))
        return self._smoothed_eta
