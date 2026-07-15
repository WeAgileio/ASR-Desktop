import tempfile
import unittest
from pathlib import Path

from asr_srt.cache import TranscriptCache, cache_identity, content_fingerprint
from asr_srt.domain import SubtitleCue, SubtitleSettings, TextUnit, Transcript, TranscriptMetadata
from asr_srt.srt import format_timestamp, render_srt, write_srt
from asr_srt.subtitle import convert_traditional, display_unit_count, segment_transcript
from tests.helpers import transcript


class CacheSubtitleSrtTests(unittest.TestCase):
    def test_fingerprint_identity_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "v.mp4"
            media.write_bytes(b"media")
            fp = content_fingerprint(media)
            key = cache_identity(fp, "paraformer", "r1", "中文", ("x",))
            key2 = cache_identity(fp, "paraformer", "r1", "中文", ("y",))
            self.assertNotEqual(key, key2)
            cache = TranscriptCache(Path(tmp) / "cache")
            item = transcript(cache_key=key)
            cache.save(key, item)
            self.assertEqual(cache.load(key), item)
            cache.paths(key).transcript.write_text("broken")
            self.assertIsNone(cache.load(key))

    def test_segmentation_punctuation_mixed_text_and_determinism(self):
        value = transcript()
        settings = SubtitleSettings()
        first = segment_transcript(value, settings)
        second = segment_transcript(value, settings)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertIn("FunASR", first[0].text)
        self.assertNotIn("F u n", first[0].text)
        self.assertLessEqual(display_unit_count(first[0].text), 22)

    def test_oversize_overlap_and_duration_clamping(self):
        units = tuple(TextUnit(str(i), i * 100, i * 100 + 150) for i in range(25))
        value = Transcript("".join(str(i) for i in range(25)), 2700, "中文", units,
                           TranscriptMetadata("m", "r", "cpu"))
        cues = segment_transcript(value, SubtitleSettings(max_display_units=5))
        self.assertGreater(len(cues), 1)
        for previous, current in zip(cues, cues[1:]):
            self.assertLessEqual(previous.end_ms, current.start_ms)
        self.assertLessEqual(cues[-1].end_ms, 2700)

    def test_empty_transcript_and_conversion(self):
        empty = Transcript("", 1000, "中文", (), TranscriptMetadata("m", "r", "cpu"))
        self.assertEqual(segment_transcript(empty, SubtitleSettings()), ())
        cues = (SubtitleCue(0, 1000, "这是 OpenAI"),)
        converted = convert_traditional(cues, converter=lambda text: text.replace("这是", "這是"))
        self.assertEqual(converted[0].text, "這是 OpenAI")

    def test_srt_render_and_write(self):
        cues = (SubtitleCue(0, 1250, "你好"), SubtitleCue(1300, 3661001, "End"))
        output = render_srt(cues)
        self.assertIn("00:00:00,000 --> 00:00:01,250", output)
        self.assertIn("01:01:01,001", output)
        self.assertTrue(output.endswith("\n"))
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "v.srt"
            write_srt(target, cues)
            self.assertEqual(target.read_text(), output)


if __name__ == "__main__":
    unittest.main()
