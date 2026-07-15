import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from ..domain import TextUnit
from ..errors import ModelOutputError

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['._+-][A-Za-z0-9]+)*|[\u3400-\u9fff]|[^\s]")


def text_tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text or "")


def _milliseconds(value: Any) -> int:
    number = float(value)
    # FunASR native timestamps are milliseconds. API-shaped seconds commonly
    # contain decimals; preserve integer values as milliseconds.
    if isinstance(value, float) and number < 10000:
        return round(number * 1000)
    return round(number)


def normalize_result(raw: Any, duration_ms: int) -> Tuple[str, Tuple[TextUnit, ...]]:
    if isinstance(raw, list):
        if not raw:
            raise ModelOutputError("Model returned an empty result list")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ModelOutputError("Model result must be an object")
    full_text = str(raw.get("text") or "").strip()
    if not full_text:
        raise ModelOutputError("Model result is missing recognized text")
    timestamps = raw.get("timestamps") or raw.get("timestamp") or raw.get("ctc_timestamps")
    units: List[TextUnit] = []
    if timestamps:
        alignment_text = str(raw.get("ctc_text") or full_text)
        fallback_tokens = text_tokens(alignment_text)
        for index, item in enumerate(timestamps):
            token = None
            start = end = None
            if isinstance(item, dict):
                token = item.get("word") or item.get("text") or item.get("token")
                start = item.get("start")
                end = item.get("end")
                if start is None:
                    start = item.get("start_time")
                if end is None:
                    end = item.get("end_time")
            elif isinstance(item, (list, tuple)):
                if len(item) >= 3 and isinstance(item[0], str):
                    token, start, end = item[0], item[1], item[2]
                elif len(item) >= 2:
                    start, end = item[0], item[1]
            if token is None and index < len(fallback_tokens):
                token = fallback_tokens[index]
            if token and start is not None and end is not None:
                start_ms = max(0, min(duration_ms, _milliseconds(start)))
                end_ms = max(start_ms, min(duration_ms, _milliseconds(end)))
                units.append(TextUnit(str(token), start_ms, end_ms))
    if not units:
        sentences = raw.get("sentence_info") or raw.get("segments") or []
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or sentence.get("sentence") or "").strip()
            start, end = sentence.get("start"), sentence.get("end")
            if text and start is not None and end is not None:
                start_ms = max(0, min(duration_ms, _milliseconds(start)))
                end_ms = max(start_ms, min(duration_ms, _milliseconds(end)))
                units.append(TextUnit(text, start_ms, end_ms))
    if not units:
        raise ModelOutputError(
            "Model result is missing timestamps required for SRT generation "
            f"(available fields: {', '.join(sorted(str(key) for key in raw.keys()))}; "
            f"timestamp preview: {repr(raw.get('timestamps') or raw.get('timestamp') or raw.get('ctc_timestamps'))[:500]})"
        )
    units.sort(key=lambda unit: (unit.start_ms, unit.end_ms))
    return full_text, tuple(units)


def discover_revision(model: Any, fallback: str) -> str:
    for owner in (model, getattr(model, "model", None)):
        if owner is None:
            continue
        for name in ("revision", "model_revision", "version"):
            value = getattr(owner, name, None)
            if value:
                return str(value)
    model_path = getattr(model, "model_path", None)
    return str(model_path) if model_path else fallback
