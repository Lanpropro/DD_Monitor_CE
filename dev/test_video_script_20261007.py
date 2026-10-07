"""Check the promo script's timing budget and local source references."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/VIDEO-SCRIPT-2026-10-07.md"


class VideoScriptTests(unittest.TestCase):
    def test_timeline_has_no_gaps_or_overlaps_and_finishes_at_sixty(self):
        text = SCRIPT.read_text(encoding="utf-8")
        spans = re.findall(r"^\| (\d{2})–(\d{2}) \|", text, re.MULTILINE)
        self.assertTrue(spans, "No storyboard timing rows found")
        previous_end = 0
        for start, end in spans:
            start, end = int(start), int(end)
            self.assertEqual(start, previous_end)
            self.assertGreater(end, start)
            previous_end = end
        self.assertEqual(previous_end, 60)

    def test_named_local_recordings_exist(self):
        text = SCRIPT.read_text(encoding="utf-8")
        references = set(re.findall(r"`(Video_reference/[^`]+\.mp4)`", text))
        self.assertTrue(references, "No source recordings referenced")
        for relative in references:
            with self.subTest(source=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertGreater((ROOT / relative).stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
