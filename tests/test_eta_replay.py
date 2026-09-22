import json
import unittest
from pathlib import Path
from statistics import median

from asr_srt.performance import EtaEstimator


class EtaReplayTests(unittest.TestCase):
    def test_representative_trace_median_absolute_percentage_error(self):
        fixture = Path(__file__).parent / "fixtures" / "eta_traces.json"
        traces = json.loads(fixture.read_text(encoding="utf-8"))
        initial_errors = []
        checkpoint_errors = []
        for trace in traces:
            prior = median(trace["historical_rtfs"])
            estimator = EtaEstimator(trace["duration_seconds"], prior)
            actual_total = trace["final_processing_seconds"]
            initial_errors.append(abs(estimator.initial_eta_seconds - actual_total) / actual_total)

            checkpoint = trace["checkpoint"]
            estimator.recalibrate(
                checkpoint["committed_seconds"], checkpoint["processing_seconds"]
            )
            estimated_remaining = estimator.remaining_seconds(
                checkpoint["committed_seconds"], smooth=False
            )
            actual_remaining = actual_total - checkpoint["processing_seconds"]
            checkpoint_errors.append(
                abs(estimated_remaining - actual_remaining) / actual_remaining
            )

            self.assertIn(trace["workload_unit"], {"milliseconds", "items", "segments"})
            self.assertTrue(trace["chunk_boundaries_seconds"])
            self.assertTrue(trace["segment_fractions"])
            self.assertIsInstance(checkpoint["resumed"], bool)

        self.assertLessEqual(median(initial_errors), 0.20)
        self.assertLessEqual(median(checkpoint_errors), 0.20)


if __name__ == "__main__":
    unittest.main()
