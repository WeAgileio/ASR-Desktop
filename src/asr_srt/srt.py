from pathlib import Path
from typing import Sequence

from .domain import SubtitleCue
from .errors import ValidationError
from .files import atomic_write_text


def format_timestamp(milliseconds: int) -> str:
    if milliseconds < 0:
        raise ValidationError("SRT timestamps cannot be negative")
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(cues: Sequence[SubtitleCue]) -> str:
    if not cues:
        raise ValidationError("No speech subtitles were produced")
    blocks = []
    previous_end = 0
    for index, cue in enumerate(cues, 1):
        if cue.start_ms < previous_end:
            raise ValidationError("Cannot render overlapping SRT cues")
        blocks.append(
            f"{index}\n{format_timestamp(cue.start_ms)} --> {format_timestamp(cue.end_ms)}\n"
            f"{cue.text.strip()}"
        )
        previous_end = cue.end_ms
    return "\n\n".join(blocks) + "\n"


def write_srt(path: Path, cues: Sequence[SubtitleCue], overwrite: bool = False) -> Path:
    atomic_write_text(Path(path), render_srt(cues), overwrite=overwrite)
    return Path(path)

