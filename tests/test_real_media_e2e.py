import hashlib
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asr_srt.config import JobConfig
from asr_srt.device import DeviceDecision
from asr_srt.workflow import LocalTranscriptionService
from tests.helpers import transcript


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RealMediaEndToEndTests(unittest.TestCase):
    def test_real_video_extraction_srt_parse_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "real media sample.mp4"
            subprocess.run(
                [
                    shutil.which("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:d=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                    "-shortest", "-c:v", "h264", "-c:a", "aac", str(video),
                ], check=True,
            )
            before = hashlib.sha256(video.read_bytes()).hexdigest()
            calls = []
            events = []
            class Adapter:
                def transcribe(self, request):
                    calls.append(request)
                    value = transcript(cache_key=request.cache_key, device=request.device)
                    return replace(
                        value, duration_ms=request.duration_ms,
                        metadata=replace(value.metadata, cache_key=request.cache_key, device=request.device),
                    )
            service = LocalTranscriptionService(
                adapter_factory=lambda name: Adapter(),
                progress=events.append,
                device_resolver=lambda requested: DeviceDecision(requested, "cpu", False),
            )
            result = service.run(JobConfig(
                video, model="paraformer", device="cpu", cache_dir=root / "cache",
                traditional=False,
            ))
            after = hashlib.sha256(video.read_bytes()).hexdigest()
            self.assertEqual(before, after)
            self.assertEqual(len(calls), 1)
            content = result.output_path.read_text(encoding="utf-8")
            self.assertRegex(content, r"(?m)^1$")
            self.assertRegex(content, r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}")
            self.assertTrue(result.transcript_path.exists())
            extraction = [e for e in events if e.phase == "audio-extraction"]
            self.assertTrue(any(e.progress_kind == "actual" and e.status == "running"
                                for e in extraction))
            self.assertEqual(extraction[-1].status, "completed")
            self.assertEqual(extraction[-1].fraction, 1.0)
            asr = [e for e in events if e.phase == "transcription" and e.status == "running"]
            self.assertTrue(asr)
            self.assertEqual(asr[0].progress_kind, "indeterminate")


if __name__ == "__main__":
    unittest.main()
