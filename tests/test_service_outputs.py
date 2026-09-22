import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from opencc import OpenCC
from asr_service.outputs import export_text


class ServiceOutputTest(unittest.TestCase):
    def test_text_preserves_traditional_wording_and_marks_unreviewed(self):
        text = "软件项目的规划。OpenAI 2026 的讨论！真的吗？" * 30
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.txt"
            export_text(SimpleNamespace(full_text=text), path)
            result = path.read_text()
            self.assertIn("未人工校訂", result.splitlines()[0])
            self.assertEqual(
                re.sub(r"\s", "", result.split("\n\n", 1)[1]),
                re.sub(r"\s", "", OpenCC("s2twp").convert(text)),
            )
            self.assertIn("\n\n", result.split("\n\n", 1)[1])
