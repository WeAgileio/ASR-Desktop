import math
import unittest

from asr_srt.adapters.base import AdapterProgress
from asr_srt.adapters.segment_progress import (
    SegmentWorkLedger,
    observe_funasr_segments,
    result_count,
    supports_segment_observation,
)


class AdapterProgressContractTests(unittest.TestCase):
    def test_defaults_preserve_batch_local_contract(self):
        value = AdapterProgress(1, 2)
        self.assertEqual((value.scope, value.kind, value.epoch), ("batch", "actual", 0))

    def test_whole_input_segment_measurement_is_estimated(self):
        value = AdapterProgress(500, 1000, "milliseconds", "whole-input", "estimated", 3)
        self.assertEqual(value.kind, "estimated")
        self.assertEqual(value.epoch, 3)

    def test_invalid_measurements_are_rejected(self):
        invalid = [
            (math.nan, 1, "items", "batch", "actual", 0),
            (0, 0, "items", "batch", "actual", 0),
            (2, 1, "items", "batch", "actual", 0),
            (0, 1, "items", "job", "actual", 0),
            (0, 1, "items", "batch", "guessed", 0),
            (0, 1, "items", "batch", "actual", -1),
        ]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises(ValueError):
                AdapterProgress(*args)


class SegmentWorkLedgerTests(unittest.TestCase):
    def test_sorts_and_weights_unequal_segments(self):
        ledger = SegmentWorkLedger.from_vad_result([
            {"value": [[0, 30000], [40000, 42000], [50000, 60000]]}
        ])
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.durations_ms, (2000.0, 10000.0, 30000.0))
        first = ledger.complete(1)
        second = ledger.complete(1)
        final = ledger.complete(1)
        self.assertEqual(first.current, 2000)
        self.assertEqual(second.current, 12000)
        self.assertEqual(final.current, 39900)
        self.assertEqual(final.total, 42000)
        self.assertLess(final.current, final.total)

    def test_invalid_vad_results_disable_estimates(self):
        invalid = [None, [], [{"value": []}], [{"value": [[1, 1]]}],
                   [{"value": [[-1, 2]]}], [{"value": [[0, math.inf]]}],
                   [{"value": [[0, 1]]}, {"value": [[0, 1]]}]]
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(SegmentWorkLedger.from_vad_result(value))

    def test_bad_completion_disables_without_raising(self):
        ledger = SegmentWorkLedger.from_vad_result([{"value": [[0, 10]]}])
        self.assertIsNone(ledger.complete(2))
        self.assertFalse(ledger.enabled)
        self.assertIsNone(ledger.complete(1))

    def test_result_count_accepts_only_nonempty_result_lists(self):
        self.assertEqual(result_count([{"text": "a"}, {"text": "b"}]), 2)
        self.assertEqual(result_count(([{"text": "a"}], {"rtf": 1})), 1)
        self.assertIsNone(result_count([]))
        self.assertIsNone(result_count({"text": "a"}))


class FakeObservedModel:
    def __init__(self, fail=False, malformed=False):
        self.vad_model = object()
        self.model = object()
        self.fail = fail
        self.malformed = malformed
        self.calls = []

    def inference_with_vad(self):
        return None

    def inference(self, payload, *, model):
        self.calls.append((payload, model))
        if model is self.vad_model:
            if self.malformed:
                return [{"value": [[0, 0]]}]
            return [{"value": [[0, 1000], [2000, 5000], [6000, 8000]]}]
        if self.fail:
            raise RuntimeError("inference failed")
        return [{"text": str(item)} for item in payload]


class SegmentObservationBridgeTests(unittest.TestCase):
    def test_observes_pass_through_calls_and_restores_method(self):
        model = FakeObservedModel()
        original = model.inference
        seen = []
        with observe_funasr_segments(model, seen.append, epoch=4) as active:
            self.assertTrue(active)
            vad = model.inference("audio", model=model.vad_model)
            first = model.inference(["short"], model=model.model)
            second = model.inference(["medium", "long"], model=model.model)
        self.assertEqual(vad[0]["value"][0], [0, 1000])
        self.assertEqual([item["text"] for item in first + second], ["short", "medium", "long"])
        self.assertEqual([value.current for value in seen], [1000, 5700])
        self.assertTrue(all(value.total == 6000 for value in seen))
        self.assertTrue(all(value.epoch == 4 for value in seen))
        self.assertEqual(model.inference, original)

    def test_restores_after_inference_failure_and_repeated_use(self):
        model = FakeObservedModel(fail=True)
        original = model.inference
        with self.assertRaises(RuntimeError):
            with observe_funasr_segments(model, lambda value: None):
                model.inference("audio", model=model.vad_model)
                model.inference(["segment"], model=model.model)
        self.assertEqual(model.inference, original)
        model.fail = False
        with observe_funasr_segments(model, lambda value: None):
            model.inference("audio", model=model.vad_model)
            model.inference(["segment"], model=model.model)
        self.assertEqual(model.inference, original)

    def test_unsupported_or_malformed_shapes_fall_back(self):
        self.assertFalse(supports_segment_observation(object()))
        with observe_funasr_segments(object(), lambda value: None) as active:
            self.assertFalse(active)
        model = FakeObservedModel(malformed=True)
        seen = []
        with observe_funasr_segments(model, seen.append):
            model.inference("audio", model=model.vad_model)
            result = model.inference(["still transcribed"], model=model.model)
        self.assertEqual(result, [{"text": "still transcribed"}])
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
