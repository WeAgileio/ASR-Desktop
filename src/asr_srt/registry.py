"""Data-only model registrations; executable engines are an explicit allowlist."""

import copy
import hashlib
from importlib import resources
import json
from pathlib import PurePosixPath

from .errors import ValidationError


ENGINES = ("funasr-nano", "funasr-paraformer", "faster-whisper", "transformers-whisper")
LEGACY = {
    "fun-asr-nano": {"engine": "funasr-nano", "primary": "nano", "devices": ["cpu", "mps"],
                     "hotwords": True, "required_files": {"nano": ["model.pt", "config.yaml"],
                                                           "vad": ["model.pt", "config.yaml"]}, "parameters": {}},
    "paraformer": {"engine": "funasr-paraformer", "primary": "paraformer", "devices": ["cpu", "mps"],
                   "hotwords": True, "required_files": {key: ["model.pt", "config.yaml"]
                                                       for key in ("paraformer", "vad", "punctuation")}, "parameters": {}},
}


def catalog():
    return json.loads(resources.files("asr_desktop").joinpath("data/models.json").read_text())


def execution(definition):
    value = copy.deepcopy(definition.get("execution", LEGACY.get(definition["id"])))
    if not isinstance(value, dict) or value.get("engine") not in ENGINES:
        raise ValidationError("Unsupported model engine: " + str(definition.get("id")))
    if not value.get("primary") or not value.get("devices") or any(d not in ("cpu", "mps") for d in value["devices"]):
        raise ValidationError("Invalid model primary component or devices")
    if type(value.get("hotwords")) is not bool or not isinstance(value.get("parameters"), dict):
        raise ValidationError("Invalid model capabilities or parameters")
    files = value.get("required_files")
    if not isinstance(files, dict) or value["primary"] not in files:
        raise ValidationError("Missing required model files")
    for key, paths in files.items():
        if key not in definition["components"] or not paths:
            raise ValidationError("Required model component is absent")
        for path in paths:
            if not isinstance(path, str) or not path or PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
                raise ValidationError("Unsafe required model file")
    return value


def registration(identifier, source=None):
    source = catalog() if source is None else source
    for item in source["models"]:
        if item["id"] == identifier:
            result = copy.deepcopy(item)
            result["execution"] = execution(item)
            return result
    raise ValidationError(f"Unsupported model '{identifier}'. Choose: " + ", ".join(i["id"] for i in source["models"]))


def supported_models():
    return tuple(item["id"] for item in catalog()["models"])


def validate_options(definition, device, hotwords):
    value = execution(definition)
    resolved = "mps" if device == "gpu" else device
    if resolved != "auto" and resolved not in value["devices"]:
        raise ValidationError(f"{definition['id']} supports devices: auto, " + ", ".join(value["devices"]))
    if hotwords and not value["hotwords"]:
        raise ValidationError(f"{definition['id']} does not support hotwords")


def execution_identity(definition):
    return hashlib.sha256(json.dumps(execution(definition), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
