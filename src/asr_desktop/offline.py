"""The desktop adapter boundary accepts only already verified local snapshots."""

import os
from pathlib import Path
import re
import socket

from .models import ModelError


def disable_network():
    """Call in a disposable inference process, never in the download coordinator."""
    def blocked(*args, **kwargs):
        raise OSError("Desktop inference is offline; prepare models before transcription")
    socket.create_connection = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")


def local_adapter(model, component_paths, revisions, model_factory=None, definition=None):
    from asr_srt.adapters import create_adapter
    from asr_srt.registry import registration, execution, execution_identity
    definition = definition or registration(model)
    spec = execution(definition)
    primary = spec["primary"]
    required = spec["required_files"]
    roots = {}
    for key in required:
        if key not in component_paths or not re.fullmatch(r"[0-9a-f]{40}", revisions.get(key, "")):
            raise ModelError("model_not_ready", "Missing pinned component: " + key)
        root = Path(component_paths[key])
        if not root.is_absolute() or any(not (root / name).is_file() for name in required[key]):
            raise ModelError("model_not_ready", "Missing local component files: " + key)
        roots[key] = str(root)
    if spec["engine"] in ("faster-whisper", "transformers-whisper"):
        from asr_srt.adapters.whisper import LocalWhisperAdapter
        adapter = LocalWhisperAdapter(definition, roots[primary], model_factory)
        adapter.model_revision = definition.get("snapshot_id", revisions[primary]) + ":" + execution_identity(definition)
        return adapter
    if model_factory is None:
        from funasr import AutoModel
        model_factory = AutoModel
    def factory(**kwargs):
        kwargs.update(model=roots[primary], model_revision=revisions[primary],
                      vad_model=roots["vad"], vad_model_revision=revisions["vad"],
                      disable_update=True, trust_remote_code=False)
        if primary == "paraformer":
            kwargs.update(punc_model=roots["punctuation"], punc_model_revision=revisions["punctuation"])
        return model_factory(**kwargs)
    adapter = create_adapter(model, model_factory=factory, definition=definition)
    adapter.model_revision = revisions[primary]
    return adapter
