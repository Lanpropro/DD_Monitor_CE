"""Check preserved Studio copy and continuity in the revised delivery."""
import array
import json
import subprocess
import unittest
from dev import test_promo_first_cut as first_cut
from dev.test_plugins_promo_sample import PROJECT, Elements


class TransitionRevisionTests(first_cut.FirstCutTests):
    render = PROJECT / "renders/dd-monitor-ce-plugins-promo-first-cut-v5.mp4"

    def test_user_copy_remains_editable_without_timeline_replacement(self):
        expected = {
            "intro": "红队绿队一起看。",
            "domestic": "为您的观看如“虎”添翼",
            "global": "海外的直播也一样",
            "alignment": "自动对齐优先，必要时手动微调。",
            "result": "不同直播间，弹幕一起看。",
            "audition": "我觉得同时有玩🐷和🐴总听的才是观赛goat。",
            "updates": "让每次观看，都更随心应手。",
        }
        for scene, text in expected.items():
            source = (PROJECT / f"compositions/{scene}.html").read_text(encoding="utf-8")
            with self.subTest(scene=scene):
                self.assertIn(text, "".join(first_cut.Copy(PROJECT / f"compositions/{scene}.html").text))
                if scene == "alignment":
                    self.assertNotIn("textContent:", source)
        alignment = (PROJECT / "compositions/alignment.html").read_text(encoding="utf-8")
        self.assertNotIn('id="alignment-method"', alignment)

    def test_bridge_continues_previous_source_without_duplicate_audio(self):
        root = {a.get("id"): a for _, a in Elements(PROJECT / "index.html").tags}
        bridge = root["highlight-bridge-video"]
        result = next(a for tag, a in Elements(PROJECT / "compositions/result.html").tags
                      if tag == "video")
        self.assertEqual(bridge["src"], result["src"])
        self.assertIn("muted", bridge)
        self.assertAlmostEqual(float(bridge["data-media-start"]),
                               float(result["data-media-start"]) +
                               float(bridge["data-start"]) - float(root["result"]["data-start"]))
        self.assertGreater(float(bridge["data-start"]) + float(bridge["data-duration"]),
                           float(root["audition"]["data-start"]))

    def test_highlight_boundary_has_less_frame_change_than_old_hard_cut(self):
        def boundary_difference(path):
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", "41.5", "-i", str(path),
                "-frames:v", "2", "-vf", "scale=160:90", "-pix_fmt", "gray",
                "-f", "rawvideo", "-"])
            frame_size = 160 * 90
            self.assertEqual(len(raw), frame_size * 2)
            return sum(abs(a-b) for a, b in zip(raw[:frame_size], raw[frame_size:])) / frame_size
        self.assertLess(boundary_difference(self.render),
                        boundary_difference(first_cut.RENDER) * .5)

    def test_follow_count_disappears_before_the_full_view(self):
        def bright_pixels(at):
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(at), "-i", str(self.render),
                "-frames:v", "1", "-vf", "crop=140:43:1480:25",
                "-pix_fmt", "gray", "-f", "rawvideo", "-"])
            return sum(pixel > 180 for pixel in raw)
        self.assertGreater(bright_pixels(7), 100)
        self.assertLess(bright_pixels(8.1), 10)

    def test_music_duck_and_recovery_have_gradual_nonzero_envelopes(self):
        music = next(a for _, a in Elements(PROJECT / "index.html").tags
                     if a.get("id") == "music")
        points = json.loads(music["data-automation"])["lanes"][0]["points"]
        duck = [p for p in points if 39 <= p["t"] <= 41.515]
        recovery = [p for p in points if 53.515 <= p["t"] <= 55]
        self.assertGreaterEqual(duck[-1]["t"] - duck[0]["t"], 1.5)
        self.assertGreaterEqual(recovery[-1]["t"] - recovery[0]["t"], .8)
        self.assertGreaterEqual(duck[-1]["v"], .1)
        for envelope in (duck, recovery):
            for a, b in zip(envelope, envelope[1:]):
                self.assertLessEqual(abs(b["v"]-a["v"])/(b["t"]-a["t"]), .8)

    def test_summary_boundary_has_less_frame_change_than_previous_cut(self):
        def difference(path):
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", "53.5", "-i", str(path),
                "-frames:v", "2", "-vf", "scale=160:90", "-pix_fmt", "gray",
                "-f", "rawvideo", "-"])
            size = 160 * 90
            self.assertEqual(len(raw), size * 2)
            return sum(abs(a-b) for a, b in zip(raw[:size], raw[size:])) / size
        previous = PROJECT / "renders/dd-monitor-ce-plugins-promo-first-cut-v4.mp4"
        self.assertLess(difference(self.render), difference(previous) * .5)

    def test_ending_logo_precedes_name_without_delaying_final_copy(self):
        def bright_pixels(at, crop):
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(at), "-i", str(self.render),
                "-frames:v", "1", "-vf", crop, "-pix_fmt", "gray",
                "-f", "rawvideo", "-"])
            return sum(pixel > 70 for pixel in raw)
        self.assertGreater(bright_pixels(60.533333, "crop=140:150:890:245"), 100)
        self.assertLess(bright_pixels(60.533333, "crop=1120:140:400:410"), 10)
        self.assertGreater(bright_pixels(61.133333, "crop=1120:140:400:410"), 5000)

    def test_rendered_music_follows_fade_before_voice_and_after_voice(self):
        music = next(a for _, a in Elements(PROJECT / "index.html").tags
                     if a.get("id") == "music")
        points = json.loads(music["data-automation"])["lanes"][0]["points"]
        def pcm(path, start):
            samples = array.array("f")
            samples.frombytes(subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(start), "-i", str(path),
                "-t", "0.08", "-vn", "-ac", "1", "-ar", "48000",
                "-f", "f32le", "-"]))
            return samples
        for at in (40, 40.5, 41, 41.4, 53.8, 54.1, 54.4):
            reference = pcm(PROJECT / music["src"], float(music["data-media-start"]) + at)
            actual = pcm(self.render, at)
            a, b = next((a, b) for a, b in zip(points, points[1:])
                        if a["t"] <= at + .04 <= b["t"])
            expected = a["v"] + (b["v"]-a["v"])*(at+.04-a["t"])/(b["t"]-a["t"])
            gain = sum(x*y for x, y in zip(reference, actual))/sum(x*x for x in reference)
            with self.subTest(time=at):
                self.assertAlmostEqual(gain, expected, delta=.03)


if __name__ == "__main__":
    unittest.main()
