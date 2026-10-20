import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asr_desktop.database import DEFAULTS, StateError
from asr_desktop.exports import Delivery
from asr_srt.domain import TextUnit, Transcript, TranscriptMetadata


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        source = self.root / "audio.wav"
        source.write_bytes(b"source")
        self.job = {"id": "job-test", "source": str(source), "output_dir": str(self.root / "output"),
                    "settings": dict(DEFAULTS), "outputs": {fmt: str(self.root / "output" / ("audio." + fmt)) for fmt in ("txt", "srt", "json")}}
        self.transcript = Transcript("软件 API 字幕。", 2000, "中文", (TextUnit("软件 API 字幕。", 0, 2000),),
                                     TranscriptMetadata("test", "rev", "cpu"))

    def tearDown(self):
        self.temp.cleanup()

    def test_all_formats_and_original_transcript_preserved(self):
        original = self.transcript.to_json()
        ledger = Delivery(self.job, self.root).publish(self.transcript)
        self.assertEqual(len(ledger["files"]), 3)
        self.assertIn("軟體 API 字幕", Path(self.job["outputs"]["txt"]).read_text())
        self.assertIn("00:00:00,000 --> 00:00:02,000", Path(self.job["outputs"]["srt"]).read_text())
        self.assertEqual(Path(self.job["outputs"]["json"]).read_text(), original)
        self.assertEqual(self.transcript.to_json(), original)
        Delivery(self.job, self.root).publish(self.transcript)

    def test_existing_files_and_source_are_protected(self):
        target = Path(self.job["outputs"]["txt"])
        target.parent.mkdir()
        target.write_text("user content")
        with self.assertRaises(StateError):
            Delivery(self.job, self.root).preflight()
        self.assertEqual(target.read_text(), "user content")
        self.job["outputs"]["txt"] = self.job["source"]
        self.job["settings"]["overwrite"] = True
        with self.assertRaises(StateError):
            Delivery(self.job, self.root).preflight()
        self.assertEqual(Path(self.job["source"]).read_bytes(), b"source")

    def test_disk_full_during_second_output_reuses_first(self):
        link = os.link
        calls = []
        def interrupted(source, target):
            calls.append(str(target))
            if len(calls) == 2:
                raise OSError(errno.ENOSPC, "disk full")
            return link(source, target)
        with patch("asr_desktop.exports.os.link", side_effect=interrupted), self.assertRaises(OSError):
            Delivery(self.job, self.root).publish(self.transcript)
        first = Path(self.job["outputs"]["txt"])
        timestamp = first.stat().st_mtime_ns
        Delivery(self.job, self.root).publish(self.transcript)
        self.assertEqual(first.stat().st_mtime_ns, timestamp)
        self.assertTrue(all(Path(p).is_file() for p in self.job["outputs"].values()))

    def test_published_intent_survives_crash_before_commit_marker(self):
        delivery = Delivery(self.job, self.root)
        from asr_desktop import exports
        write = exports.atomic_json
        def interrupted(path, value):
            if any(v.get("state") == "committed" for v in value["files"].values()):
                raise OSError("crash after publish")
            write(path, value)
        with patch("asr_desktop.exports.atomic_json", side_effect=interrupted), self.assertRaises(OSError):
            delivery.publish(self.transcript)
        ledger = json.loads(delivery.ledger_path.read_text())
        self.assertEqual(ledger["files"]["txt"]["state"], "prepared")
        Delivery(self.job, self.root).publish(self.transcript)


if __name__ == "__main__":
    unittest.main()
