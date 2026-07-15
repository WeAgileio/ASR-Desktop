import tempfile
import unittest
from pathlib import Path

from asr_srt.adapters.base import AdapterRequest, create_adapter
from asr_srt.adapters.nano import FunAsrNanoAdapter
from asr_srt.adapters.paraformer import ParaformerAdapter
from asr_srt.device import resolve_device
from asr_srt.errors import MPSCompatibilityError, ModelOutputError, ValidationError


class FakeModel:
    model_path = "/models/revision-1"
    def __init__(self, result):
        self.result = result
        self.generate_kwargs = None
    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return self.result


class AdapterDeviceTests(unittest.TestCase):
    def request(self):
        return AdapterRequest(Path("audio.wav"), 5000, "中文", ("OpenAI",), "cpu", "key")

    def test_registry(self):
        self.assertIsInstance(create_adapter("fun-asr-nano", lambda **kw: None), FunAsrNanoAdapter)
        self.assertIsInstance(create_adapter("paraformer", lambda **kw: None), ParaformerAdapter)
        with self.assertRaises(ValidationError):
            create_adapter("other")

    def test_nano_normalizes_character_timestamps_and_hotwords(self):
        model = FakeModel([{"text": "你好 OpenAI", "timestamps": [[0, 200], [200, 400], ["OpenAI", 500, 1000]]}])
        created = {}
        def factory(**kwargs):
            created.update(kwargs)
            return model
        adapter = FunAsrNanoAdapter(factory)
        result = adapter.transcribe(self.request())
        self.assertEqual([u.text for u in result.units], ["你", "好", "OpenAI"])
        self.assertEqual(model.generate_kwargs["hotwords"], ["OpenAI"])
        self.assertTrue(model.generate_kwargs["disable_pbar"])
        self.assertIn("progress_callback", model.generate_kwargs)
        self.assertTrue(created["disable_pbar"])
        self.assertEqual(result.metadata.cache_key, "key")

    def test_existing_model_cache_is_preferred(self):
        from asr_srt.adapters.local_models import resolve_model_reference
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "hub/models/FunAudioLLM/Fun-ASR-Nano-2512"
            model.mkdir(parents=True)
            (model / "model.pt").write_bytes(b"model")
            (model / "config.yaml").write_text("model: test")
            from unittest.mock import patch
            with patch.dict("os.environ", {"MODELSCOPE_CACHE": tmp}):
                self.assertEqual(
                    resolve_model_reference("FunAudioLLM/Fun-ASR-Nano-2512"), str(model)
                )

    def test_paraformer_mixed_text_and_hotword_format(self):
        model = FakeModel([{"text": "你好 FunASR！", "timestamp": [["你", 0, 200], ["好", 200, 400], ["FunASR", 500, 1000], ["！", 1000, 1050]]}])
        created = {}
        def factory(**kwargs):
            created.update(kwargs)
            return model
        adapter = ParaformerAdapter(factory)
        result = adapter.transcribe(self.request())
        self.assertIn("FunASR", [u.text for u in result.units])
        self.assertEqual(model.generate_kwargs["hotword"], "OpenAI")
        self.assertTrue(model.generate_kwargs["disable_pbar"])
        self.assertTrue(created["disable_pbar"])

    def test_malformed_output(self):
        adapter = FunAsrNanoAdapter(lambda **kwargs: FakeModel([{"text": "text"}]))
        with self.assertRaises(ModelOutputError):
            adapter.transcribe(self.request())

    def test_nano_ctc_timestamp_shape(self):
        model = FakeModel([{
            "text": "开饭时间",
            "ctc_text": "开饭时间",
            "ctc_timestamps": [
                {"token": "开", "start_time": 0.78, "end_time": 0.84, "score": 0.9},
                {"token": "饭", "start_time": 1.08, "end_time": 1.14, "score": 0.8},
            ],
        }])
        result = FunAsrNanoAdapter(lambda **kwargs: model).transcribe(self.request())
        self.assertEqual(result.units[0].start_ms, 780)
        self.assertEqual(result.units[1].text, "饭")

    def test_device_resolution(self):
        self.assertEqual(resolve_device("auto", lambda: True).resolved, "mps")
        self.assertTrue(resolve_device("auto", lambda: True).fallback_allowed)
        self.assertEqual(resolve_device("auto", lambda: False).resolved, "cpu")
        self.assertEqual(resolve_device("cpu", lambda: True).resolved, "cpu")
        with self.assertRaises(MPSCompatibilityError):
            resolve_device("mps", lambda: False)


if __name__ == "__main__":
    unittest.main()
