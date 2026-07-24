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


class ObservedFakeModel(FakeModel):
    def __init__(self, result):
        super().__init__(result)
        self.vad_model = object()
        self.model = object()
        self.inference_calls = []

    def inference_with_vad(self):
        return None

    def inference(self, payload, *, model):
        self.inference_calls.append((payload, model))
        if model is self.vad_model:
            return [{"value": [[0, 1000], [2000, 5000]]}]
        return [{"text": str(value)} for value in payload]

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        self.inference("audio", model=self.vad_model)
        self.inference(["short"], model=self.model)
        self.inference(["long"], model=self.model)
        callback = kwargs.get("progress_callback")
        if callback:
            callback(1, 1)
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

    def test_segment_observation_preserves_adapter_results_and_arguments(self):
        cases = (
            (FunAsrNanoAdapter, [{"text": "你好", "timestamps": [[0, 200], [200, 400]]}]),
            (ParaformerAdapter, [{"text": "你好", "timestamp": [["你", 0, 200], ["好", 200, 400]]}]),
        )
        for adapter_type, raw in cases:
            with self.subTest(adapter=adapter_type.__name__):
                without_model = ObservedFakeModel(raw)
                with_model = ObservedFakeModel(raw)
                without = adapter_type(lambda **kwargs: without_model).transcribe(self.request())
                seen = []
                with_progress = adapter_type(lambda **kwargs: with_model).transcribe(
                    AdapterRequest(
                        Path("audio.wav"), 5000, "中文", ("OpenAI",), "cpu", "key",
                        seen.append,
                    )
                )
                self.assertEqual(with_progress.full_text, without.full_text)
                self.assertEqual(with_progress.units, without.units)
                self.assertEqual(with_progress.metadata.cache_key, without.metadata.cache_key)
                without_args = {k: v for k, v in without_model.generate_kwargs.items()
                                if k != "progress_callback"}
                with_args = {k: v for k, v in with_model.generate_kwargs.items()
                             if k != "progress_callback"}
                self.assertEqual(with_args, without_args)
                segment = [value for value in seen if value.scope == "whole-input"]
                batch = [value for value in seen if value.scope == "batch"]
                self.assertEqual([value.current for value in segment], [1000, 3800])
                self.assertTrue(all(value.kind == "estimated" for value in segment))
                self.assertEqual(len(batch), 1)

    def test_model_session_reuses_one_model_and_single_call_remains_compatible(self):
        raw = [{"text": "你好", "timestamps": [[0, 200], [200, 400]]}]
        created = []
        def factory(**kwargs):
            created.append(kwargs)
            return FakeModel(raw)
        adapter = FunAsrNanoAdapter(factory)
        with adapter.open_session("cpu") as session:
            first = session.transcribe(self.request())
            second = session.transcribe(self.request())
        self.assertEqual(len(created), 1)
        self.assertEqual(first.units, second.units)
        adapter.transcribe(self.request())
        self.assertEqual(len(created), 2)

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

    def test_nano_ignores_whitespace_timestamp_tokens(self):
        model = FakeModel([{
            "text": "你好",
            "timestamps": [
                ["你", 0, 200],
                [" ", 200, 250],
                ["好", 250, 450],
            ],
        }])
        result = FunAsrNanoAdapter(lambda **kwargs: model).transcribe(self.request())
        self.assertEqual([unit.text for unit in result.units], ["你", "好"])

    def test_device_resolution(self):
        self.assertEqual(resolve_device("auto", lambda: True).resolved, "mps")
        self.assertTrue(resolve_device("auto", lambda: True).fallback_allowed)
        self.assertEqual(resolve_device("auto", lambda: False).resolved, "cpu")
        self.assertEqual(resolve_device("cpu", lambda: True).resolved, "cpu")
        with self.assertRaises(MPSCompatibilityError):
            resolve_device("mps", lambda: False)


if __name__ == "__main__":
    unittest.main()
