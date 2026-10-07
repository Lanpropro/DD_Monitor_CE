"""Verify final-cut copy, complete media references and delivered sound."""
import array
import math
import subprocess
import unittest
from html.parser import HTMLParser
from dev.test_plugins_promo_sample import Elements, PROJECT, probe

RENDER = PROJECT / "renders/dd-monitor-ce-plugins-promo-first-cut.mp4"


class Copy(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.hidden = 0
        self.text = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


class FirstCutTests(unittest.TestCase):
    render = RENDER

    def test_no_placeholder_copy_or_sample_tag_in_active_scenes(self):
        for path in [PROJECT / "index.html", *sorted((PROJECT / "compositions").glob("*.html"))]:
            copy = "".join(Copy(path).text)
            for placeholder in ("样片", "待替换", "待补", "预留", "占位", "TODO", "TBD", "placeholder"):
                with self.subTest(path=path.name, placeholder=placeholder):
                    self.assertNotIn(placeholder, copy)
        entry = (PROJECT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("sample-tag", entry)
        self.assertIn("highlight-dual-commentary-v3.wav", entry)
        intro = (PROJECT / "compositions/intro.html").read_text(encoding="utf-8")
        self.assertIn("多平台支持", intro)

    def test_all_active_media_are_available_and_within_source_duration(self):
        for path in [PROJECT / "index.html", *sorted((PROJECT / "compositions").glob("*.html"))]:
            for tag, attrs in Elements(path).tags:
                if tag not in ("video", "audio", "img") or "src" not in attrs:
                    continue
                source = PROJECT / attrs["src"]
                with self.subTest(source=attrs["src"]):
                    self.assertTrue(source.is_file())
                    if tag in ("audio", "video"):
                        metadata = probe(source, "-show_format")
                        end = float(attrs.get("data-media-start", 0)) + float(attrs["data-duration"])
                        self.assertLessEqual(end, float(metadata["format"]["duration"])+.04)

    def test_delivered_video_matches_full_timeline_and_decodes(self):
        metadata = probe(self.render, "-show_streams", "-show_format")
        video, audio = metadata["streams"]
        self.assertEqual((video["width"], video["height"], video["r_frame_rate"]),
                         (1920, 1080, "30/1"))
        self.assertEqual(int(video["nb_frames"]), math.ceil(64.424*30))
        self.assertEqual(audio["channels"], 2)
        self.assertAlmostEqual(float(metadata["format"]["duration"]), 64.424, delta=.05)
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(self.render),
                        "-f", "null", "-"], check=True, capture_output=True)

    def test_delivered_highlight_uses_the_accepted_stereo_audio(self):
        def pcm(source, start):
            data = array.array("f")
            data.frombytes(subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(start), "-i", str(source),
                "-t", "11", "-vn", "-ac", "2", "-ar", "48000", "-f", "f32le", "-"]))
            return data
        from dev.test_promo_highlight_audio import correlation
        expected = pcm(PROJECT / "assets/highlight-dual-commentary-v3.wav", .5)
        rendered = pcm(self.render, 42.015)
        length = min(len(expected), len(rendered))
        for channel in (0, 1):
            self.assertGreater(correlation(expected[channel:length:2],
                                           rendered[channel:length:2]), .90)

    def test_delivered_audio_has_no_unintended_gaps(self):
        data = array.array("f")
        data.frombytes(subprocess.check_output([
            "ffmpeg", "-v", "error", "-i", str(self.render), "-vn", "-ac", "1",
            "-ar", "48000", "-f", "f32le", "-"]))
        for start in range(48000, 63*48000, 12000):
            window = data[start:start+12000]
            with self.subTest(start=start/48000):
                self.assertGreater(math.sqrt(sum(x*x for x in window)/len(window)), .001)


if __name__ == "__main__":
    unittest.main()
