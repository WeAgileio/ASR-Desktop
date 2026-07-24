import contextlib
import io
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asr_srt.cli import main
from asr_srt.adapters.base import AdapterProgress
from asr_srt.config import JobConfig
from asr_srt.longform import LongFormSettings
from asr_srt.device import DeviceDecision
from asr_srt.domain import TranscriptMetadata
from asr_srt.errors import MPSCompatibilityError
from asr_srt.media import MediaInfo
from asr_srt.performance import PerformanceKey, PerformanceProfile, runtime_identity
from asr_srt.workflow import JobResult, LocalTranscriptionService
from tests.helpers import transcript


class StubAdapter:
    def __init__(self, calls, fail_mps=False):
        self.calls = calls
        self.fail_mps = fail_mps
    def transcribe(self, request):
        self.calls.append(request)
        if self.fail_mps and request.device == "mps":
            raise MPSCompatibilityError("MPS op unsupported")
        value = transcript(cache_key=request.cache_key, device=request.device)
        return replace(value, duration_ms=request.duration_ms,
                       metadata=replace(value.metadata, cache_key=request.cache_key, device=request.device))


class WorkflowCliTests(unittest.TestCase):
    def test_long_form_checkpoints_resume_and_reuse_one_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "video.mp4"; source.write_bytes(b"x")
            class LongAdapter:
                model_id = "long-model"; model_revision = "r1"; progress_scope = "batch"
                def __init__(self, fail_after=None):
                    self.fail_after, self.calls, self.loads = fail_after, [], 0
                @contextlib.contextmanager
                def open_session(inner, device, stage_callback=None):
                    inner.loads += 1
                    class Session:
                        def transcribe(_, request):
                            inner.calls.append(request.audio_path.name)
                            if inner.fail_after is not None and len(inner.calls) > inner.fail_after:
                                raise RuntimeError("interrupted")
                            base = transcript(cache_key=request.cache_key, device=device)
                            units = tuple(unit for unit in base.units if unit.end_ms <= request.duration_ms)
                            return replace(base, duration_ms=request.duration_ms, units=units,
                                           metadata=replace(base.metadata, model_id="long-model",
                                                            model_revision="r1", device=device,
                                                            cache_key=request.cache_key))
                    yield Session()
            settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                        minimum_ms=1500, maximum_ms=3000,
                                        fallback_overlap_ms=100)
            config = JobConfig(source, cache_dir=root / "cache", output_path=root / "out.srt",
                               overwrite=True, traditional=False, long_form=settings)
            def fake_extract(src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF"); return dest
            def fake_chunk(src, dest, start, end):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF"); return dest
            failing = LongAdapter(fail_after=1)
            service = LocalTranscriptionService(
                adapter_factory=lambda name: failing,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            patches = (patch("asr_srt.workflow.probe_media", return_value=MediaInfo(5000, "aac")),
                       patch("asr_srt.workflow.extract_audio", side_effect=fake_extract),
                       patch("asr_srt.workflow.detect_silence", return_value=()),
                       patch("asr_srt.workflow.extract_audio_chunk", side_effect=fake_chunk))
            with patches[0], patches[1], patches[2], patches[3]:
                with self.assertRaises(Exception):
                    service.run(config)
            self.assertEqual(failing.loads, 1)
            succeeding = LongAdapter()
            service = LocalTranscriptionService(
                adapter_factory=lambda name: succeeding,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(5000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract), \
                 patch("asr_srt.workflow.detect_silence", return_value=()), \
                 patch("asr_srt.workflow.extract_audio_chunk", side_effect=fake_chunk):
                result = service.run(config)
            self.assertEqual(succeeding.loads, 1)
            self.assertEqual(len(succeeding.calls), 2)
            self.assertEqual(result.transcript.duration_ms, 5000)
            result.transcript_path.unlink()
            checkpoint_only = LongAdapter()
            service = LocalTranscriptionService(
                adapter_factory=lambda name: checkpoint_only,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(5000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract), \
                 patch("asr_srt.workflow.detect_silence", return_value=()), \
                 patch("asr_srt.workflow.extract_audio_chunk", side_effect=fake_chunk):
                service.run(config)
            self.assertEqual(checkpoint_only.loads, 0)
    def run_service(self, tmp, model="paraformer", subtitle_override=None, fail_mps=False):
        source = Path(tmp) / "video sample.mp4"
        source.write_bytes(b"video-content")
        calls = []
        events = []
        service = LocalTranscriptionService(
            adapter_factory=lambda name: StubAdapter(calls, fail_mps),
            progress=events.append,
            device_resolver=lambda requested: DeviceDecision(requested, "mps", True),
        )
        config = JobConfig(
            source, model=model, cache_dir=Path(tmp) / "cache",
            output_path=Path(tmp) / "result.srt", traditional=False,
            overwrite=True,
        )
        if subtitle_override:
            config = replace(config, subtitle=subtitle_override)
        fake_media = MediaInfo(4000, "aac")
        def fake_extract(src, dest, **kwargs):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"RIFF")
            if kwargs.get("progress"):
                kwargs["progress"](2.0, 4.0)
            return dest
        with patch("asr_srt.workflow.probe_media", return_value=fake_media), \
             patch("asr_srt.workflow.extract_audio", side_effect=fake_extract):
            first = service.run(config)
            second = service.run(config)
        return first, second, calls, events, config

    def test_cache_skips_asr_and_subtitle_settings_do_not_change_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second, calls, events, config = self.run_service(tmp)
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertEqual(len(calls), 1)
            self.assertTrue(first.output_path.exists())
            self.assertTrue(first.transcript_path.exists())
            cache_events = events[len(events) // 2:]
            self.assertTrue(any(e.phase == "audio-extraction" and e.status == "skipped" for e in cache_events))
            self.assertTrue(any(e.phase == "transcription" and e.status == "skipped" for e in cache_events))

    def test_auto_mps_falls_back_to_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, _, calls, events, _ = self.run_service(tmp, fail_mps=True)
            self.assertEqual([call.device for call in calls], ["mps", "cpu"])
            self.assertEqual(first.transcript.metadata.device, "cpu")
            self.assertTrue(any("CPU" in event.message for event in events))

    def test_model_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second, calls, events, config = self.run_service(tmp, model="paraformer")
            # Separate service invocation with same cache but another model.
            source = config.input_path
            more_calls = []
            service = LocalTranscriptionService(
                adapter_factory=lambda name: StubAdapter(more_calls),
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            changed = replace(config, model="fun-asr-nano")
            def fake_extract(src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF"); return dest
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(4000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract):
                result = service.run(changed)
            self.assertFalse(result.cache_hit)
            self.assertEqual(len(more_calls), 1)

    def test_cli_integration_for_models_output_and_error(self):
        class CliService:
            def __init__(self): self.configs = []
            def run(self, config):
                self.configs.append(config)
                output = config.resolved_output_path
                output.write_text("1\n00:00:00,000 --> 00:00:01,000\n測試\n")
                return JobResult(output, Path("cache.json"), transcript(), (), False)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "v.mp4"; source.write_bytes(b"x")
            service = CliService()
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main([str(source), "--model", "fun-asr-nano", "--device", "cpu",
                             "--hotword", "OpenAI,FunASR", "--no-traditional"], service=service)
            self.assertEqual(code, 0)
            self.assertEqual(service.configs[0].model, "fun-asr-nano")
            self.assertEqual(service.configs[0].hotwords, ("OpenAI", "FunASR"))
            self.assertIn("SRT:", stdout.getvalue())

        class FailingService:
            def run(self, config): raise OSError("failure")
        with contextlib.redirect_stderr(io.StringIO()) as error:
            code = main(["missing.mp4", "--model", "paraformer"], service=FailingService())
        self.assertEqual(code, 1)
        self.assertIn("failure", error.getvalue())

    def test_phase_order_actual_progress_and_single_terminals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "video.mp4"; source.write_bytes(b"x")
            events = []
            class GlobalAdapter(StubAdapter):
                model_id = "global-model"
                model_revision = "r1"
                progress_scope = "global"
                def transcribe(self, request):
                    request.progress(type("P", (), {
                        "current": 2, "total": 4, "unit": "chunks", "scope": "global"
                    })())
                    return super().transcribe(request)
            calls = []
            service = LocalTranscriptionService(
                adapter_factory=lambda name: GlobalAdapter(calls), progress=events.append,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            def fake_extract(src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF")
                kwargs["progress"](1, 4)
                return dest
            config = JobConfig(source, model="paraformer", cache_dir=root / "cache",
                               output_path=root / "out.srt", overwrite=True, traditional=False)
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(4000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract):
                service.run(config)
            running_order = [e.phase for e in events if e.status == "running"]
            expected = ["validation", "audio-extraction", "model-preparation",
                        "transcription", "subtitle-generation", "output-writing"]
            self.assertEqual(list(dict.fromkeys(running_order)), expected)
            for phase in expected:
                terminals = [e for e in events if e.phase == phase and e.terminal]
                self.assertEqual(len(terminals), 1, phase)
            self.assertTrue(any(e.phase == "audio-extraction" and e.progress_kind == "actual"
                                for e in events))
            self.assertTrue(any(e.phase == "transcription" and e.progress_kind == "actual"
                                and e.status == "running" for e in events))

    def test_failure_emits_one_failed_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "video.mp4"; source.write_bytes(b"x")
            events = []
            service = LocalTranscriptionService(
                adapter_factory=lambda name: StubAdapter([]), progress=events.append,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(4000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=OSError("disk failed")):
                with self.assertRaises(Exception):
                    service.run(JobConfig(source, cache_dir=root / "cache"))
            failed = [e for e in events if e.phase == "audio-extraction" and e.status == "failed"]
            self.assertEqual(len(failed), 1)

    def test_compatible_rtf_history_starts_estimated_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "video.mp4"; source.write_bytes(b"x")
            adapter = StubAdapter([])
            adapter.model_id = "estimate-model"; adapter.model_revision = "r1"
            key = PerformanceKey("estimate-model", "r1", "cpu", runtime_identity())
            profile = PerformanceProfile(root / "cache" / "performance.json")
            profile.record(key, 100, 20); profile.record(key, 100, 20)
            events = []
            service = LocalTranscriptionService(
                adapter_factory=lambda name: adapter, progress=events.append,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            def fake_extract(src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF"); return dest
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(40000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract):
                service.run(JobConfig(source, model="paraformer", cache_dir=root / "cache",
                                      output_path=root / "out.srt", overwrite=True, traditional=False))
            estimated = [e for e in events if e.phase == "transcription"
                         and e.status == "running" and e.progress_kind == "estimated"]
            self.assertTrue(estimated)
            self.assertLess(estimated[0].current, estimated[0].total)

    def test_segment_progress_is_duration_weighted_estimated_and_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "video.mp4"; source.write_bytes(b"x")
            events = []
            class SegmentAdapter(StubAdapter):
                model_id = "segment-model"
                model_revision = "r1"
                def transcribe(self, request):
                    request.progress(AdapterProgress(
                        1000, 10000, "milliseconds", "whole-input", "estimated", 0
                    ))
                    request.progress(AdapterProgress(
                        5000, 10000, "milliseconds", "whole-input", "estimated", 0
                    ))
                    # A changed total in the same epoch is ignored by the workflow.
                    request.progress(AdapterProgress(
                        6000, 12000, "milliseconds", "whole-input", "estimated", 0
                    ))
                    return super().transcribe(request)
            service = LocalTranscriptionService(
                adapter_factory=lambda name: SegmentAdapter([]), progress=events.append,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            def fake_extract(src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF"); return dest
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(10000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract):
                service.run(JobConfig(source, cache_dir=root / "cache",
                                      output_path=root / "out.srt", overwrite=True,
                                      traditional=False))
            running = [e for e in events if e.phase == "transcription"
                       and e.status == "running" and e.current]
            self.assertEqual([e.current for e in running], [1000, 5000])
            self.assertTrue(all(e.total == 10000 for e in running))
            self.assertTrue(all(e.progress_kind == "estimated" for e in running))
            terminal = [e for e in events if e.phase == "transcription"
                        and e.status == "completed"]
            self.assertEqual(terminal[-1].current, terminal[-1].total)

    def test_mps_retry_restarts_segment_progress_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "video.mp4"; source.write_bytes(b"x")
            events = []
            class RetryAdapter(StubAdapter):
                model_id = "retry-model"
                model_revision = "r1"
                def transcribe(self, request):
                    if request.device == "mps":
                        request.progress(AdapterProgress(
                            2850, 3000, "milliseconds", "whole-input", "estimated",
                            request.progress_epoch,
                        ))
                        raise MPSCompatibilityError("MPS op unsupported")
                    request.progress(AdapterProgress(
                        950, 1000, "milliseconds", "whole-input", "estimated",
                        request.progress_epoch,
                    ))
                    return super().transcribe(request)
            service = LocalTranscriptionService(
                adapter_factory=lambda name: RetryAdapter([]), progress=events.append,
                device_resolver=lambda requested: DeviceDecision(requested, "mps", True),
            )
            def fake_extract(src, dest, **kwargs):
                dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(b"RIFF"); return dest
            with patch("asr_srt.workflow.probe_media", return_value=MediaInfo(4000, "aac")), \
                 patch("asr_srt.workflow.extract_audio", side_effect=fake_extract):
                service.run(JobConfig(source, cache_dir=root / "cache",
                                      output_path=root / "out.srt", overwrite=True,
                                      traditional=False))
            measured = [e for e in events if e.phase == "transcription"
                        and e.status == "running" and e.current]
            self.assertEqual([(e.current, e.total) for e in measured], [(2850, 3000), (950, 1000)])
            self.assertTrue(any("restarting transcription estimate on CPU" in e.message
                                for e in events))

    def test_cli_progress_off_is_silent(self):
        class CliService:
            def run(self, config):
                output = config.resolved_output_path
                output.write_text("1\n00:00:00,000 --> 00:00:01,000\n測試\n")
                return JobResult(output, Path("cache.json"), transcript(), (), False)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "v.mp4"; source.write_bytes(b"x")
            with contextlib.redirect_stderr(io.StringIO()) as stderr, \
                 contextlib.redirect_stdout(io.StringIO()):
                code = main([str(source), "--progress", "off"], service=CliService())
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
