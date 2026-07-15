import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Tuple

from .errors import ValidationError

TRANSCRIPT_SCHEMA_VERSION = 1


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{name} must be an integer millisecond value")
    return value


@dataclass(frozen=True)
class TextUnit:
    text: str
    start_ms: int
    end_ms: int

    def __post_init__(self):
        if not self.text or not self.text.strip():
            raise ValidationError("Text units cannot be empty")
        _require_int(self.start_ms, "start_ms")
        _require_int(self.end_ms, "end_ms")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValidationError("Text unit timestamps must be non-negative and ordered")


@dataclass(frozen=True)
class TranscriptMetadata:
    model_id: str
    model_revision: str
    device: str
    hotwords: Tuple[str, ...] = field(default_factory=tuple)
    processing_seconds: float = 0.0
    cache_key: str = ""


@dataclass(frozen=True)
class Transcript:
    full_text: str
    duration_ms: int
    language: str
    units: Tuple[TextUnit, ...]
    metadata: TranscriptMetadata
    schema_version: int = TRANSCRIPT_SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != TRANSCRIPT_SCHEMA_VERSION:
            raise ValidationError(
                f"Unsupported transcript schema {self.schema_version}; expected {TRANSCRIPT_SCHEMA_VERSION}"
            )
        _require_int(self.duration_ms, "duration_ms")
        if self.duration_ms < 0:
            raise ValidationError("duration_ms cannot be negative")
        previous_start = -1
        for unit in self.units:
            if unit.start_ms < previous_start:
                raise ValidationError("Transcript units must be ordered by start time")
            if unit.end_ms > self.duration_ms:
                raise ValidationError("Transcript unit exceeds media duration")
            previous_start = unit.start_ms

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["units"] = [asdict(unit) for unit in self.units]
        data["metadata"]["hotwords"] = list(self.metadata.hotwords)
        return data

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": ")
        ) + "\n"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transcript":
        try:
            metadata_data = dict(data["metadata"])
            metadata_data["hotwords"] = tuple(metadata_data.get("hotwords", ()))
            return cls(
                full_text=str(data["full_text"]),
                duration_ms=data["duration_ms"],
                language=str(data["language"]),
                units=tuple(TextUnit(**item) for item in data["units"]),
                metadata=TranscriptMetadata(**metadata_data),
                schema_version=data.get("schema_version", 0),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid transcript structure: {exc}") from exc

    @classmethod
    def from_json(cls, value: str) -> "Transcript":
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid transcript JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValidationError("Transcript JSON root must be an object")
        return cls.from_dict(data)


@dataclass(frozen=True)
class SubtitleSettings:
    max_display_units: int = 22
    max_duration_ms: int = 6000
    target_min_duration_ms: int = 1000
    silence_gap_ms: int = 650

    def __post_init__(self):
        if not 1 <= self.max_display_units <= 100:
            raise ValidationError("max_display_units must be between 1 and 100")
        if not 250 <= self.max_duration_ms <= 30000:
            raise ValidationError("max_duration_ms must be between 250 and 30000")
        if not 0 <= self.target_min_duration_ms <= self.max_duration_ms:
            raise ValidationError("target_min_duration_ms must be between 0 and max_duration_ms")
        if not 0 <= self.silence_gap_ms <= 10000:
            raise ValidationError("silence_gap_ms must be between 0 and 10000")


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self):
        _require_int(self.start_ms, "start_ms")
        _require_int(self.end_ms, "end_ms")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValidationError("Cue timestamps must be non-negative and ordered")
        if not self.text or not self.text.strip():
            raise ValidationError("Cue text cannot be empty")

