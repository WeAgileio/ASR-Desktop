from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable, Optional, Tuple

from ..domain import Transcript
from ..errors import ValidationError


@dataclass(frozen=True)
class AdapterProgress:
    current: float
    total: float
    unit: str = "items"
    scope: str = "batch"
    kind: str = "actual"
    epoch: int = 0

    def __post_init__(self) -> None:
        if self.kind not in ("actual", "estimated"):
            raise ValueError(f"Unsupported adapter progress kind: {self.kind}")
        if self.scope not in ("batch", "global", "whole-input"):
            raise ValueError(f"Unsupported adapter progress scope: {self.scope}")
        if not self.unit:
            raise ValueError("Adapter progress unit cannot be empty")
        if not math.isfinite(self.current) or not math.isfinite(self.total):
            raise ValueError("Adapter progress values must be finite")
        if self.total <= 0 or self.current < 0 or self.current > self.total:
            raise ValueError("Adapter progress requires 0 <= current <= positive total")
        if not isinstance(self.epoch, int) or self.epoch < 0:
            raise ValueError("Adapter progress epoch must be a non-negative integer")


@dataclass(frozen=True)
class AdapterRequest:
    audio_path: Path
    duration_ms: int
    language: str
    hotwords: Tuple[str, ...]
    device: str
    cache_key: str = ""
    progress: Optional[Callable[[AdapterProgress], None]] = None
    progress_epoch: int = 0
    stage_callback: Optional[Callable[[str, float], None]] = None


class ASRAdapter(ABC):
    model_id: str
    progress_scope: str = "none"

    @abstractmethod
    def transcribe(self, request: AdapterRequest) -> Transcript:
        raise NotImplementedError

    @contextmanager
    def open_session(self, device: str, stage_callback=None):
        yield _SingleCallSession(self)


class _SingleCallSession:
    def __init__(self, adapter):
        self.adapter = adapter

    def transcribe(self, request: AdapterRequest) -> Transcript:
        return self.adapter.transcribe(request)


def supported_models() -> Tuple[str, ...]:
    return ("fun-asr-nano", "paraformer")


def create_adapter(model: str, model_factory: Optional[Callable] = None) -> ASRAdapter:
    if model == "fun-asr-nano":
        from .nano import FunAsrNanoAdapter
        return FunAsrNanoAdapter(model_factory=model_factory)
    if model == "paraformer":
        from .paraformer import ParaformerAdapter
        return ParaformerAdapter(model_factory=model_factory)
    raise ValidationError(
        f"Unsupported model '{model}'. Choose: {', '.join(supported_models())}"
    )
