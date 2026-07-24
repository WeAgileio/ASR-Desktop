import time
from contextlib import contextmanager
from typing import Callable, Optional

from ..domain import Transcript, TranscriptMetadata
from ..errors import DependencyError, MPSCompatibilityError
from ..device import looks_like_mps_error
from .base import ASRAdapter, AdapterProgress, AdapterRequest
from .local_models import resolve_model_reference
from .normalization import discover_revision, normalize_result
from .segment_progress import observe_funasr_segments


class FunAsrNanoAdapter(ASRAdapter):
    model_id = "FunAudioLLM/Fun-ASR-Nano-2512"
    model_revision = "master"
    progress_scope = "batch"

    def __init__(self, model_factory: Optional[Callable] = None):
        self.model_factory = model_factory

    def _create_model(self, device: str):
        model_reference = resolve_model_reference(self.model_id)
        vad_reference = resolve_model_reference("fsmn-vad")
        if self.model_factory:
            return self.model_factory(
                model=model_reference,
                vad_model=vad_reference,
                vad_kwargs={"max_single_segment_time": 30000},
                model_revision=self.model_revision,
                disable_update=True,
                disable_pbar=True,
                device=device,
            )
        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise DependencyError("FunASR is not installed. Run: pip install -e .") from exc
        return AutoModel(
            model=model_reference,
            vad_model=vad_reference,
            vad_kwargs={"max_single_segment_time": 30000},
            model_revision=self.model_revision,
            disable_update=True,
            disable_pbar=True,
            device=device,
        )

    def transcribe(self, request: AdapterRequest) -> Transcript:
        with self.open_session(request.device, request.stage_callback) as session:
            return session.transcribe(request)

    @contextmanager
    def open_session(self, device: str, stage_callback=None):
        load_started = time.monotonic()
        try:
            model = self._create_model(device)
            if stage_callback:
                stage_callback("model-load", time.monotonic() - load_started)
            yield _NanoSession(self, model)
        except Exception as exc:
            if device == "mps" and looks_like_mps_error(exc):
                raise MPSCompatibilityError(str(exc)) from exc
            raise


class _NanoSession:
    def __init__(self, adapter, model):
        self.adapter, self.model = adapter, model

    def transcribe(self, request: AdapterRequest) -> Transcript:
        started = time.monotonic()
        model = self.model
        try:
            inference_started = time.monotonic()
            with observe_funasr_segments(model, request.progress, epoch=request.progress_epoch):
                raw = model.generate(
                    input=str(request.audio_path), cache={}, batch_size=1,
                    language=request.language, hotwords=list(request.hotwords), timestamp=True,
                    disable_pbar=True,
                    progress_callback=(
                        (lambda current, total: request.progress(
                            AdapterProgress(current, total, "items", self.adapter.progress_scope)
                        )) if request.progress else None
                    ),
                )
            if request.stage_callback:
                request.stage_callback("asr-inference", time.monotonic() - inference_started)
        except Exception as exc:
            if request.device == "mps" and looks_like_mps_error(exc):
                raise MPSCompatibilityError(str(exc)) from exc
            raise
        normalization_started = time.monotonic()
        text, units = normalize_result(raw, request.duration_ms)
        if request.stage_callback:
            request.stage_callback("normalization", time.monotonic() - normalization_started)
        return Transcript(
            full_text=text,
            duration_ms=request.duration_ms,
            language=request.language,
            units=units,
            metadata=TranscriptMetadata(
                model_id=self.adapter.model_id,
                model_revision=discover_revision(model, self.adapter.model_revision),
                device=request.device,
                hotwords=request.hotwords,
                processing_seconds=round(time.monotonic() - started, 3),
                cache_key=request.cache_key,
            ),
        )
