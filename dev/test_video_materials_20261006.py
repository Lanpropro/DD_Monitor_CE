"""Validate the local evidence used by the October 6 video material report."""
import json
import math
import subprocess
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "work/video-analysis-2026-10-06"


@unittest.skipUnless((ANALYSIS / "inventory.json").exists(), "Local video analysis is not present")
class VideoMaterialEvidenceTests(unittest.TestCase):
    def test_inventory_matches_recordings(self):
        records = json.loads((ANALYSIS / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual({r["file"] for r in records}, {
            "二路同播cs.mp4", "二路直播对齐.mp4", "双人精彩时刻.mp4", "海外平台apex.mp4"})
        for record in records:
            with self.subTest(file=record["file"]):
                source = ROOT / "Video_reference" / record["file"]
                self.assertEqual(source.stat().st_size, record["source_bytes"])
                actual = json.loads(subprocess.check_output([
                    "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)]))
                self.assertAlmostEqual(float(actual["format"]["duration"]), record["duration"], places=5)
                video = next(s for s in actual["streams"] if s["codec_type"] == "video")
                self.assertEqual((video["width"], video["height"], video["avg_frame_rate"]), (3840, 2160, "60/1"))
                audio = [s for s in actual["streams"] if s["codec_type"] == "audio"]
                self.assertEqual(len(audio), 6)
                self.assertEqual(len(record["audio_tracks"]), len(audio))
                for track in record["audio_tracks"]:
                    self.assertEqual(track["seconds_analyzed"], math.floor(record["duration"]))
                    self.assertEqual(track["peak"], 0.0)
                samples = record["samples"]
                self.assertEqual(len(samples), 12)
                self.assertEqual(samples, sorted(set(samples)))
                self.assertTrue(all(0 <= t < record["duration"] for t in samples))
                with Image.open(record["contact_sheet"]) as sheet:
                    self.assertEqual(sheet.size, (1920, 1208))
                    sheet.verify()

    def test_key_frame_evidence_is_readable(self):
        for name in ["alignment-controls-contact.jpg", "align-20-native.png",
                     "align-controls-16.jpg", "align-controls-24.jpg", "global-32.jpg",
                     "global-105.jpg", "dual-24.jpg"]:
            with self.subTest(image=name), Image.open(ANALYSIS / name) as image:
                image.verify()


if __name__ == "__main__":
    unittest.main()
