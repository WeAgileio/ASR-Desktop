"""Native-only output generation; leaves recognized wording intact."""

import re


def export_text(transcript, path):
    from opencc import OpenCC
    from asr_srt.files import atomic_write_text

    text = OpenCC("s2twp").convert(transcript.full_text).strip()
    paragraphs = []
    current = ""
    for sentence in re.split(r"(?<=[。！？])", text):
        current += sentence
        if len(current) >= 300:
            paragraphs.append(current.strip())
            current = ""
    if current.strip():
        paragraphs.append(current.strip())
    body = "\n\n".join(paragraphs)
    assert re.sub(r"\s", "", body) == re.sub(r"\s", "", text)
    atomic_write_text(path, "機器逐字稿（台灣繁體，未人工校訂）\n\n" + body + "\n")
