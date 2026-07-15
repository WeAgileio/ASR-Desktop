import time
from typing import Callable, Optional

from ..domain import Transcript, TranscriptMetadata
from ..errors import DependencyError, MPSCompatibilityError
from ..device import looks_like_mps_error
from .base import ASRAdapter, AdapterProgress, AdapterRequest
from .local_models import resolve_model_reference
from .normalization import discover_revision, normalize_result


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
        started = time.monotonic()
        try:
            model = self._create_model(request.device)
            raw = model.generate(
                input=str(request.audio_path), cache={}, batch_size=1,
                language=request.language, hotwords=list(request.hotwords), timestamp=True,
                disable_pbar=True,
                progress_callback=(
                    (lambda current, total: request.progress(
                        AdapterProgress(current, total, "items", self.progress_scope)
                    )) if request.progress else None
                ),
            )
        except Exception as exc:
            if request.device == "mps" and looks_like_mps_error(exc):
                raise MPSCompatibilityError(str(exc)) from exc
            raise
        text, units = normalize_result(raw, request.duration_ms)
        return Transcript(
            full_text=text,
            duration_ms=request.duration_ms,
            language=request.language,
            units=units,
            metadata=TranscriptMetadata(
                model_id=self.model_id,
                model_revision=discover_revision(model, self.model_revision),
                device=request.device,
                hotwords=request.hotwords,
                processing_seconds=round(time.monotonic() - started, 3),
                cache_key=request.cache_key,
            ),
        )
