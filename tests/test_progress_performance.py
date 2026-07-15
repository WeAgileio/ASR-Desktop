import contextlib
import importlib.util
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from asr_srt.performance import PerformanceKey, PerformanceProfile
from asr_srt.progress import ProgressEvent
from asr_srt.progress_render import (
    NullProgressRenderer,
    PlainProgressRenderer,
    create_progress_renderer,
)


class ProgressPerformanceTests(unittest.TestCase):
    def test_event_validation_and_compatibility(self):
        legacy = ProgressEvent("phase", "message")
        self.assertEqual(legacy.status, "running")
        self.assertIsNone(legacy.fraction)
        measured = ProgressEvent(
            "phase", "working", progress_kind="actual", current=2, total=4, unit="seconds"
        )
        self.assertEqual(measured.fraction, 0.5)
        with self.assertRaises(ValueError):
            ProgressEvent("phase", "false finish", progress_kind="actual", current=4, total=4)
        completed = ProgressEvent(
            "phase", "done", status="completed", progress_kind="actual", current=4, total=4
        )
        self.assertTrue(completed.terminal)

    def test_performance_profile_sampling_estimates_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "performance.json"
            profile = PerformanceProfile(path)
            key = PerformanceKey("nano", "r1", "cpu", "runtime")
            other = PerformanceKey("nano", "r1", "mps", "runtime")
            self.assertFalse(profile.record(key, 5, 1))
            self.assertTrue(profile.record(key, 100, 20))
            self.assertIsNone(profile.estimate_seconds(key, 200))
            self.assertTrue(profile.record(key, 100, 30))
            self.assertEqual(profile.estimate_seconds(key, 200), 50)
            self.assertIsNone(profile.estimate_seconds(other, 200))
            path.write_text("not-json", encoding="utf-8")
            self.assertIsNone(profile.estimate_seconds(key, 200))
            self.assertTrue(profile.record(key, 100, 10))
            self.assertEqual(json.loads(path.read_text())["version"], 1)

    def test_plain_renderer_throttles_heartbeats_and_has_no_ansi(self):
        stream = io.StringIO()
        renderer = PlainProgressRenderer(stream, heartbeat_interval=0.05)
        renderer(ProgressEvent("asr", "working"))
        renderer(ProgressEvent("asr", "working"))
        time.sleep(0.08)
        renderer(ProgressEvent("asr", "done", status="completed"))
        renderer.close()
        output = stream.getvalue()
        self.assertNotIn("\x1b", output)
        self.assertIn("[asr] running", output)
        self.assertIn("[asr] completed", output)
        self.assertLessEqual(output.count("[asr]"), 3)

    def test_renderer_factory_auto_and_off(self):
        stream = io.StringIO()
        renderer = create_progress_renderer("auto", stream)
        self.assertIsInstance(renderer, PlainProgressRenderer)
        renderer.close()
        self.assertIsInstance(create_progress_renderer("off", stream), NullProgressRenderer)

    @unittest.skipUnless(importlib.util.find_spec("rich"), "Rich dependency not installed")
    def test_rich_renderer_uses_bounded_live_output(self):
        stream = io.StringIO()
        renderer = create_progress_renderer("rich", stream)
        renderer(ProgressEvent("transcription", "working"))
        renderer(ProgressEvent(
            "transcription", "done", status="completed",
            progress_kind="actual", current=10, total=10, unit="items",
        ))
        renderer.close()
        output = stream.getvalue()
        self.assertIn("transcription", output)
        self.assertIn("completed", output)
        self.assertLess(len(output), 20000)


if __name__ == "__main__":
    unittest.main()
