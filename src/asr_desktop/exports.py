"""Per-file atomic delivery with a durable intent/checksum ledger."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile

from asr_srt.domain import SubtitleSettings
from asr_srt.srt import render_srt
from asr_srt.subtitle import segment_transcript
from asr_srt.text import convert_text, render_text

from .database import StateError
from .models import atomic_json, digest_file


class Delivery:
    def __init__(self, job, workspace):
        self.job = job
        self.root = Path(workspace) / "jobs" / job["id"]
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ledger_path = self.root / "outputs.json"
        try:
            self.ledger = json.loads(self.ledger_path.read_text())
        except FileNotFoundError:
            self.ledger = {"job_id": job["id"], "files": {}}
        if self.ledger.get("job_id") != job["id"]:
            raise StateError("output_conflict", "Output ledger belongs to another job")

    def validate_target(self, target):
        source = Path(self.job["source"])
        root = Path(self.job["output_dir"])
        if root.resolve() != root or not target.resolve().is_relative_to(root):
            raise StateError("output_unavailable", "Output directory changed or resolves outside the accepted root")
        if target.resolve() == source.resolve() or (target.exists() and os.path.samefile(source, target)):
            raise StateError("source_output_overlap", "An output would replace the source media")
        if target.is_symlink():
            raise StateError("output_conflict", "Output path is a symlink")

    def owned(self, fmt, target):
        record = self.ledger["files"].get(fmt)
        return (record and record.get("path") == str(target) and target.is_file()
                and digest_file(target) == record.get("sha256"))

    def preflight(self):
        for fmt, value in self.job["outputs"].items():
            target = Path(value)
            self.validate_target(target)
            if target.exists() and not self.owned(fmt, target) and not self.job["settings"]["overwrite"]:
                raise StateError("output_conflict", "Output already exists; choose another destination or explicitly overwrite", path=str(target))

    def publish(self, transcript, cancel_check=lambda: None):
        options = self.job["settings"]
        subtitle = SubtitleSettings(max_display_units=options["max_chars"], max_duration_ms=options["max_duration_ms"],
                                    target_min_duration_ms=min(1000, options["max_duration_ms"]))
        cues = segment_transcript(transcript, subtitle)
        cues = tuple(replace(cue, text=convert_text(cue.text, options["script"])) for cue in cues)
        bodies = {"txt": lambda: render_text(transcript, options["script"]),
                  "srt": lambda: render_srt(cues), "json": transcript.to_json}
        self.preflight()
        for fmt, value in self.job["outputs"].items():
            cancel_check()
            target = Path(value)
            self.validate_target(target)
            if self.owned(fmt, target):
                self.ledger["files"][fmt]["state"] = "committed"
                atomic_json(self.ledger_path, self.ledger)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = bodies[fmt]().encode("utf-8")
            descriptor, temporary = tempfile.mkstemp(prefix=f".asr-{self.job['id']}-", suffix=".tmp", dir=target.parent)
            temporary = Path(temporary)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                self.ledger["files"][fmt] = {"path": str(target), "sha256": hashlib.sha256(payload).hexdigest(),
                                              "size": len(payload), "state": "prepared"}
                atomic_json(self.ledger_path, self.ledger)
                cancel_check()
                self.validate_target(target)
                if options["overwrite"]:
                    os.replace(temporary, target)
                else:
                    try:
                        os.link(temporary, target)
                    except FileExistsError:
                        raise StateError("output_conflict", "Output appeared during delivery", path=str(target))
                    temporary.unlink()
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                self.ledger["files"][fmt]["state"] = "committed"
                atomic_json(self.ledger_path, self.ledger)
            finally:
                temporary.unlink(missing_ok=True)
        if not all(self.owned(fmt, Path(path)) for fmt, path in self.job["outputs"].items()):
            raise StateError("output_incomplete", "Not all requested outputs passed verification")
        return self.ledger
