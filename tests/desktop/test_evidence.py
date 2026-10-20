import copy
import unittest

from asr_srt.evidence import eligible, identity_key, select
from asr_srt.device import looks_like_mps_error, resolve_device


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.identity = {"policy_version": 1, "hardware": "test-Mac", "ram_bytes": 32 * 1024**3,
                         "os": "test-os", "python": "3.11", "packages": {k: "pinned" for k in ("funasr", "torch", "torchaudio", "transformers", "modelscope", "tiktoken")},
                         "snapshot": "immutable", "recognition": {"language": "中文", "hotwords": []},
                         "loading": "cold-per-file", "planner": "v1", "duration_band": "short", "runtime_distributions": {"runtime": "pinned"}}
        self.sample = {"state": "completed", "cache_hit": False, "resumed": False, "fallback": False,
                       "duration_seconds": 60, "cost_seconds": 10, "quality_ok": True, "timestamps_ok": True,
                       "source_sha256": "same-input", "resources": {"peak_rss_bytes": 100 * 1024**2,
                        "observations": [{"seconds": 0, "pressure": "normal", "swap_bytes": 0},
                                         {"seconds": 5, "pressure": "normal", "swap_bytes": 0}],
                        "policy_version": 1, "sources": {"rss": "getrusage.RUSAGE_SELF.ru_maxrss.darwin_bytes",
                            "pressure": "sysctl.kern.memorystatus_vm_pressure_level.dispatch_flags", "swap": "psutil.swap_memory.used"}}}

    def samples(self, gpu_seconds=8):
        return [{**copy.deepcopy(self.sample), "device": device, "cost_seconds": cost}
                for device, cost in (("cpu", 10), ("mps", gpu_seconds)) for _ in range(3)]

    def test_requires_three_matched_samples_and_ten_percent(self):
        self.assertEqual(select(self.identity, [])['device'], "cpu")
        self.assertEqual(select(self.identity, self.samples()[:5])["device"], "cpu")
        self.assertEqual(select(self.identity, self.samples())["device"], "mps")
        self.assertEqual(select(self.identity, self.samples(9))["device"], "mps")
        self.assertEqual(select(self.identity, self.samples(9.01))["device"], "cpu")
        self.assertEqual(select(self.identity, self.samples(), True)["device"], "cpu")

    def test_cache_resume_failed_cancelled_short_unknown_quality_are_excluded(self):
        for changes in ({"cache_hit": True}, {"resumed": True}, {"state": "failed"}, {"state": "cancelled"},
                        {"duration_seconds": 29}, {"quality_ok": False}, {"timestamps_ok": False}, {"cost_seconds": float("nan")}, {"fallback": True}):
            self.assertFalse(eligible({**self.sample, **changes}, self.identity["ram_bytes"]), changes)

    def test_resource_unknown_background_pressure_and_sustained_swap_fail(self):
        for change in ({"peak_rss_bytes": None}, {"peak_rss_bytes": self.identity["ram_bytes"] * .71}, {"observations": []}):
            value = copy.deepcopy(self.sample)
            value["resources"].update(change)
            self.assertFalse(eligible(value, self.identity["ram_bytes"]))
        for pressure in (None, "warning", "critical"):
            value = copy.deepcopy(self.sample)
            value["resources"]["observations"][1]["pressure"] = pressure
            self.assertFalse(eligible(value, self.identity["ram_bytes"]))
        value = copy.deepcopy(self.sample)
        observations = value["resources"]["observations"]
        observations[1]["swap_bytes"] = 65 * 1024**2
        observations.append({"seconds": 10, "pressure": "normal", "swap_bytes": 65 * 1024**2})
        self.assertFalse(eligible(value, self.identity["ram_bytes"]))

    def test_identity_changes_and_unmatched_inputs_do_not_mix(self):
        for key, value in (("hardware", "another"), ("ram_bytes", 16 * 1024**3), ("os", "new"),
                           ("snapshot", "new"), ("duration_band", "long"), ("loading", "warm")):
            self.assertNotEqual(identity_key(self.identity), identity_key({**self.identity, key: value}))
        legacy = {"hardware": "old"}
        self.assertEqual(select(legacy, self.samples())["reason"], "incomplete_profile_identity")
        samples = self.samples()
        for sample in samples[3:]:
            sample["source_sha256"] = "different-input"
        self.assertEqual(select(self.identity, samples)["device"], "cpu")

    def test_explicit_and_error_classification_are_conservative(self):
        self.assertEqual(resolve_device("cpu", lambda: True).resolved, "cpu")
        self.assertEqual(resolve_device("mps", lambda: True).resolved, "mps")
        self.assertEqual(resolve_device("auto", lambda: True).reason, "insufficient_evidence")
        self.assertFalse(looks_like_mps_error(OSError("disk full: metal.mp4")))
        self.assertFalse(looks_like_mps_error(RuntimeError("unknown failure")))
        self.assertTrue(looks_like_mps_error(RuntimeError("operator not implemented for the MPS device")))


if __name__ == "__main__":
    unittest.main()
