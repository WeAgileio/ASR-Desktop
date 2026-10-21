from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from .domain import SubtitleSettings
from .longform import LongFormSettings
from .errors import ValidationError

from .registry import registration, supported_models, validate_options

SUPPORTED_MODELS = supported_models()
SUPPORTED_DEVICES = ("auto", "mps", "cpu")


def default_cache_dir() -> Path:
    return Path.home() / "Library" / "Caches" / "asr-srt"


def normalize_hotwords(values) -> Tuple[str, ...]:
    result = []
    seen = set()
    for raw in values or ():
        for item in str(raw).split(","):
            word = item.strip()
            if word and word not in seen:
                result.append(word)
                seen.add(word)
    return tuple(result)


@dataclass(frozen=True)
class JobConfig:
    input_path: Path
    model: str = "fun-asr-nano"
    device: str = "auto"
    language: str = "中文"
    hotwords: Tuple[str, ...] = field(default_factory=tuple)
    output_path: Optional[Path] = None
    cache_dir: Path = field(default_factory=default_cache_dir)
    use_cache: bool = True
    overwrite: bool = False
    traditional: bool = True
    subtitle: SubtitleSettings = field(default_factory=SubtitleSettings)
    long_form: LongFormSettings = field(default_factory=LongFormSettings)
    model_definition: Optional[dict] = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        definition = self.model_definition or registration(self.model)
        if definition["id"] != self.model:
            raise ValidationError("Model definition does not match selected model")
        validate_options(definition, self.device, normalize_hotwords(self.hotwords))
        if self.device not in SUPPORTED_DEVICES:
            raise ValidationError(
                f"Unsupported device '{self.device}'. Choose: {', '.join(SUPPORTED_DEVICES)}"
            )
        object.__setattr__(self, "input_path", Path(self.input_path).expanduser())
        object.__setattr__(self, "cache_dir", Path(self.cache_dir).expanduser())
        if self.output_path is not None:
            object.__setattr__(self, "output_path", Path(self.output_path).expanduser())
        object.__setattr__(self, "hotwords", normalize_hotwords(self.hotwords))

    @property
    def resolved_output_path(self) -> Path:
        return self.output_path or self.input_path.with_suffix(".srt")
