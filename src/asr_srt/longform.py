import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Optional, Tuple

from .errors import ValidationError
from .domain import TextUnit, Transcript, TranscriptMetadata

PLANNER_VERSION = 1


@dataclass(frozen=True)
class LongFormSettings:
    threshold_ms: int = 30 * 60 * 1000
    target_ms: int = 20 * 60 * 1000
    minimum_ms: int = 15 * 60 * 1000
    maximum_ms: int = 30 * 60 * 1000
    search_window_ms: int = 60 * 1000
    minimum_silence_ms: int = 600
    fallback_overlap_ms: int = 1500
    version: int = PLANNER_VERSION

    def __post_init__(self):
        if self.version != PLANNER_VERSION:
            raise ValidationError("Unsupported long-form planner version")
        if not 0 < self.minimum_ms <= self.target_ms <= self.maximum_ms:
            raise ValidationError("Long-form chunk durations are invalid")
        if self.threshold_ms <= 0 or self.search_window_ms < 0 or self.minimum_silence_ms < 0:
            raise ValidationError("Long-form planner settings must be non-negative")
        if not 0 <= self.fallback_overlap_ms < self.minimum_ms:
            raise ValidationError("Fallback overlap must be smaller than a chunk")


@dataclass(frozen=True)
class SilenceInterval:
    start_ms: int
    end_ms: int

    def __post_init__(self):
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValidationError("Silence interval must be positive and ordered")


@dataclass(frozen=True)
class AudioChunk:
    index: int
    start_ms: int
    end_ms: int
    overlap_ms: int = 0
    boundary_kind: str = "final"

    @property
    def duration_ms(self):
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class ChunkPlan:
    duration_ms: int
    chunks: Tuple[AudioChunk, ...]
    settings: LongFormSettings
    identity: str


_SILENCE = re.compile(r"silence_(start|end):\s*([0-9]+(?:\.[0-9]+)?)")


def parse_silence_intervals(lines: Iterable[str], duration_ms: Optional[int] = None):
    started = None
    result = []
    for raw in lines:
        match = _SILENCE.search(str(raw))
        if not match:
            continue
        value = round(float(match.group(2)) * 1000)
        if duration_ms is not None:
            value = min(max(0, value), duration_ms)
        if match.group(1) == "start":
            started = value
        elif started is not None and value > started:
            result.append(SilenceInterval(started, value))
            started = None
    if started is not None and duration_ms is not None and duration_ms > started:
        result.append(SilenceInterval(started, duration_ms))
    return tuple(result)


def _identity(duration_ms, settings, chunks):
    payload = {"duration_ms": duration_ms, "settings": asdict(settings),
               "chunks": [asdict(chunk) for chunk in chunks]}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def plan_chunks(duration_ms: int, silences=(), settings=LongFormSettings()) -> ChunkPlan:
    if duration_ms <= 0:
        raise ValidationError("Audio duration must be positive")
    if duration_ms <= settings.threshold_ms:
        chunks = (AudioChunk(0, 0, duration_ms),)
        return ChunkPlan(duration_ms, chunks, settings, _identity(duration_ms, settings, chunks))
    candidates = tuple(
        silence for silence in silences
        if silence.end_ms - silence.start_ms >= settings.minimum_silence_ms
    )
    chunks = []
    start = 0
    while duration_ms - start > settings.maximum_ms:
        target = start + settings.target_ms
        lower = max(start + settings.minimum_ms, target - settings.search_window_ms)
        upper = min(start + settings.maximum_ms, target + settings.search_window_ms)
        mids = [round((item.start_ms + item.end_ms) / 2) for item in candidates
                if lower <= round((item.start_ms + item.end_ms) / 2) <= upper]
        if mids:
            end = min(mids, key=lambda value: (abs(value - target), value))
            overlap, kind = 0, "silence"
        else:
            end = min(target, duration_ms)
            overlap, kind = settings.fallback_overlap_ms, "fallback"
        chunks.append(AudioChunk(len(chunks), start, end, 0 if not chunks else max(0, chunks[-1].end_ms - start), kind))
        start = end - overlap
    chunks.append(AudioChunk(len(chunks), start, duration_ms,
                             0 if not chunks else max(0, chunks[-1].end_ms - start), "final"))
    validate_plan(duration_ms, tuple(chunks), settings)
    value = tuple(chunks)
    return ChunkPlan(duration_ms, value, settings, _identity(duration_ms, settings, value))


