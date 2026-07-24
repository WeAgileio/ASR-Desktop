"""Failure-tolerant, duration-weighted progress for FunASR VAD segments.

FunASR 1.3.x (verified with the installed 1.3.14 runtime) calls
``self.inference`` first with ``model=self.vad_model`` and then once per
dynamic ASR batch with ``model=self.model``.  The bridge below observes those
pass-through boundaries and disables itself if that structural contract is
absent or changes.
"""

from contextlib import contextmanager
import math
from dataclasses import dataclass
from typing import Callable, Iterator, Optional, Tuple

from .base import AdapterProgress


@dataclass
class SegmentWorkLedger:
    """Track sorted VAD segment durations without affecting inference."""

    durations_ms: Tuple[float, ...]
    epoch: int = 0
    completed_count: int = 0
    completed_ms: float = 0.0
    enabled: bool = True

    @classmethod
    def from_vad_result(cls, result, *, epoch: int = 0) -> Optional["SegmentWorkLedger"]:
        try:
            if not isinstance(result, (list, tuple)) or len(result) != 1:
                return None
            segments = result[0].get("value")
            if not isinstance(segments, (list, tuple)) or not segments:
                return None
            durations = []
            for segment in segments:
                if not isinstance(segment, (list, tuple)) or len(segment) < 2:
                    return None
                start, end = float(segment[0]), float(segment[1])
                duration = end - start
                if not all(math.isfinite(value) for value in (start, end, duration)):
                    return None
                if start < 0 or duration <= 0:
                    return None
                durations.append(duration)
            return cls(tuple(sorted(durations)), epoch=epoch)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None

    @property
    def total_ms(self) -> float:
        return sum(self.durations_ms)

    def complete(self, count: int) -> Optional[AdapterProgress]:
        if not self.enabled:
            return None
        if not isinstance(count, int) or count <= 0:
            self.enabled = False
            return None
        end = self.completed_count + count
        if end > len(self.durations_ms):
            self.enabled = False
            return None
        increment = sum(self.durations_ms[self.completed_count:end])
        current = self.completed_ms + increment
        total = self.total_ms
        if not math.isfinite(current) or total <= 0 or current < self.completed_ms or current > total:
            self.enabled = False
            return None
        self.completed_count = end
        self.completed_ms = current
        # ASR batches may be done while normalization/merge can still fail.
        visible = min(current, total * 0.95)
        return AdapterProgress(
            visible, total, "milliseconds", "whole-input", "estimated", self.epoch
        )


def result_count(result) -> Optional[int]:
    """Return the number of successful inference results for a supported call shape."""
    values = result[0] if isinstance(result, tuple) and result else result
    if not isinstance(values, list) or not values:
        return None
    return len(values)


def supports_segment_observation(model) -> bool:
    """Probe the call topology instead of trusting a package version alone."""
    return (
        callable(getattr(model, "inference", None))
        and callable(getattr(model, "inference_with_vad", None))
        and getattr(model, "vad_model", None) is not None
        and getattr(model, "model", None) is not None
    )


@contextmanager
def observe_funasr_segments(
    model,
    callback: Optional[Callable[[AdapterProgress], None]],
    *,
    epoch: int = 0,
) -> Iterator[bool]:
    """Temporarily observe VAD and main-ASR inference calls without changing them."""
    if callback is None or not supports_segment_observation(model):
        yield False
        return

    original = model.inference
    had_instance_value = "inference" in getattr(model, "__dict__", {})
    instance_value = getattr(model, "__dict__", {}).get("inference")
    ledger: Optional[SegmentWorkLedger] = None
    active = True

    def observed(*args, **kwargs):
        nonlocal ledger, active
        result = original(*args, **kwargs)
        if not active:
            return result
        target = kwargs.get("model")
        if target is model.vad_model:
            ledger = SegmentWorkLedger.from_vad_result(result, epoch=epoch)
            active = ledger is not None
        elif target is model.model:
            count = result_count(result)
            measurement = ledger.complete(count) if ledger is not None and count else None
            if measurement is None:
                active = False
            else:
                try:
                    callback(measurement)
                except Exception:
                    active = False
        return result

    model.inference = observed
    try:
        yield True
    finally:
        if had_instance_value:
            model.inference = instance_value
        else:
            try:
                delattr(model, "inference")
            except AttributeError:
                model.inference = original
