import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .adapters import AdapterRequest, create_adapter
from .adapters.base import AdapterProgress
from .cache import TranscriptCache, cache_identity, content_fingerprint
from .config import JobConfig
from .device import DeviceDecision, resolve_device
from .domain import SubtitleCue, Transcript
from .errors import JobError, MPSCompatibilityError
from .media import extract_audio, probe_media, probe_wav_duration, validate_source
from .performance import PerformanceKey, PerformanceProfile, runtime_identity
from .progress import ProgressCallback, ProgressEvent
from .srt import write_srt
from .subtitle import convert_traditional, segment_transcript


@dataclass(frozen=True)
class JobResult:
    output_path: Path
    transcript_path: Path
    transcript: Transcript
    cues: Tuple[SubtitleCue, ...]
    cache_hit: bool


class _PhaseEmitter:
    def __init__(self, callback: ProgressCallback):
        self.callback = callback
        self.started: Dict[str, float] = {}
        self.last: Dict[str, ProgressEvent] = {}

    def start(
        self,
        phase: str,
        message: str,
        *,
        kind: str = "indeterminate",
        current: Optional[float] = None,
        total: Optional[float] = None,
        unit: Optional[str] = None,
        eta: Optional[float] = None,
    ) -> None:
        self.started[phase] = time.monotonic()
        self._send(phase, message, "running", kind, current, total, unit, eta)

    def update(
        self,
        phase: str,
        message: str,
        *,
        kind: str,
        current: float,
        total: float,
        unit: str,
        eta: Optional[float] = None,
    ) -> None:
        previous = self.last.get(phase)
        if previous and previous.current is not None:
            current = max(current, previous.current)
        current = min(current, total * 0.999999)
        self._send(phase, message, "running", kind, current, total, unit, eta)

    def complete(self, phase: str, message: str) -> None:
        previous = self.last.get(phase)
        if previous and previous.progress_kind != "indeterminate" and previous.total is not None:
            self._send(
                phase, message, "completed", previous.progress_kind,
                previous.total, previous.total, previous.unit, 0.0,
            )
        else:
            self._send(phase, message, "completed", "indeterminate", None, None, None, None)

    def skip(self, phase: str, message: str) -> None:
        self.started.setdefault(phase, time.monotonic())
        self._send(phase, message, "skipped", "indeterminate", None, None, None, None)

    def fail(self, phase: str, message: str) -> None:
        previous = self.last.get(phase)
        if previous and previous.terminal:
            return
        self.started.setdefault(phase, time.monotonic())
        self._send(phase, message, "failed", "indeterminate", None, None, None, None)

    def _send(
        self,
        phase: str,
        message: str,
        status: str,
        kind: str,
        current: Optional[float],
        total: Optional[float],
        unit: Optional[str],
        eta: Optional[float],
    ) -> None:
        elapsed = max(0.0, time.monotonic() - self.started.get(phase, time.monotonic()))
        event = ProgressEvent(
            phase=phase,
            message=message,
            status=status,
            progress_kind=kind,
            current=current,
            total=total,
            unit=unit,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
        )
        self.last[phase] = event
        self.callback(event)


