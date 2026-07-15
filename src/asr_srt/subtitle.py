import re
from dataclasses import replace
from typing import Callable, Iterable, List, Sequence, Tuple

from .domain import SubtitleCue, SubtitleSettings, TextUnit, Transcript
from .errors import DependencyError

_LATIN = re.compile(r"^[A-Za-z0-9]")
_NO_SPACE_BEFORE = set("，。！？；：、,.!?;:%)]}”’")
_NO_SPACE_AFTER = set("([{\u201c‘")
_SENTENCE_END = set("。！？.!?")
_SOFT_END = set("，；：、,;:")


def display_unit_count(text: str) -> int:
    words = re.findall(r"[A-Za-z0-9]+(?:['._+-][A-Za-z0-9]+)*|[\u3400-\u9fff]|[^\s]", text)
    return len(words)


def join_unit_text(units: Sequence[TextUnit]) -> str:
    result = ""
    previous = ""
    for unit in units:
        token = unit.text.strip()
        if not token:
            continue
        needs_space = bool(
            result
            and token[0] not in _NO_SPACE_BEFORE
            and previous[-1:] not in _NO_SPACE_AFTER
            and (_LATIN.match(token) or _LATIN.match(previous[-1:]))
        )
        result += (" " if needs_space else "") + token
        previous = token
    return result.strip()


def _ends_with(text: str, characters) -> bool:
    stripped = text.rstrip('"\'”’)]}')
    return bool(stripped) and stripped[-1] in characters


def _make_cue(units: Sequence[TextUnit]) -> SubtitleCue:
    return SubtitleCue(units[0].start_ms, units[-1].end_ms, join_unit_text(units))


def segment_transcript(
    transcript: Transcript,
    settings: SubtitleSettings,
) -> Tuple[SubtitleCue, ...]:
    if not transcript.units:
        return ()
    cues: List[SubtitleCue] = []
    current: List[TextUnit] = []
    for unit in transcript.units:
        if current:
            candidate = current + [unit]
            candidate_text = join_unit_text(candidate)
            duration = unit.end_ms - current[0].start_ms
            gap = unit.start_ms - current[-1].end_ms
            hard_break = (
                display_unit_count(candidate_text) > settings.max_display_units
                or duration > settings.max_duration_ms
                or gap >= settings.silence_gap_ms
            )
            if hard_break:
                cues.append(_make_cue(current))
                current = []
        current.append(unit)
        text = join_unit_text(current)
        if _ends_with(text, _SENTENCE_END):
            cues.append(_make_cue(current))
            current = []
        elif (
            _ends_with(text, _SOFT_END)
            and display_unit_count(text) >= max(6, settings.max_display_units // 2)
        ):
            cues.append(_make_cue(current))
            current = []
    if current:
        cues.append(_make_cue(current))
    cues = _merge_short(cues, settings)
    return normalize_timeline(cues, transcript.duration_ms)


def _merge_short(cues: List[SubtitleCue], settings: SubtitleSettings) -> List[SubtitleCue]:
    merged: List[SubtitleCue] = []
    for cue in cues:
        if merged and cue.end_ms - cue.start_ms < settings.target_min_duration_ms:
            previous = merged[-1]
            combined_text = (previous.text + " " + cue.text).strip()
            if (
                display_unit_count(combined_text) <= settings.max_display_units
                and cue.end_ms - previous.start_ms <= settings.max_duration_ms
            ):
                merged[-1] = SubtitleCue(previous.start_ms, cue.end_ms, combined_text)
                continue
        merged.append(cue)
    return merged


def normalize_timeline(cues: Sequence[SubtitleCue], duration_ms: int) -> Tuple[SubtitleCue, ...]:
    normalized: List[SubtitleCue] = []
    previous_end = 0
    for cue in cues:
        start = max(previous_end, min(duration_ms, cue.start_ms))
        end = max(start, min(duration_ms, cue.end_ms))
        if end == start and start < duration_ms:
            end = min(duration_ms, start + 1)
        text = cue.text.strip()
        if text and end >= start:
            normalized.append(SubtitleCue(start, end, text))
            previous_end = end
    return tuple(normalized)


def convert_traditional(
    cues: Sequence[SubtitleCue],
    converter: Callable[[str], str] = None,
) -> Tuple[SubtitleCue, ...]:
    if converter is None:
        try:
            from opencc import OpenCC
        except ImportError as exc:
            raise DependencyError(
                "Traditional Chinese output requires opencc-python-reimplemented"
            ) from exc
        converter = OpenCC("s2twp").convert
    return tuple(replace(cue, text=converter(cue.text)) for cue in cues)

