import unittest
import tempfile
from dataclasses import replace
from pathlib import Path

from asr_srt.errors import ValidationError
from asr_srt.longform import (
    AudioChunk, LongFormSettings, SilenceInterval, parse_silence_intervals,
    merge_chunk_transcripts, plan_chunks, validate_plan,
)
from asr_srt.domain import TextUnit, Transcript, TranscriptMetadata
from asr_srt.longform_cache import (
    LongFormCheckpointStore, LongFormIdentity, LongFormManifest,
)
from tests.helpers import transcript


class LongFormPlannerTests(unittest.TestCase):
    def test_parse_silence_intervals_clips_and_ignores_malformed(self):
        values = parse_silence_intervals([
            "noise", "silence_start: 10.0", "silence_end: 12.5",
            "silence_start: 19.0", "silence_end: bad",
        ], 20000)
        self.assertEqual(values, (SilenceInterval(10000, 12500), SilenceInterval(19000, 20000)))

    def test_two_hour_plan_prefers_nearby_silence_and_is_stable(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=1200000,
                                    minimum_ms=900000, maximum_ms=1800000,
                                    search_window_ms=60000)
        silences = tuple(SilenceInterval(point - 1000, point + 1000)
                         for point in (1210000, 2410000, 3610000, 4810000, 6010000))
        first = plan_chunks(7200000, silences, settings)
        second = plan_chunks(7200000, silences, settings)
        self.assertEqual(first, second)
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.chunks[0].end_ms, 1210000)
        self.assertEqual(first.chunks[-1].end_ms, 7200000)
        self.assertTrue(all(chunk.duration_ms <= settings.maximum_ms for chunk in first.chunks))

    def test_dense_speech_uses_bounded_overlap(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                    minimum_ms=1500, maximum_ms=3000,
                                    fallback_overlap_ms=100)
        plan = plan_chunks(7000, (), settings)
        self.assertEqual(plan.chunks[1].overlap_ms, 100)
        self.assertEqual(plan.chunks[1].start_ms, plan.chunks[0].end_ms - 100)

    def test_short_input_bypasses_chunking(self):
        plan = plan_chunks(1000, (), LongFormSettings(threshold_ms=2000,
                           target_ms=1000, minimum_ms=500, maximum_ms=1500,
                           fallback_overlap_ms=100))
        self.assertEqual(plan.chunks, (AudioChunk(0, 0, 1000),))

    def test_invalid_gap_and_settings_are_rejected(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                    minimum_ms=1500, maximum_ms=3000,
                                    fallback_overlap_ms=100)
        with self.assertRaises(ValidationError):
            validate_plan(5000, (AudioChunk(0, 0, 2000), AudioChunk(1, 2100, 5000)), settings)
        with self.assertRaises(ValidationError):
            LongFormSettings(target_ms=100, minimum_ms=200, maximum_ms=300)


if __name__ == "__main__":
    unittest.main()


class LongFormCheckpointTests(unittest.TestCase):
    def identity(self, plan, **changes):
        values = dict(source="source", preprocessing="mono-v1", plan=plan.identity,
                      model="nano", model_revision="r1", device="cpu",
                      language="中文", hotwords=("ASR",))
        values.update(changes)
        return LongFormIdentity(**values)

    def test_manifest_and_mixed_checkpoints_resume_independently(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                    minimum_ms=1500, maximum_ms=3000,
                                    fallback_overlap_ms=100)
        plan = plan_chunks(5000, (), settings)
        identity = self.identity(plan)
        with tempfile.TemporaryDirectory() as tmp:
            store = LongFormCheckpointStore(Path(tmp))
            store.save_manifest(LongFormManifest(identity, plan.duration_ms, plan.chunks))
            first = plan.chunks[0]
            value = replace(transcript(), duration_ms=first.duration_ms,
                            units=tuple(unit for unit in transcript().units
                                        if unit.end_ms <= first.duration_ms))
            store.save_checkpoint(identity, first, value)
            self.assertEqual(set(store.load_valid(identity, plan)), {0})
            store.checkpoint_path(1).parent.mkdir(parents=True, exist_ok=True)
            store.checkpoint_path(1).write_text("broken")
            self.assertEqual(set(store.load_valid(identity, plan)), {0})

    def test_identity_and_plan_changes_invalidate_without_touching_legacy_cache(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                    minimum_ms=1500, maximum_ms=3000,
                                    fallback_overlap_ms=100)
        plan = plan_chunks(5000, (), settings)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "transcript.json"
            legacy.write_text("legacy")
            store = LongFormCheckpointStore(root)
            identity = self.identity(plan)
            store.save_manifest(LongFormManifest(identity, plan.duration_ms, plan.chunks))
            self.assertIsNone(store.load_manifest(self.identity(plan, language="English"), plan))
            self.assertEqual(legacy.read_text(), "legacy")


class LongFormMergeTests(unittest.TestCase):
    def value(self, duration, units, device="cpu"):
        metadata = TranscriptMetadata("model", "r1", device, (), 1.0, "local")
        return Transcript("".join(unit.text for unit in units), duration, "中文",
                          tuple(units), metadata)

    def test_offsets_and_deduplicates_exact_overlap(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                    minimum_ms=1500, maximum_ms=3000,
                                    fallback_overlap_ms=500)
        plan = plan_chunks(4000, (), settings)
        first, second = plan.chunks
        values = {
            0: self.value(first.duration_ms, [TextUnit("你", 100, 300),
                                              TextUnit("好", 1700, 1950)]),
            1: self.value(second.duration_ms, [TextUnit("好", 100, 350),
                                               TextUnit("嗎", 500, 800)]),
        }
        result = merge_chunk_transcripts(plan, values, cache_key="global")
        self.assertEqual(result.transcript.full_text, "你好嗎")
        self.assertEqual(result.transcript.metadata.cache_key, "global")
        self.assertTrue(all(a.start_ms <= b.start_ms for a, b in zip(
            result.transcript.units, result.transcript.units[1:])))

    def test_ambiguous_overlap_is_preserved_and_diagnosed(self):
        settings = LongFormSettings(threshold_ms=1000, target_ms=2000,
                                    minimum_ms=1500, maximum_ms=3000,
                                    fallback_overlap_ms=500)
        plan = plan_chunks(4000, (), settings)
        first, second = plan.chunks
        values = {0: self.value(first.duration_ms, [TextUnit("甲", 1700, 2000)]),
                  1: self.value(second.duration_ms, [TextUnit("乙", 0, 400)])}
        result = merge_chunk_transcripts(plan, values)
        self.assertEqual(result.transcript.full_text, "甲乙")
        self.assertTrue(result.diagnostics)

    def test_rejects_missing_or_inconsistent_chunks(self):
        plan = plan_chunks(4000, (), LongFormSettings(threshold_ms=1000,
                           target_ms=2000, minimum_ms=1500, maximum_ms=3000,
                           fallback_overlap_ms=500))
        with self.assertRaises(ValidationError):
            merge_chunk_transcripts(plan, {})
