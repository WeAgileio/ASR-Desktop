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
    from ..registry import supported_models as models
    return models()


def create_adapter(model: str, model_factory: Optional[Callable] = None, definition=None) -> ASRAdapter:
    from ..registry import registration, execution
    definition = definition or registration(model)
    engine = execution(definition)["engine"]
    if engine == "funasr-nano":
        from .nano import FunAsrNanoAdapter
        return FunAsrNanoAdapter(model_factory=model_factory)
    if engine == "funasr-paraformer":
        from .paraformer import ParaformerAdapter
        return ParaformerAdapter(model_factory=model_factory)
    if engine in ("faster-whisper", "transformers-whisper"):
        # Standalone CLI shares the desktop's explicitly prepared model store.
        import os
        from asr_desktop.models import ModelStore
        from asr_desktop.offline import local_adapter
        root = Path(os.environ.get("ASR_DESKTOP_DATA_DIR", str(Path.home() / "Library/Application Support/ASR Desktop")))
        store = ModelStore(root / "models")
        pinned = store.definition(model)
        paths = store.local_paths(pinned["snapshot_id"])
        revisions = {key: value["revision"] for key, value in pinned["component_definitions"].items()}
        return local_adapter(model, paths, revisions, model_factory=model_factory, definition=pinned)
    raise ValidationError(
        f"Unsupported model '{model}'. Choose: {', '.join(supported_models())}"
    )