class LocalTranscriptionService:
    def __init__(
        self,
        adapter_factory: Callable = create_adapter,
        progress: Optional[ProgressCallback] = None,
        device_resolver: Callable = resolve_device,
    ):
        self.adapter_factory = adapter_factory
        self.progress = progress or (lambda event: None)
        self.device_resolver = device_resolver

    def run(self, config: JobConfig) -> JobResult:
        events = _PhaseEmitter(self.progress)
        phase = "validation"
        try:
            events.start(phase, "Validating input and dependencies")
            source = validate_source(config.input_path)
            media = probe_media(source)
            decision = self.device_resolver(config.device)
            fingerprint = content_fingerprint(source)
            adapter = self.adapter_factory(config.model)
            selected_revision = str(getattr(adapter, "model_revision", "master"))
            key = cache_identity(
                fingerprint, config.model, selected_revision, config.language, config.hotwords
            )
            cache = TranscriptCache(config.cache_dir)
            paths = cache.paths(key)
            transcript = cache.load(key) if config.use_cache else None
            cache_hit = transcript is not None
            events.complete(phase, "Input and dependencies validated")

            if transcript is None:
                phase = "audio-extraction"
                events.start(phase, "Extracting mono 16 kHz audio")

                def media_progress(current: float, total: float) -> None:
                    events.update(
                        phase,
                        "Extracting mono 16 kHz audio",
                        kind="actual",
                        current=current,
                        total=total,
                        unit="seconds",
                        eta=max(0.0, total - current),
                    )

                audio_path = extract_audio(
                    source,
                    paths.audio,
                    duration_ms=media.duration_ms,
                    progress=media_progress,
                )
                events.complete(phase, "Audio extraction completed")
                duration_ms = media.duration_ms or probe_wav_duration(audio_path)

                phase = "model-preparation"
                events.start(phase, f"Preparing {config.model} on {decision.resolved}")
                events.complete(phase, f"Selected {config.model} on {decision.resolved}")

                phase = "transcription"
                profile = PerformanceProfile(config.cache_dir / "performance.json")
                estimate_key = PerformanceKey(
                    str(getattr(adapter, "model_id", config.model)),
                    selected_revision,
                    decision.resolved,
                    runtime_identity(),
                )
                estimated_seconds = profile.estimate_seconds(
                    estimate_key, duration_ms / 1000
                )
                if estimated_seconds:
                    events.start(
                        phase,
                        f"Transcribing on {decision.resolved} (estimated)",
                        kind="estimated",
                        current=0.0,
                        total=estimated_seconds,
                        unit="seconds",
                        eta=estimated_seconds,
                    )
                else:
                    events.start(phase, f"Transcribing on {decision.resolved}")

                asr_started = time.monotonic()
                transcript = self._transcribe(
                    config, audio_path, duration_ms, key, decision, adapter, events
                )
                processing_seconds = time.monotonic() - asr_started
                cache.save(key, transcript)
                record_key = PerformanceKey(
                    transcript.metadata.model_id,
                    transcript.metadata.model_revision,
                    transcript.metadata.device,
                    runtime_identity(),
                )
                profile.record(
                    record_key,
                    duration_ms / 1000,
                    processing_seconds,
                    successful=True,
                )
                events.complete(phase, "Transcription completed")
            else:
                events.skip("audio-extraction", "Skipped: compatible transcript cache hit")
                events.skip("model-preparation", "Skipped: compatible transcript cache hit")
                events.skip("transcription", "Skipped: using compatible cached transcript")

            phase = "subtitle-generation"
            events.start(phase, "Generating subtitle cues")
            cues = segment_transcript(transcript, config.subtitle)
            if config.traditional:
                cues = convert_traditional(cues)
            events.complete(phase, "Subtitle cues generated")

            phase = "output-writing"
            events.start(phase, f"Writing {config.resolved_output_path}")
            output = write_srt(config.resolved_output_path, cues, overwrite=config.overwrite)
            events.complete(phase, f"Generated {output}")
            return JobResult(output, paths.transcript, transcript, cues, cache_hit)
        except Exception as exc:
            events.fail(phase, str(exc))
            if isinstance(exc, JobError):
                raise
            raise JobError(phase, str(exc)) from exc

    def _transcribe(
        self,
        config: JobConfig,
        audio_path: Path,
        duration_ms: int,
        key: str,
        decision: DeviceDecision,
        adapter,
        events: _PhaseEmitter,
    ) -> Transcript:
        def adapter_progress(value: AdapterProgress) -> None:
            if getattr(adapter, "progress_scope", "none") != "global" or value.scope != "global":
                return
            events.update(
                "transcription",
                f"Transcribing on {decision.resolved}",
                kind="actual",
                current=value.current,
                total=value.total,
                unit=value.unit,
            )

        request = AdapterRequest(
            audio_path,
            duration_ms,
            config.language,
            config.hotwords,
            decision.resolved,
            key,
            adapter_progress,
        )
        try:
            return adapter.transcribe(request)
        except MPSCompatibilityError:
            if not decision.fallback_allowed:
                raise
            events.start("transcription", "MPS failed; reloading model on CPU")
            cpu_request = replace(request, device="cpu")
            return self.adapter_factory(config.model).transcribe(cpu_request)


__all__ = ["JobResult", "LocalTranscriptionService", "ProgressEvent"]
