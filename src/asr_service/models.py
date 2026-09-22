"""Validated wire contracts shared by API and host clients."""

import hashlib
import json
import re
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def folder_id(value):
    value = value.strip()
    if "://" in value:
        url = urlparse(value)
        if url.scheme != "https" or url.netloc != "drive.google.com":
            raise ValueError("請提供 Google Drive 資料夾 URL 或 ID")
        match = re.fullmatch(r"/drive/(?:u/\d+/)?folders/([\w-]+)(?:/)?", url.path)
        if not match:
            raise ValueError("無效的 Drive 資料夾 URL")
        value = match.group(1)
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,200}", value):
        raise ValueError("無效的 Drive ID")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Settings(StrictModel):
    model: str = "fun-asr-nano"
    device: str = "auto"
    hotwords: list[str] = Field(default_factory=list, max_length=100)
    max_units: int = Field(default=22, ge=1, le=100)
    max_duration_ms: int = Field(default=6000, ge=250, le=30000)

    @field_validator("model")
    @classmethod
    def model_choice(cls, v):
        if v not in ("fun-asr-nano", "paraformer"):
            raise ValueError("不支援的模型")
        return v

    @field_validator("device")
    @classmethod
    def device_choice(cls, v):
        if v not in ("auto", "mps", "cpu"):
            raise ValueError("不支援的裝置")
        return v

    @field_validator("hotwords")
    @classmethod
    def clean_hotwords(cls, v):
        words = dict.fromkeys(
            w.strip() for item in v for w in item.split(",") if w.strip()
        )
        if any(len(w) > 200 for w in words):
            raise ValueError("熱詞過長")
        return list(words)


class BatchInput(StrictModel):
    source: str
    destination: str
    settings: Settings = Field(default_factory=Settings)
    interval_seconds: int = Field(default=0, ge=0, le=604800)

    @field_validator("source", "destination")
    @classmethod
    def parse_folder(cls, v):
        return folder_id(v)

    @field_validator("interval_seconds")
    @classmethod
    def interval(cls, v):
        if v and v < 120:
            raise ValueError("掃描間隔至少 120 秒")
        return v


class Media(StrictModel):
    id: str
    name: str = Field(max_length=1000)
    path: str = Field(max_length=8000)
    version: str = Field(min_length=1, max_length=300)
    size: int = Field(ge=0)
    md5: str = ""
    mime: str = ""

    @field_validator("id")
    @classmethod
    def parse_id(cls, v):
        return folder_id(v)


def natural_key(value):
    return [
        (1, int(p)) if p.isdigit() else (0, p.casefold())
        for p in re.split(r"(\d+)", value)
    ]
