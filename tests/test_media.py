import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asr_srt.errors import DependencyError, MediaError, ValidationError
from asr_srt.media import (
    extract_audio, extract_audio_chunk, parse_ffmpeg_progress, probe_media, validate_source,
)


class MediaTests(unittest.TestCase):
    def test_missing_input(self):
        with self.assertRaises(ValidationError):
            validate_source(Path("/definitely/missing.mp4"))

    def test_probe_uses_argument_array_with_special_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "video name;safe.mp4"
            source.write_bytes(b"x")
            seen = {}
            def runner(command, **kwargs):
                seen["command"] = command
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout=json.dumps({"streams": [{"codec_name": "aac"}], "format": {"duration": "1.25"}}),
                    stderr="",
                )
            with patch("asr_srt.media.require_binary", return_value="/ffprobe"):
                info = probe_media(source, runner=runner)
            self.assertEqual(info.duration_ms, 1250)
            self.assertEqual(seen["command"][-1], str(source))
            self.assertIsInstance(seen["command"], list)

    def test_no_audio_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"x")
            runner = lambda command, **kwargs: subprocess.CompletedProcess(
                command, 0, stdout='{"streams":[],"format":{"duration":"1"}}', stderr=""
            )
            with patch("asr_srt.media.require_binary", return_value="/ffprobe"):
                with self.assertRaises(MediaError):
                    probe_media(source, runner=runner)

    def test_probe_allows_unknown_duration_for_indeterminate_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "video.mp4"
            source.write_bytes(b"x")
            runner = lambda command, **kwargs: subprocess.CompletedProcess(
                command, 0,
                stdout='{"streams":[{"codec_name":"aac"}],"format":{"duration":"N/A"}}',
                stderr="",
            )
            with patch("asr_srt.media.require_binary", return_value="/ffprobe"):
                info = probe_media(source, runner=runner)
            self.assertEqual(info.duration_ms, 0)

    def test_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "v.mp4"
            source.write_bytes(b"x")
            with patch("asr_srt.media.shutil.which", return_value=None):
                with self.assertRaises(DependencyError):
                    probe_media(source)

    def test_extract_success_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "v.mp4"
            destination = Path(tmp) / "cache" / "audio.wav"
            source.write_bytes(b"x")
            def success(command, **kwargs):
                Path(command[-1]).write_bytes(b"RIFFdata")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("asr_srt.media.require_binary", return_value="/ffmpeg"):
                extract_audio(source, destination, runner=success)
            self.assertEqual(destination.read_bytes(), b"RIFFdata")
            destination.unlink()
            def failure(command, **kwargs):
                Path(command[-1]).write_bytes(b"")
                return subprocess.CompletedProcess(command, 1, "", "bad")
            with patch("asr_srt.media.require_binary", return_value="/ffmpeg"):
                with self.assertRaises(MediaError):
                    extract_audio(source, destination, runner=failure)
            self.assertFalse(destination.exists())

    def test_extract_chunk_uses_validated_boundaries_and_cleans_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "audio.wav"; source.write_bytes(b"RIFF")
            destination = Path(tmp) / "chunks" / "0001.wav"
            seen = []
            def runner(command, **kwargs):
                seen.append(command)
                Path(command[-1]).write_bytes(b"RIFFchunk")
                return subprocess.CompletedProcess(command, 0, "", "")
            with patch("asr_srt.media.require_binary", return_value="/ffmpeg"):
                extract_audio_chunk(source, destination, 1500, 4500, runner)
            self.assertIn("1.500", seen[0])
            self.assertIn("3.000", seen[0])
            with self.assertRaises(ValidationError):
                extract_audio_chunk(source, destination, 5, 5, runner)

    def test_progress_parser_supports_units_clock_and_malformed_records(self):
        values = list(parse_ffmpeg_progress([
            "out_time_us=500000\n", "progress=continue\n",
            "not-a-record\n", "out_time=00:00:01.250000\n", "progress=continue\n",
            "out_time_ms=bad\n", "progress=continue\n",
        ]))
        self.assertEqual(values, [0.5, 1.25])

    def test_extract_progress_is_bounded_and_duration_can_be_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "v.mp4"; source.write_bytes(b"x")
            destination = Path(tmp) / "audio.wav"
            def runner(command, **kwargs):
                Path(command[-1]).write_bytes(b"RIFFdata")
                return subprocess.CompletedProcess(
                    command, 0,
                    "out_time_us=2000000\nprogress=continue\nout_time_us=9000000\nprogress=end\n",
                    "",
                )
            seen = []
            with patch("asr_srt.media.require_binary", return_value="/ffmpeg"):
                extract_audio(source, destination, runner=runner, duration_ms=4000,
                              progress=lambda current, total: seen.append((current, total)))
            self.assertTrue(seen)
            self.assertTrue(all(current < total for current, total in seen))
            destination.unlink()
            seen.clear()
            with patch("asr_srt.media.require_binary", return_value="/ffmpeg"):
                extract_audio(source, destination, runner=runner, duration_ms=None,
                              progress=lambda current, total: seen.append((current, total)))
            self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
