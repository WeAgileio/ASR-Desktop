"""Transcript text export shared by desktop and Drive entry points."""

import re
from .files import atomic_write_text


def convert_text(text, script="traditional"):
    if script == "original":
        return text
    from opencc import OpenCC
    if script not in ("traditional", "simplified"):
        raise ValueError("Unknown text script")
    return OpenCC("s2twp" if script == "traditional" else "t2s").convert(text)


def render_text(transcript, script="traditional"):
    text = convert_text(transcript.full_text, script).strip()
    paragraphs, current = [], ""
    for sentence in re.split(r"(?<=[。！？])", text):
        current += sentence
        if len(current) >= 300:
            paragraphs.append(current.strip())
            current = ""
    if current.strip():
        paragraphs.append(current.strip())
    body = "\n\n".join(paragraphs)
    assert re.sub(r"\s", "", body) == re.sub(r"\s", "", text)
    label = {"traditional": "台灣繁體", "simplified": "簡體", "original": "原文"}[script]
    return f"機器逐字稿（{label}，未人工校訂）\n\n" + body + "\n"


def export_text(transcript, path, script="traditional"):
    atomic_write_text(path, render_text(transcript, script))
