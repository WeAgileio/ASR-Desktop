from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from asr_srt.adapters.base import AdapterRequest, create_adapter
from asr_srt.adapters.whisper import LocalWhisperAdapter, timestamped_units
from asr_srt.config import JobConfig
from asr_srt.errors import ModelOutputError, ValidationError
from asr_srt.registry import registration
from asr_desktop.database import StateError
from asr_desktop.intake import settings
from asr_desktop.offline import local_adapter


class WhisperAdapterTests(unittest.TestCase):
    def request(self):
        return AdapterRequest(Path("audio.wav"), 5000, "中文", (), "cpu", "key")

    def test_real_timestamp_validation_and_empty_output(self):
        self.assertEqual(timestamped_units([], 5000), ())
        result = timestamped_units([("Hi", .02, 5.1)], 5000)
        self.assertEqual((result[0].start_ms, result[0].end_ms), (20, 5000))
        for start, end in ((None, 1), (0, None), (float("nan"), 1), (2, 1), (-1, 2), (6, 7)):
            with self.assertRaises(ModelOutputError):
                timestamped_units([("Hi", start, end)], 5000)

    def test_faster_whisper_uses_local_cpu_session_and_reports_segments(self):
        spec = registration("taiwan-tongues")
        calls, events = [], []
        class Engine:
            def transcribe(self, path, **kwargs):
                calls.append(kwargs)
                return iter([SimpleNamespace(text="你好 English", start=.1, end=1.5,
                    words=[SimpleNamespace(word="你好 English", start=.1, end=1.5)])]), None
        factory_calls = []
        def factory(**kwargs):
            factory_calls.append(kwargs)
            return Engine()
        adapter = LocalWhisperAdapter(spec, "/local/model", factory)
        with adapter.open_session("cpu") as session:
            for _ in range(2):
                result = session.transcribe(replace(self.request(), progress=events.append))
        self.assertEqual(len(factory_calls), 1)
        self.assertTrue(factory_calls[0]["local_files_only"])
        self.assertEqual(factory_calls[0]["device"], "cpu")
        self.assertEqual(calls[0]["language"], "zh")
        self.assertFalse(calls[0]["vad_filter"])
        self.assertEqual(result.units[0].end_ms, 1500)
        self.assertIn("English", result.full_text)
        self.assertEqual(events[-1].kind, "actual")

    def test_transformers_long_audio_input_and_timestamp_conversion(self):
        import numpy as np
        kwargs_seen = []
        def pipeline(audio, **kwargs):
            self.assertEqual(len(audio["raw"]), 16000 * 65)
            kwargs_seen.append(kwargs)
            return {"text": "Hello", "chunks": [{"text": "Hello", "timestamp": (30.1, 32.2)}]}
        adapter = LocalWhisperAdapter(registration("breeze-asr-25"), "/local/model", lambda **kw: pipeline)
        with patch("soundfile.read", return_value=(np.zeros(16000 * 65, dtype=np.float32), 16000)):
            result = adapter.transcribe(replace(self.request(), duration_ms=65000))
        self.assertEqual(result.units[0].start_ms, 30100)
        self.assertEqual(kwargs_seen[0]["return_timestamps"], "word")
        self.assertEqual(kwargs_seen[0]["generate_kwargs"]["task"], "transcribe")

    def test_new_model_validation_rejects_unsupported_options_before_execution(self):
        for model in ("taiwan-tongues", "breeze-asr-25"):
            JobConfig(Path("audio.wav"), model=model, device="cpu")
            for values in ({"device": "mps"}, {"hotwords": ("Hello",)}):
                with self.assertRaises(ValidationError):
                    JobConfig(Path("audio.wav"), model=model, **values)
            with self.assertRaises(StateError):
                settings({"model": model, "device": "gpu"})

    def test_compatible_model_uses_engine_without_model_name_branch(self):
        spec = registration("breeze-asr-25")
        spec["id"] = "my-fine-tune"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in spec["execution"]["required_files"]["breeze-asr-25"]:
                (root / filename).touch()
            adapter = local_adapter("my-fine-tune", {"breeze-asr-25": root}, {"breeze-asr-25": "a" * 40},
                                    definition=spec, model_factory=lambda **kwargs: None)
            self.assertEqual(adapter.model_id, "my-fine-tune")

    def test_legacy_compatible_model_dispatches_by_engine(self):
        spec = registration("paraformer")
        spec["id"] = "compatible-paraformer"
        adapter = create_adapter(spec["id"], lambda **kw: None, definition=spec)
        self.assertEqual(type(adapter).__name__, "ParaformerAdapter")

    def test_chunk_checkpoints_resume_and_merge_real_engine_timestamps(self):
        from asr_srt.longform import LongFormSettings, plan_chunks, merge_chunk_transcripts
        from asr_srt.longform_cache import LongFormIdentity, LongFormCheckpointStore, LongFormManifest
        from asr_srt.domain import SubtitleSettings
        from asr_srt.subtitle import segment_transcript
        from asr_srt.srt import render_srt
        import numpy as np
        plan = plan_chunks(4000, (), LongFormSettings(threshold_ms=1000, target_ms=2000,
            minimum_ms=1500, maximum_ms=2500, fallback_overlap_ms=0))
        for identifier in ("taiwan-tongues", "breeze-asr-25"):
            with self.subTest(model=identifier), tempfile.TemporaryDirectory() as directory:
                class Engine:
                    def transcribe(self, *args, **kwargs):
                        return iter([SimpleNamespace(text="測試。", start=.1, end=.8,
                            words=[SimpleNamespace(word="測試。", start=.1, end=.8)])]), None
                    def __call__(self, *args, **kwargs):
                        return {"text": "測試。", "chunks": [{"text": "測試。", "timestamp": (.1, .8)}]}
                adapter = LocalWhisperAdapter(registration(identifier), "/local", lambda **kw: Engine())
                identity = LongFormIdentity("source", "mono-v1", plan.identity, identifier,
                                           adapter.model_revision, "cpu", "中文", ())
                store = LongFormCheckpointStore(Path(directory))
                store.save_manifest(LongFormManifest(identity, plan.duration_ms, plan.chunks))
                with adapter.open_session("cpu") as session, patch("soundfile.read", return_value=(np.zeros(32000, dtype=np.float32), 16000)):
                    for chunk in plan.chunks:
                        transcript = session.transcribe(replace(self.request(), duration_ms=chunk.duration_ms))
                        store.save_checkpoint(identity, chunk, transcript)
                recovered = store.load_valid(identity, plan)
                self.assertEqual(len(recovered), 2)
                merged = merge_chunk_transcripts(plan, {key: value.transcript for key, value in recovered.items()}).transcript
                self.assertEqual([unit.start_ms for unit in merged.units], [100, 2100])
                self.assertIn("00:00:02,100", render_srt(segment_transcript(merged, SubtitleSettings(target_min_duration_ms=0))))

    def test_text_without_timestamps_is_rejected(self):
        import numpy as np
        adapter = LocalWhisperAdapter(registration("breeze-asr-25"), "/local",
                                     lambda **kw: lambda *args, **kwargs: {"text": "Hello", "chunks": []})
        with patch("soundfile.read", return_value=(np.zeros(16000, dtype=np.float32), 16000)):
            with self.assertRaises(ModelOutputError):
                adapter.transcribe(self.request())
