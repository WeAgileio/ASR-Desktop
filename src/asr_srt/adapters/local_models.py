import os
from pathlib import Path


ALIASES = {
    "fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "ct-punc": "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
    "paraformer-zh": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
}


def resolve_model_reference(model_id: str) -> str:
    """Prefer complete legacy/new ModelScope cache entries over a download."""
    canonical = ALIASES.get(model_id, model_id)
    if "/" not in canonical:
        return model_id
    organization, name = canonical.split("/", 1)
    roots = []
    configured = os.environ.get("MODELSCOPE_CACHE")
    if configured:
        roots.append(Path(configured).expanduser())
    roots.append(Path.home() / ".cache" / "modelscope")
    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        candidates = (
            root / "hub" / "models" / organization / name,
            root / "models" / f"{organization}--{name}" / "snapshots" / "master",
        )
        for candidate in candidates:
            if (candidate / "model.pt").is_file() and (candidate / "config.yaml").is_file():
                return str(candidate)
    return model_id

