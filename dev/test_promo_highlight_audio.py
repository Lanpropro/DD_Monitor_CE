"""Check actual replay alignment, restored channel identity and preview placement."""
import array
import json
import math
import subprocess
import unittest
from pathlib import Path
from dev.test_plugins_promo_sample import Elements, probe

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "videos/dd-monitor-ce-plugins-promo"
SYNC = json.loads((PROJECT / "highlight-sync.json").read_text(encoding="utf-8"))


def correlation(a, b):
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    aa, bb = [x-ma for x in a], [x-mb for x in b]
    return sum(x*y for x,y in zip(aa,bb))/math.sqrt(
        sum(x*x for x in aa)*sum(y*y for y in bb))


def frame(source, time, crop):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(source),
        "-frames:v", "1", "-vf", crop+
        "scale=320:180,crop=125:55:100:65,format=gray", "-f", "rawvideo", "-"])


def pcm(source):
    samples = array.array("f")
    samples.frombytes(subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(source), "-vn", "-ar", "48000",
        "-f", "f32le", "-"]))
    return samples


class HighlightAudioTests(unittest.TestCase):
    def test_machine_audio_is_advanced_and_csboy_keeps_its_original_offset(self):
        self.assertEqual(SYNC["machine"]["audio_advance_seconds"], .1)
        self.assertEqual(SYNC["csboy"]["audio_advance_seconds"], 0)
        for speaker in ("machine", "csboy"):
            source = SYNC[speaker]
            expected = array.array("f")
            expected.frombytes(subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss",
                str(source["start"]+source["audio_advance_seconds"]),
                "-i", str(ROOT / source["source"]), "-t", "1",
                "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]))
            actual = pcm(ROOT / f"work/highlight-sync/{speaker}-aligned.wav")
            with self.subTest(speaker=speaker):
                self.assertGreater(correlation(expected[2048:46000],
                                               actual[2048:46000]), .999)

    def test_replays_match_gameplay_at_multiple_points_without_stretching(self):
        self.assertFalse(SYNC["alignment"]["time_stretch"])
        for time in (0, 3, 6, 10):
            reference = frame(ROOT / SYNC["picture_source"], 120+time,
                              "crop=2556:1438:372:132,")
            for speaker in ("machine", "csboy"):
                with self.subTest(time=time, speaker=speaker):
                    source = SYNC[speaker]
                    # Match within the documented one-frame uncertainty.
                    candidates = [frame(ROOT / source["source"],
                                        source["start"]+time+delta, "")
                                  for delta in (-1/30, 0, 1/30)]
                    self.assertGreater(max(correlation(reference, c) for c in candidates), .65)
            picture = frame(PROJECT / SYNC["picture_asset"], time,
                            "crop=1278:718:186:66,")
            self.assertGreater(correlation(reference, picture), .95)

    def test_default_preview_has_twelve_seconds_and_real_stereo_audio(self):
        metadata = probe(PROJECT / SYNC["preview"], "-show_format", "-show_streams")
        self.assertAlmostEqual(float(metadata["format"]["duration"]), 12, delta=.04)
        video, audio = metadata["streams"]
        self.assertEqual((video["width"], video["height"], int(video["nb_frames"])),
                         (1920, 1080, 360))
        self.assertEqual(video["r_frame_rate"], "30/1")
        self.assertEqual(audio["channels"], 2)
        self.assertEqual(int(audio["sample_rate"]), 48000)
        mixed = pcm(PROJECT / SYNC["audio_asset"])
        encoded = pcm(PROJECT / SYNC["preview"])
        end = min(len(mixed), len(encoded)) - 8192
        for channel in (0, 1):
            self.assertGreater(correlation(mixed[8192+channel:end:2],
                                           encoded[8192+channel:end:2]), .99)
        for channel in (mixed[0::2], mixed[1::2]):
            self.assertGreater(math.sqrt(sum(x*x for x in channel)/len(channel)), .01)
            self.assertLess(max(abs(x) for x in channel), .51)
        # Verify channel routing against separately extracted original commentary.
        voices = [pcm(ROOT / f"work/highlight-sync/{name}-aligned.wav")
                  for name in ("machine", "csboy")]
        self.assertEqual(len(mixed), 12*48000*2)
        for i in range(0, 12*48000, 103):
            m, c = voices[0][i]*.5, voices[1][i]*.5
            self.assertAlmostEqual(mixed[2*i], .8*m+.2*c, delta=.0001)
            self.assertAlmostEqual(mixed[2*i+1], .2*m+.8*c, delta=.0001)

    def test_preview_picture_audio_timing_and_music_duck_match(self):
        tags = Elements(PROJECT / "index.html").tags
        host = next(a for _,a in tags if a.get("id") == "audition")
        voice = next(a for tag,a in tags if tag == "audio" and a["id"] == "highlight-commentary")
        self.assertEqual(host["data-start"], voice["data-start"])
        self.assertEqual(float(host["data-duration"]), 12)
        self.assertEqual(host["data-duration"], voice["data-duration"])
        self.assertEqual(voice["src"], SYNC["audio_asset"])
        music = next(a for tag,a in tags if tag == "audio" and a["id"] == "music")
        points = json.loads(music["data-automation"])["lanes"][0]["points"]
        self.assertIn({"t": 41.515, "v": .08}, points)
        self.assertIn({"t": 53.515, "v": .08}, points)
        self.assertFalse(any(a["v"] == b["v"] == 0 for a,b in zip(points,points[1:])))
        self.assertAlmostEqual(float(music["data-duration"]), 64.424)
        motion = json.loads((PROJECT / "index.motion.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(motion["duration"], 64.424)
        ending = next(a for a in motion["assertions"]
                      if a["kind"] == "appearsBy" and a["selector"] == "#ending-group")
        self.assertAlmostEqual(ending["bySec"], 62.424)
        scene = (PROJECT / "compositions/audition.html").read_text(encoding="utf-8")
        self.assertNotIn("待替换", scene)
        self.assertNotIn("当前只有配乐", scene)


if __name__ == "__main__":
    unittest.main()
