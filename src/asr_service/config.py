"""Explicit configuration; credentials are never embedded in source or job payloads."""

from dataclasses import dataclass
import os
from pathlib import Path


def secret(name):
    path = os.environ.get(name + "_FILE")
    value = Path(path).read_text().strip() if path else os.environ.get(name, "")
    if len(value) < 24:
        raise ValueError(f"{name} must contain at least 24 characters")
    return value


@dataclass(frozen=True)
class APIConfig:
    db: Path
    password: str
    worker_token: str
    signing_key: str
    redis_url: str
    dispatch: bool = True

    @classmethod
    def environment(cls):
        return cls(
            Path(os.environ.get("ASR_DATABASE", "/data/asr.sqlite3")),
            secret("ASR_ADMIN_PASSWORD"),
            secret("ASR_WORKER_TOKEN"),
            secret("ASR_SIGNING_KEY"),
            os.environ.get("ASR_REDIS_URL", "redis://127.0.0.1:16379/0"),
        )


def workspace():
    path = (
        Path(
            os.environ.get(
                "ASR_WORKSPACE",
                str(Path.home() / "Library/Application Support/asr-service"),
            )
        )
        .expanduser()
        .resolve()
    )
    if "Mobile Documents" in path.parts or "CloudStorage" in path.parts:
        raise ValueError("ASR_WORKSPACE must be outside cloud-synchronized directories")
    path.mkdir(parents=True, exist_ok=True)
    return path
