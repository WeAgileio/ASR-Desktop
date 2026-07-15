from abc import ABC, abstractmethod
from dataclasses import dataclass
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


@dataclass(frozen=True)
class AdapterRequest:
    audio_path: Path
    duration_ms: int
    language: str
    hotwords: Tuple[str, ...]
    device: str
    cache_key: str = ""
    progress: Optional[Callable[[AdapterProgress], None]] = None


class ASRAdapter(ABC):
    model_id: str
    progress_scope: str = "none"

    @abstractmethod
    def transcribe(self, request: AdapterRequest) -> Transcript:
        raise NotImplementedError


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
