"""Check preserved Studio copy and continuity in the revised delivery."""
import subprocess
import unittest
from dev import test_promo_first_cut as first_cut
from dev.test_plugins_promo_sample import PROJECT, Elements


class TransitionRevisionTests(first_cut.FirstCutTests):
    render = PROJECT / "renders/dd-monitor-ce-plugins-promo-first-cut-v3.mp4"

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


if __name__ == "__main__":
    unittest.main()
