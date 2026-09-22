import contextlib
import importlib.util
import io
import json
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from asr_srt.performance import (
    EtaEstimator, LongFormPerformanceKey, LongFormPerformanceProfile, PerformanceKey,
    PerformanceProfile, PerformanceSpan, StageRecorder, duration_band, resource_snapshot,
    tuning_eligible,
)
from asr_srt.progress import ProgressEvent
from asr_srt.progress_render import (
    NullProgressRenderer,
    PlainProgressRenderer,
    create_progress_renderer,
    _snapshot,
)


class ProgressPerformanceTests(unittest.TestCase):
    def test_stage_metrics_accounting_and_resource_fallbacks(self):
        recorder = StageRecorder()
        recorder.record("model-load", 1.25)
        with recorder.measure("asr-inference"):
            pass
        self.assertEqual(recorder.spans[0], PerformanceSpan("model-load", 1.25))
        self.assertGreaterEqual(recorder.spans[1].seconds, 0)
        snapshot = resource_snapshot()
        self.assertGreaterEqual(snapshot.peak_rss_mb, 0)
        self.assertIsNone(snapshot.memory_pressure)
        self.assertIsNone(snapshot.swap_used_mb)

    def test_stage_recorder_records_failed_span_without_masking_error(self):
        recorder = StageRecorder()
        with self.assertRaisesRegex(RuntimeError, "boom"):
            with recorder.measure("failed-stage"):
                raise RuntimeError("boom")
        self.assertEqual(recorder.spans[0].name, "failed-stage")

    def test_long_form_evidence_requires_comparable_safe_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = LongFormPerformanceProfile(Path(tmp) / "long-form.json")
            base = ("nano", "r1", "runtime")
            cpu = LongFormPerformanceKey(*base, "cpu", "over-60m", 1)
            mps = LongFormPerformanceKey(*base, "mps", "over-60m", 1)
            profile.record(cpu, rtf=.4, peak_rss_mb=6000)
            profile.record(cpu, rtf=.5, peak_rss_mb=6100)
            self.assertIsNone(profile.choose_device(cpu, mps))
            profile.record(mps, rtf=.8, peak_rss_mb=6200)
            profile.record(mps, rtf=.7, peak_rss_mb=6200)
            self.assertEqual(profile.choose_device(cpu, mps), "cpu")
            self.assertIsNone(profile.choose_device(cpu, mps, max_peak_rss_mb=5000))
            unsafe = LongFormPerformanceKey(*base, "mps", "10m-60m", 1)
            profile.record(unsafe, rtf=.1, peak_rss_mb=1000, swap_grew=True)
            profile.record(unsafe, rtf=.1, peak_rss_mb=1000, swap_grew=True)
            self.assertIsNone(profile.eligible_rtf(unsafe))
            self.assertEqual(duration_band(7200), "over-60m")
            eligible, reasons = tuning_eligible(
                baseline_rtf=.5, candidate_rtf=.3, peak_rss_mb=6000,
                max_peak_rss_mb=7000,
            )
            self.assertTrue(eligible)
            rejected, reasons = tuning_eligible(
                baseline_rtf=.5, candidate_rtf=.2, peak_rss_mb=8000,
                max_peak_rss_mb=7000, swap_grew=True,
            )
            self.assertFalse(rejected)
            self.assertIn("swap increased", reasons)

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

    def test_snapshot_never_interprets_workload_units_as_eta_seconds(self):
        for unit, current, total in (("milliseconds", 1_000, 10_000), ("items", 1, 10), ("segments", 2, 20)):
            event = ProgressEvent(
                "asr", "working", progress_kind="estimated",
                current=current, total=total, unit=unit,
            )
            with mock.patch("asr_srt.progress_render.time.monotonic", return_value=105):
                _, rendered_current, eta = _snapshot(event, 100)
            self.assertEqual(rendered_current, current)
            self.assertIsNone(eta)

    def test_snapshot_preserves_explicit_eta_and_counts_down_only_wall_time(self):
        event = ProgressEvent(
            "asr", "working", progress_kind="estimated",
            current=1_000, total=10_000, unit="milliseconds", eta_seconds=90,
        )
        with mock.patch("asr_srt.progress_render.time.monotonic", return_value=105):
            elapsed, current, eta = _snapshot(event, 100)
        self.assertEqual((elapsed, current, eta), (5, 1_000, 85))
        completed = ProgressEvent(
            "asr", "done", status="completed", progress_kind="actual",
            current=10, total=10, unit="items", elapsed_seconds=12, eta_seconds=0,
        )
        self.assertEqual(_snapshot(completed, 0), (12, 10, 0))
        invalid = ProgressEvent("asr", "working", eta_seconds=float("inf"))
        self.assertIsNone(_snapshot(invalid, time.monotonic())[2])

    def test_time_based_estimated_progress_advances_without_fabricating_eta(self):
        event = ProgressEvent(
            "asr", "working", progress_kind="estimated",
            current=10, total=100, unit="seconds",
        )
        with mock.patch("asr_srt.progress_render.time.monotonic", return_value=105):
            _, current, eta = _snapshot(event, 100)
        self.assertEqual(current, 15)
        self.assertIsNone(eta)

    def test_eta_estimator_uses_robust_history_and_bounded_smoothing(self):
        estimator = EtaEstimator(1_000, historical_rtf=0.5)
        self.assertEqual(estimator.initial_eta_seconds, 500)
        first = estimator.remaining_seconds(1)
        later = estimator.remaining_seconds(900)
        self.assertGreater(first, 400)
        self.assertGreaterEqual(later, first * 0.75)
        recalibrated = estimator.recalibrate(500, 400)
        self.assertAlmostEqual(recalibrated, 0.65)
        self.assertAlmostEqual(estimator.remaining_seconds(500, smooth=False), 325)
        self.assertGreater(estimator.remaining_seconds(999.99, smooth=False), 0)

    def test_eta_estimator_rejects_invalid_or_insufficient_evidence(self):
        for value in (None, 0, -1, float("inf"), float("nan")):
            estimator = EtaEstimator(100, value)
            self.assertIsNone(estimator.initial_eta_seconds)
            self.assertIsNone(estimator.remaining_seconds(10))

    def test_eta_estimator_allows_honest_checkpoint_increase_without_early_zero(self):
        estimator = EtaEstimator(100, 0.2)
        before = estimator.remaining_seconds(50, smooth=False)
        estimator.recalibrate(50, 40)
        after = estimator.remaining_seconds(50, smooth=False)
        self.assertGreater(after, before)
        self.assertGreater(estimator.remaining_seconds(99.999, smooth=False), 0)

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

    def test_plain_renderer_shows_explicit_eta_and_omits_missing_eta(self):
        stream = io.StringIO()
        renderer = PlainProgressRenderer(stream, heartbeat_interval=60)
        renderer(ProgressEvent(
            "asr", "with estimate", progress_kind="estimated",
            current=1, total=10, unit="segments", eta_seconds=90,
        ))
        renderer(ProgressEvent(
            "asr", "done", status="completed", progress_kind="actual",
            current=10, total=10, unit="segments", elapsed_seconds=10,
        ))
        renderer.close()
        lines = stream.getvalue().splitlines()
        self.assertIn("ETA 01:30", lines[0])
        self.assertNotIn("ETA", lines[-1])

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

    @unittest.skipUnless(importlib.util.find_spec("rich"), "Rich dependency not installed")
    def test_rich_renderer_uses_explicit_eta_and_missing_fallback(self):
        stream = io.StringIO()
        renderer = create_progress_renderer("rich", stream)
        renderer(ProgressEvent(
            "asr", "with estimate", progress_kind="estimated",
            current=1, total=10, unit="segments", eta_seconds=90,
        ))
        renderer(ProgressEvent(
            "other", "without estimate", progress_kind="estimated",
            current=1_000, total=10_000, unit="milliseconds",
        ))
        renderer.close()
        output = stream.getvalue()
        self.assertIn("01:30", output)
        self.assertIn("other", output)
        self.assertIn("-", output)


if __name__ == "__main__":
    unittest.main()
