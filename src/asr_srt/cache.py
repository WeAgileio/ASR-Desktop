import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .domain import Transcript
from .errors import ValidationError
from .files import atomic_write_text

PREPROCESSING_VERSION = "mono-16k-pcm-v1"


def content_fingerprint(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def cache_identity(
    media_fingerprint: str,
    model: str,
    model_revision: str,
    language: str,
    hotwords: Tuple[str, ...],
    recognition_settings: Optional[Dict[str, Any]] = None,
) -> str:
    payload = {
        "media": media_fingerprint,
        "model": model,
        "model_revision": model_revision,
        "language": language,
        "hotwords": list(hotwords),
        "preprocessing": PREPROCESSING_VERSION,
        "recognition": recognition_settings or {},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachePaths:
    directory: Path
    transcript: Path
    audio: Path


class TranscriptCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def paths(self, key: str) -> CachePaths:
        directory = self.root / "jobs" / key[:2] / key
        return CachePaths(directory, directory / "transcript.json", directory / "audio.wav")

    def load(self, key: str) -> Optional[Transcript]:
        path = self.paths(key).transcript
        if not path.exists():
            return None
        try:
            transcript = Transcript.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            return None
        if transcript.metadata.cache_key != key:
            return None
        return transcript

    def save(self, key: str, transcript: Transcript) -> Path:
        if transcript.metadata.cache_key != key:
            raise ValidationError("Transcript cache key does not match target cache identity")
        path = self.paths(key).transcript
        atomic_write_text(path, transcript.to_json(), overwrite=True)
        return path

