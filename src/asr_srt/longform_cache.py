import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from .domain import Transcript
from .errors import ValidationError
from .files import atomic_write_text
from .longform import AudioChunk, ChunkPlan

CHECKPOINT_VERSION = 1


@dataclass(frozen=True)
class LongFormIdentity:
    source: str
    preprocessing: str
    plan: str
    model: str
    model_revision: str
    device: str
    language: str
    hotwords: Tuple[str, ...]
    recognition: str = "{}"

    @property
    def digest(self):
        payload = asdict(self)
        payload["hotwords"] = list(self.hotwords)
        value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class LongFormManifest:
    identity: LongFormIdentity
    duration_ms: int
    chunks: Tuple[AudioChunk, ...]
    version: int = CHECKPOINT_VERSION


@dataclass(frozen=True)
class ChunkCheckpoint:
    identity_digest: str
    chunk: AudioChunk
    transcript: Transcript
    checksum: str
    version: int = CHECKPOINT_VERSION


class LongFormCheckpointStore:
    def __init__(self, job_directory: Path):
        self.root = Path(job_directory) / "longform"

    @property
    def manifest_path(self):
        return self.root / "manifest.json"

    def checkpoint_path(self, index):
        return self.root / "chunks" / f"{index:04d}.json"

    def save_manifest(self, manifest: LongFormManifest):
        payload = {"version": manifest.version, "identity": asdict(manifest.identity),
                   "duration_ms": manifest.duration_ms,
                   "chunks": [asdict(chunk) for chunk in manifest.chunks]}
        atomic_write_text(self.manifest_path,
                          json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    def load_manifest(self, expected: LongFormIdentity, plan: ChunkPlan):
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            identity_data = dict(data["identity"])
            identity_data["hotwords"] = tuple(identity_data.get("hotwords", ()))
            identity = LongFormIdentity(**identity_data)
            chunks = tuple(AudioChunk(**item) for item in data["chunks"])
            if data["version"] != CHECKPOINT_VERSION or identity != expected:
                return None
            if data["duration_ms"] != plan.duration_ms or chunks != plan.chunks:
                return None
            return LongFormManifest(identity, data["duration_ms"], chunks, data["version"])
        except (OSError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            return None

    def save_checkpoint(self, identity: LongFormIdentity, chunk: AudioChunk, transcript: Transcript):
        transcript_json = transcript.to_json()
        checksum = hashlib.sha256(transcript_json.encode()).hexdigest()
        payload = {"version": CHECKPOINT_VERSION, "identity": identity.digest,
                   "chunk": asdict(chunk), "transcript": transcript.to_dict(),
                   "checksum": checksum}
        atomic_write_text(self.checkpoint_path(chunk.index),
                          json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")

    def load_checkpoint(self, identity: LongFormIdentity, chunk: AudioChunk):
        try:
            data = json.loads(self.checkpoint_path(chunk.index).read_text(encoding="utf-8"))
            if data["version"] != CHECKPOINT_VERSION or data["identity"] != identity.digest:
                return None
            if AudioChunk(**data["chunk"]) != chunk:
                return None
            transcript = Transcript.from_dict(data["transcript"])
            checksum = hashlib.sha256(transcript.to_json().encode()).hexdigest()
            if checksum != data["checksum"] or transcript.duration_ms != chunk.duration_ms:
                return None
            return ChunkCheckpoint(identity.digest, chunk, transcript, checksum)
        except (OSError, KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            return None

    def load_valid(self, identity: LongFormIdentity, plan: ChunkPlan) -> Dict[int, ChunkCheckpoint]:
        if self.load_manifest(identity, plan) is None:
            return {}
        result = {}
        for chunk in plan.chunks:
            checkpoint = self.load_checkpoint(identity, chunk)
            if checkpoint is not None and chunk.index not in result:
                result[chunk.index] = checkpoint
        return result