def validate_plan(duration_ms, chunks, settings):
    if not chunks or chunks[0].start_ms != 0 or chunks[-1].end_ms != duration_ms:
        raise ValidationError("Chunk plan must cover the complete timeline")
    previous = None
    for index, chunk in enumerate(chunks):
        if chunk.index != index or chunk.start_ms < 0 or chunk.end_ms <= chunk.start_ms:
            raise ValidationError("Chunk plan contains invalid boundaries")
        if chunk.end_ms > duration_ms or chunk.duration_ms > settings.maximum_ms:
            raise ValidationError("Chunk exceeds configured bounds")
        if previous:
            overlap = previous.end_ms - chunk.start_ms
            if overlap < 0 or overlap > settings.fallback_overlap_ms or overlap != chunk.overlap_ms:
                raise ValidationError("Chunk plan contains an invalid gap or overlap")
        previous = chunk


@dataclass(frozen=True)
class MergeResult:
    transcript: Transcript
    diagnostics: Tuple[str, ...] = ()


def _normalized(value):
    return "".join(str(value).lower().split())


def merge_chunk_transcripts(plan: ChunkPlan, transcripts, *, cache_key="") -> MergeResult:
    ordered = []
    diagnostics = []
    metadata = None
    language = None
    processing = 0.0
    for chunk in plan.chunks:
        value = transcripts.get(chunk.index)
        if value is None:
            raise ValidationError(f"Missing transcript for chunk {chunk.index}")
        if value.duration_ms != chunk.duration_ms:
            raise ValidationError("Chunk transcript duration does not match its plan")
        if metadata is None:
            metadata, language = value.metadata, value.language
        elif (value.metadata.model_id, value.metadata.model_revision, value.metadata.device,
              value.language, value.metadata.hotwords) != (
              metadata.model_id, metadata.model_revision, metadata.device, language,
              metadata.hotwords):
            raise ValidationError("Chunk transcript metadata is inconsistent")
        processing += value.metadata.processing_seconds
        incoming = [TextUnit(unit.text, unit.start_ms + chunk.start_ms,
                             min(plan.duration_ms, unit.end_ms + chunk.start_ms))
                    for unit in value.units]
        drop = 0
        if chunk.overlap_ms and ordered and incoming:
            maximum = min(20, len(ordered), len(incoming))
            for size in range(maximum, 0, -1):
                left = _normalized("".join(unit.text for unit in ordered[-size:]))
                right = _normalized("".join(unit.text for unit in incoming[:size]))
                if left and left == right and incoming[0].start_ms <= ordered[-1].end_ms:
                    drop = size
                    break
            if not drop and incoming[0].start_ms < ordered[-1].end_ms:
                diagnostics.append(f"Ambiguous overlap before chunk {chunk.index}")
        for unit in incoming[drop:]:
            if ordered and unit.start_ms < ordered[-1].end_ms:
                unit = TextUnit(unit.text, ordered[-1].end_ms,
                                max(ordered[-1].end_ms, unit.end_ms))
            ordered.append(unit)
    if metadata is None or not ordered:
        raise ValidationError("Merged transcript cannot be empty")
    merged_metadata = TranscriptMetadata(metadata.model_id, metadata.model_revision,
                                         metadata.device, metadata.hotwords,
                                         round(processing, 3), cache_key)
    merged = Transcript("".join(unit.text for unit in ordered), plan.duration_ms,
                        language, tuple(ordered), merged_metadata)
    return MergeResult(merged, tuple(diagnostics))
