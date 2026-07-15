import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asr_srt.domain import TextUnit, Transcript
from asr_srt.errors import OutputExistsError, ValidationError
from asr_srt.files import atomic_write_text
from tests.helpers import transcript


class DomainFilesTests(unittest.TestCase):
    def test_round_trip_is_stable(self):
        original = transcript()
        serialized = original.to_json()
        self.assertEqual(Transcript.from_json(serialized), original)
        self.assertEqual(Transcript.from_json(serialized).to_json(), serialized)

    def test_rejects_schema_and_invalid_timestamps(self):
        data = transcript().to_dict()
        data["schema_version"] = 99
        with self.assertRaises(ValidationError):
            Transcript.from_dict(data)
        with self.assertRaises(ValidationError):
            TextUnit("x", -1, 2)
        data = transcript().to_dict()
        data["units"][0]["end_ms"] = 9000
        with self.assertRaises(ValidationError):
            Transcript.from_dict(data)

    def test_atomic_write_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            atomic_write_text(target, "first", overwrite=False)
            self.assertEqual(target.read_text(), "first")
            with self.assertRaises(OutputExistsError):
                atomic_write_text(target, "second", overwrite=False)
            self.assertEqual(target.read_text(), "first")
            atomic_write_text(target, "second", overwrite=True)
            self.assertEqual(target.read_text(), "second")

    def test_failed_replace_does_not_replace_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.txt"
            target.write_text("safe")
            with patch("asr_srt.files.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "unsafe")
            self.assertEqual(target.read_text(), "safe")
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

