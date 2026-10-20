import math
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .adapters import AdapterRequest, create_adapter
from .adapters.base import AdapterProgress
from .cache import PREPROCESSING_VERSION, TranscriptCache, cache_identity, content_fingerprint
from .config import JobConfig
from .device import DeviceDecision, resolve_device
from .domain import SubtitleCue, Transcript
from .errors import JobError, MPSCompatibilityError
from .media import (detect_silence, extract_audio, extract_audio_chunk, probe_media,
                    probe_wav_duration, validate_source)
from .longform import merge_chunk_transcripts, plan_chunks
from .longform_cache import LongFormCheckpointStore, LongFormIdentity, LongFormManifest
from .performance import (EtaEstimator, LongFormPerformanceKey, LongFormPerformanceProfile,
                          PerformanceKey, PerformanceProfile, PerformanceSpan,
                          StageRecorder, duration_band, resource_snapshot, runtime_identity)
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
    performance_spans: Tuple[PerformanceSpan, ...] = ()


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
        cancel_check: Optional[Callable] = None,
        media_cache_dir: Optional[Path] = None,
    ):
        self.adapter_factory = adapter_factory
        self.progress = progress or (lambda event: None)
        self.device_resolver = device_resolver
        self.cancel_check = cancel_check or (lambda: None)
        self.media_cache_dir = Path(media_cache_dir) if media_cache_dir else None

    def run(self, config: JobConfig) -> JobResult:
        recorder = StageRecorder()
        events = _PhaseEmitter(self.progress)
        phase = "validation"
        try:
            events.start(phase, "Validating input and dependencies")
            source = validate_source(config.input_path)
            self.cancel_check()
            media = probe_media(source)
            fingerprint = content_fingerprint(source)
            adapter = self.adapter_factory(config.model)
            selected_revision = str(getattr(adapter, "model_revision", "master"))
            decision = self.device_resolver(config.device)
            if config.device == "auto" and media.duration_ms > config.long_form.threshold_ms:
                evidence = LongFormPerformanceProfile(config.cache_dir / "long-form-performance.json")
                common = (str(getattr(adapter, "model_id", config.model)), selected_revision,
                          runtime_identity())
                band = duration_band(media.duration_ms / 1000)
                cpu_key = LongFormPerformanceKey(*common, "cpu", band,
                                                 config.long_form.version)
                mps_key = LongFormPerformanceKey(*common, "mps", band,
                                                 config.long_form.version)
                selected = evidence.choose_device(cpu_key, mps_key)
                if selected == "cpu":
                    decision = DeviceDecision("auto", "cpu", False,
                                              "CPU selected from compatible long-form evidence")
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
                    self.media_cache_dir / key / "audio.wav" if self.media_cache_dir else paths.audio,
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
                estimator = EtaEstimator(
                    duration_ms / 1000, profile.estimate_rtf(estimate_key)
                )
                estimated_seconds = estimator.initial_eta_seconds
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
                with recorder.measure("transcription-total"):
                    if duration_ms > config.long_form.threshold_ms:
                        transcript = self._transcribe_long_form(
                            config, audio_path, duration_ms, key, fingerprint, decision,
                            adapter, events, recorder, paths.directory, profile, estimator,
                        )
                    else:
                        transcript = self._transcribe(
                            config, audio_path, duration_ms, key, decision, adapter, events,
                            recorder, profile, estimator,
                        )
                processing_seconds = time.monotonic() - asr_started
                self.cancel_check()
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
                span_names = [span.name for span in recorder.spans]
                if (duration_ms > config.long_form.threshold_ms
                        and "chunk-asr" in span_names
                        and "checkpoint-resumed" not in span_names):
                    snapshot = resource_snapshot()
                    long_key = LongFormPerformanceKey(
                        transcript.metadata.model_id, transcript.metadata.model_revision,
                        runtime_identity(), transcript.metadata.device,
                        duration_band(duration_ms / 1000), config.long_form.version,
                    )
                    LongFormPerformanceProfile(
                        config.cache_dir / "long-form-performance.json"
                    ).record(long_key, rtf=processing_seconds / (duration_ms / 1000),
                             peak_rss_mb=snapshot.peak_rss_mb)
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
            self.cancel_check()
            events.start(phase, f"Writing {config.resolved_output_path}")
            output = write_srt(config.resolved_output_path, cues, overwrite=config.overwrite)
            events.complete(phase, f"Generated {output}")
            return JobResult(output, paths.transcript, transcript, cues, cache_hit, tuple(recorder.spans))
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
        recorder: Optional[StageRecorder] = None,
        profile: Optional[PerformanceProfile] = None,
        estimator: Optional[EtaEstimator] = None,
    ) -> Transcript:
        totals_by_epoch: Dict[int, float] = {}

        def adapter_progress(value: AdapterProgress) -> None:
            scope = getattr(value, "scope", "batch")
            kind = getattr(value, "kind", "actual")
            epoch = getattr(value, "epoch", 0)
            if scope == "global" and kind == "actual":
                active_adapter = getattr(adapter_progress, "active_adapter", adapter)
                if getattr(active_adapter, "progress_scope", "none") != "global":
                    return
            elif scope == "whole-input" and kind == "estimated":
                previous_total = totals_by_epoch.get(epoch)
                if previous_total is not None and previous_total != value.total:
                    return
                totals_by_epoch[epoch] = value.total
            else:
                return
            completed_audio = duration_ms / 1000 * (value.current / value.total)
            eta = estimator.remaining_seconds(completed_audio) if estimator else None
            events.update(
                "transcription",
                f"Transcribing on {getattr(adapter_progress, 'active_device', decision.resolved)}"
                + (" (segment estimate)" if kind == "estimated" else ""),
                kind=kind,
                current=value.current,
                total=value.total,
                unit=value.unit,
                eta=eta,
            )

        adapter_progress.active_adapter = adapter
        adapter_progress.active_device = decision.resolved

        request = AdapterRequest(
            audio_path,
            duration_ms,
            config.language,
            config.hotwords,
            decision.resolved,
            key,
            adapter_progress,
            0,
            recorder.record if recorder else None,
        )
        try:
            return adapter.transcribe(request)
        except MPSCompatibilityError:
            if not decision.fallback_allowed:
                raise
            events.start("transcription", "MPS failed; restarting transcription estimate on CPU")
            cpu_adapter = self.adapter_factory(config.model)
            if profile is not None:
                cpu_key = PerformanceKey(
                    str(getattr(cpu_adapter, "model_id", config.model)),
                    str(getattr(cpu_adapter, "model_revision", "master")),
                    "cpu", runtime_identity(),
                )
                estimator = EtaEstimator(duration_ms / 1000, profile.estimate_rtf(cpu_key))
            adapter_progress.active_adapter = cpu_adapter
            adapter_progress.active_device = "cpu"
            cpu_request = replace(
                request, device="cpu", progress_epoch=request.progress_epoch + 1
            )
            return cpu_adapter.transcribe(cpu_request)

    def _transcribe_long_form(
        self, config, audio_path, duration_ms, key, fingerprint, decision, adapter,
        events, recorder, job_directory, profile=None, initial_estimator=None,
    ):
        with recorder.measure("silence-planning"):
            silences = detect_silence(
                audio_path, duration_ms, config.long_form.minimum_silence_ms
            )
            plan = plan_chunks(duration_ms, silences, config.long_form)
        store = LongFormCheckpointStore(job_directory)

        def identity_for(active_adapter, device):
            return LongFormIdentity(
                fingerprint, PREPROCESSING_VERSION, plan.identity,
                str(getattr(active_adapter, "model_id", config.model)),
                str(getattr(active_adapter, "model_revision", "master")), device,
                config.language, config.hotwords,
            )

        def run_attempt(active_adapter, device, epoch):
            if epoch == 0 and initial_estimator is not None:
                estimator = initial_estimator
            else:
                estimate_key = PerformanceKey(
                    str(getattr(active_adapter, "model_id", config.model)),
                    str(getattr(active_adapter, "model_revision", "master")),
                    device, runtime_identity(),
                )
                estimator = EtaEstimator(
                    duration_ms / 1000,
                    profile.estimate_rtf(estimate_key) if profile is not None else None,
                )
            identity = identity_for(active_adapter, device)
            manifest = store.load_manifest(identity, plan)
            if manifest is None:
                manifest = LongFormManifest(identity, duration_ms, plan.chunks)
                store.save_manifest(manifest)
            checkpoints = store.load_valid(identity, plan)
            if checkpoints:
                recorder.record("checkpoint-resumed", 0.0)
            transcripts = {index: item.transcript for index, item in checkpoints.items()}
            committed = sum(chunk.duration_ms - chunk.overlap_ms for chunk in plan.chunks
                            if chunk.index in transcripts)
            processing_seconds = sum(
                item.metadata.processing_seconds for item in transcripts.values()
                if isinstance(item.metadata.processing_seconds, (int, float))
                and math.isfinite(item.metadata.processing_seconds)
                and item.metadata.processing_seconds > 0
            )
            if committed and processing_seconds:
                estimator.recalibrate(committed / 1000, processing_seconds)
            if checkpoints:
                events.update("transcription",
                              f"Resuming {len(checkpoints)}/{len(plan.chunks)} chunks on {device}",
                              kind="estimated", current=min(committed, duration_ms * .95),
                              total=duration_ms, unit="milliseconds",
                              eta=estimator.remaining_seconds(committed / 1000, smooth=False))
            pending = [chunk for chunk in plan.chunks if chunk.index not in transcripts]
            if pending:
                with active_adapter.open_session(device, recorder.record) as session:
                    for chunk in pending:
                        self.cancel_check()
                        chunk_path = ((self.media_cache_dir / key / "chunks") if self.media_cache_dir
                                      else store.root / "audio") / f"{chunk.index:04d}.wav"
                        try:
                            extract_audio_chunk(audio_path, chunk_path, chunk.start_ms, chunk.end_ms)
                            base = committed
                            def chunk_progress(value, chunk=chunk, base=base):
                                if getattr(value, "scope", "") != "whole-input":
                                    return
                                fraction = value.current / value.total
                                current = base + fraction * (chunk.duration_ms - chunk.overlap_ms)
                                events.update(
                                    "transcription",
                                    f"Chunk {chunk.index + 1}/{len(plan.chunks)} "
                                    f"{chunk.start_ms/1000:.0f}-{chunk.end_ms/1000:.0f}s on {device}",
                                    kind="estimated", current=min(current, duration_ms * .95),
                                    total=duration_ms, unit="milliseconds",
                                    eta=estimator.remaining_seconds(current / 1000),
                                )
                            request = AdapterRequest(
                                chunk_path, chunk.duration_ms, config.language, config.hotwords,
                                device, identity.digest, chunk_progress, epoch, recorder.record,
                            )
                            with recorder.measure("chunk-asr"):
                                value = session.transcribe(request)
                            self.cancel_check()
                            store.save_checkpoint(identity, chunk, value)
                            transcripts[chunk.index] = value
                            committed += chunk.duration_ms - chunk.overlap_ms
                            chunk_processing = value.metadata.processing_seconds
                            if (isinstance(chunk_processing, (int, float))
                                    and math.isfinite(chunk_processing)
                                    and chunk_processing > 0):
                                processing_seconds += chunk_processing
                                estimator.recalibrate(committed / 1000, processing_seconds)
                            events.update(
                                "transcription", f"Committed chunk {chunk.index + 1}/{len(plan.chunks)}",
                                kind="estimated", current=min(committed, duration_ms * .95),
                                total=duration_ms, unit="milliseconds",
                                eta=estimator.remaining_seconds(committed / 1000, smooth=False),
                            )
                        finally:
                            try:
                                chunk_path.unlink()
                            except FileNotFoundError:
                                pass
            with recorder.measure("chunk-merge"):
                return merge_chunk_transcripts(plan, transcripts, cache_key=key).transcript

        try:
            return run_attempt(adapter, decision.resolved, 0)
        except MPSCompatibilityError:
            if not decision.fallback_allowed:
                raise
            events.start("transcription", "MPS failed; resuming long-form transcription on CPU")
            return run_attempt(self.adapter_factory(config.model), "cpu", 1)


__all__ = ["JobResult", "LocalTranscriptionService", "ProgressEvent"]
