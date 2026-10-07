"""Validate the editable sample and its actual rendered audio/video."""
import array
import json
import subprocess
import unittest
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "videos/dd-monitor-ce-plugins-promo"
RENDER = PROJECT / "renders/sample-v7.mp4"


class Elements(HTMLParser):
    def __init__(self, path):
        super().__init__()
        self.tags = []
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def probe(path, *options):
    return json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", *options, "-of", "json", str(path)]))


class PromoSampleTests(unittest.TestCase):
    def test_preview_media_isolation_regression(self):
        subprocess.run(["node", "--test", str(ROOT / "dev/test_promo_videotogether.cjs")],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        entry = (PROJECT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("limited-diagnostic", entry)
        self.assertNotIn("127.0.0.1:3018", entry)

    def test_studio_motion_plugin_is_local_and_version_matches_gsap(self):
        # Studio injects this editing plugin from jsDelivr unless it is already
        # present. Shipping the matching local build avoids network-dependent reloads.
        scripts = [a["src"] for tag,a in Elements(PROJECT / "index.html").tags
                   if tag == "script" and "src" in a]
        self.assertEqual(scripts, ["assets/lib/gsap.min.js", "assets/lib/MotionPathPlugin.min.js"])
        for asset in scripts:
            text = (PROJECT / asset).read_text(encoding="utf-8")
            self.assertIn("3.14.2", text[:500])
            self.assertNotIn("https://cdn", text)

    def test_studio_lint_endpoint_has_no_findings(self):
        # Studio also scans catalog components, which the CLI entry-file lint
        # excludes. Verify the actual endpoint used by the preview's Lint button.
        with urllib.request.urlopen(
                "http://127.0.0.1:3017/api/projects/dd-monitor-ce-plugins-promo/lint",
                timeout=15) as response:
            findings = json.load(response)["findings"]
        self.assertEqual(findings, [])

    def test_user_copy_is_preserved_and_manual_demonstration_is_labeled(self):
        intro = (PROJECT / "compositions/intro.html").read_text(encoding="utf-8")
        domestic = (PROJECT / "compositions/domestic.html").read_text(encoding="utf-8")
        global_scene = (PROJECT / "compositions/global.html").read_text(encoding="utf-8")
        self.assertIn("红队绿队一起看。", intro)
        self.assertIn("为你的ALGS观看体验如“虎”添翼", domestic)
        self.assertNotIn("tl.set('#domestic-caption'", domestic)
        self.assertIn("海外的直播也一样", global_scene)
        self.assertIn("国（内）外大神视角一屏掌握", global_scene)
        self.assertNotIn("九格来自不同时间片段拼接", global_scene)
        self.assertNotIn("<br", global_scene)
        alignment = (PROJECT / "compositions/alignment.html").read_text(encoding="utf-8")
        self.assertIn("自动对齐优先，必要时手动微调。", alignment)
        self.assertNotIn("也可手动微调偏移。", alignment)
        self.assertNotIn("自动对齐演示", alignment)
        updates = (PROJECT / "compositions/updates.html").read_text(encoding="utf-8")
        self.assertIn("让每次观看，都更随心应手。", updates)
        for copy in ("关注，整理有序", "弹幕，随心调整", "插件，集中管理"):
            self.assertIn(copy, updates)
        self.assertNotIn("比赛二路", updates)

    def test_follow_camera_starts_on_the_topmost_recorded_card(self):
        frame = subprocess.check_output([
            "ffmpeg", "-v", "error", "-ss", "4.5", "-i", str(RENDER), "-frames:v", "1",
            "-vf", "crop=220:90:230:406,scale=64:36,format=gray", "-f", "rawvideo", "-"])
        source = subprocess.check_output([
            "ffmpeg", "-v", "error", "-ss", "4.5", "-i", str(PROJECT / "assets/domestic-apex-v7.mp4"),
            "-frames:v", "1", "-vf", "crop=112:46:18:106,scale=64:36,format=gray",
            "-f", "rawvideo", "-"])
        self.assertEqual(len(frame), 64*36)
        error = sum(abs(a-b) for a,b in zip(frame,source))/len(frame)
        self.assertLess(error, 10, "First camera beat skipped the topmost recorded card")

    def test_native_domestic_panes_have_no_extended_freeze_when_revealed(self):
        # The source's early paused third player must stay hidden. Once each mask
        # opens, all six panes must use smooth footage from the reset recording.
        regions = [(198,14,1138,662),(1344,14,562,312),(1344,360,562,314),
                   (200,710,562,310),(772,710,562,310),(1344,710,562,310)]
        for pane, (x,y,w,h) in enumerate(regions):
            visible = 3.636 + 4.9 + pane*.212
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(visible), "-i",
                str(PROJECT / "assets/domestic-apex-v7.mp4"), "-t", str(16.364-visible),
                "-vf", f"crop={w}:{h}:{x}:{y},scale=64:36,format=gray",
                "-f", "rawvideo", "-"])
            size = 64*36
            frames = [raw[i:i+size] for i in range(0,len(raw),size)]
            run = longest = 0
            for a,b in zip(frames,frames[1:]):
                change = sum(abs(u-v) for u,v in zip(a,b))/size
                run = run+1 if change < .35 else 0
                longest = max(longest,run)
            with self.subTest(pane=pane):
                self.assertGreater(len(frames), 190)
                self.assertLessEqual(longest/30, .5, "A native pane stalled for over half a second")
        domestic = (PROJECT / "compositions/domestic.html").read_text(encoding="utf-8")
        self.assertNotIn("部分画面以其他流畅片段替换", domestic)
        self.assertIn("const ys=[112,178,263,349,434,519,604,690,775]", domestic)

    def test_domestic_is_the_new_recording_and_intro_joins_it_continuously(self):
        end = 0
        for name in ("intro", "domestic"):
            path = PROJECT / f"compositions/{name}.html"
            video = [a for tag, a in Elements(path).tags if tag == "video"][0]
            self.assertEqual(video["src"], "assets/domestic-apex-v7.mp4")
            self.assertAlmostEqual(float(video.get("data-media-start", 0)), end)
            end += float(video["data-duration"])
            self.assertNotIn("待替换", path.read_text(encoding="utf-8"))
        source = next(s for s in json.loads((PROJECT / "sources.json").read_text(
            encoding="utf-8")) if s["asset"] == "domestic-apex-v7.mp4")
        self.assertEqual(source["source"], "Video_reference/国内apex1+5 重置.mp4")
        self.assertEqual(source["source_start"], 8.9)
        self.assertFalse(source["looped"])
        self.assertGreaterEqual(source["duration"], end)

    def test_render_reveals_six_panes_and_matches_the_real_one_plus_five_source(self):
        # Sample each actual pane, including the large primary view; avoid captions and controls.
        regions = [(340,220,800,350),(1330,130,400,200),(1330,430,400,180),
                   (340,735,350,170),(850,735,350,170),(1330,735,400,170)]
        for pane, (x,y,w,h) in enumerate(regions, 1):
            frames = [subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(RENDER),
                "-frames:v", "1", "-vf",
                f"crop={w}:{h}:{x}:{y},scale=64:36,format=gray", "-f", "rawvideo", "-"])
                for time in (8.3,10.3,12.3)]
            with self.subTest(pane=pane):
                self.assertEqual(len(frames[0]), 64*36)
                self.assertLess(max(frames[0])-min(frames[0]), 8, "Pane leaked before reveal")
                self.assertGreater(max(frames[1])-min(frames[1]), 40, "Pane stayed masked")
                # A streamer can hold the camera still. Compare to the actual source instead
                # of requiring arbitrary movement from every game view.
                sx, sy = 1920/1678, 1080/943  # Software viewport excludes its 1px border.
                source_crop = [int(v)//2*2 for v in (w*sx,h*sy,(x-121)*sx,(y-77)*sy)]
                for time, rendered in zip((10.3,12.3), frames[1:]):
                    # 3.636s is between frames at 30fps; the renderer floors source seeks.
                    # Accept the expected frame or its immediate predecessor, never a broad range.
                    expected = subprocess.check_output([
                        "ffmpeg", "-v", "error", "-ss", str(time-1/30), "-i",
                        str(PROJECT / "assets/domestic-apex-v7.mp4"), "-frames:v", "2", "-vf",
                        "crop="+":".join(map(str,source_crop))+",scale=64:36,format=gray",
                        "-f", "rawvideo", "-"])
                    size = len(rendered)
                    self.assertEqual(len(expected), size*2)
                    error = min(sum(abs(a-b) for a,b in zip(rendered,expected[j:j+size]))/size
                                for j in (0,size))
                    self.assertLess(error, 10, "Rendered pane differs from its real source frame")

    def test_scenes_cover_timeline_and_match_children(self):
        tags = Elements(PROJECT / "index.html").tags
        hosts = [attrs for _, attrs in tags if "data-composition-src" in attrs]
        self.assertEqual(len(hosts), 9)
        previous = 0
        for host in hosts:
            with self.subTest(scene=host["id"]):
                self.assertAlmostEqual(float(host["data-start"]), previous, places=3)
                duration = float(host["data-duration"])
                self.assertGreater(duration, 0)
                child = Elements(PROJECT / host["data-composition-src"])
                roots = [a for _, a in child.tags if "data-composition-id" in a]
                self.assertEqual(roots[0]["data-composition-id"], host["id"])
                self.assertAlmostEqual(float(roots[0]["data-duration"]), duration)
                previous += duration
        self.assertAlmostEqual(previous, 64.424, places=3)

    def test_all_media_fit_their_source_and_are_muted(self):
        for path in (PROJECT / "compositions").glob("*.html"):
            for tag, attrs in Elements(path).tags:
                if tag != "video":
                    continue
                with self.subTest(video=attrs["id"]):
                    source = PROJECT / attrs["src"]
                    metadata = probe(source, "-show_format", "-show_streams")
                    consumed = float(attrs.get("data-media-start", 0)) + float(
                        attrs["data-duration"]) * float(attrs.get("data-playback-rate", 1))
                    self.assertLessEqual(consumed, float(metadata["format"]["duration"]) + .04)
                    self.assertIn("muted", attrs)
                    self.assertFalse(any(s["codec_type"] == "audio"
                                         for s in metadata["streams"]))

    def test_seeking_assets_have_one_second_keyframes(self):
        for source in (PROJECT / "assets").glob("*.mp4"):
            frames = probe(source, "-select_streams", "v:0", "-skip_frame", "nokey",
                           "-show_frames", "-show_entries", "frame=best_effort_timestamp_time")
            times = [float(f["best_effort_timestamp_time"]) for f in frames["frames"]]
            with self.subTest(source=source.name):
                self.assertTrue(times)
                self.assertLessEqual(max([b-a for a, b in zip(times, times[1:])] + [0]), 1.04)

    def test_render_is_sixty_seconds_with_expected_tracks(self):
        self.assertTrue(RENDER.is_file(), "Render the sample before running delivery checks")
        metadata = probe(RENDER, "-show_format", "-show_streams")
        self.assertAlmostEqual(float(metadata["format"]["duration"]), 60, delta=.08)
        video = [s for s in metadata["streams"] if s["codec_type"] == "video"]
        audio = [s for s in metadata["streams"] if s["codec_type"] == "audio"]
        self.assertEqual(len(video), 1)
        self.assertEqual(len(audio), 1)
        self.assertEqual((video[0]["width"], video[0]["height"]), (1920, 1080))
        self.assertEqual(video[0]["r_frame_rate"], "30/1")
        self.assertEqual(int(video[0]["nb_frames"]), 1800)
        subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(RENDER),
                        "-f", "null", "-"], check=True, capture_output=True)

    def test_reveal_music_has_no_added_silence(self):
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(RENDER),
                                       "-vn", "-ac", "1", "-ar", "48000",
                                       "-f", "f32le", "-"])
        samples = array.array("f")
        samples.frombytes(raw)
        music = next(a for tag, a in Elements(PROJECT / "index.html").tags
                     if tag == "audio" and a["id"] == "music")
        points = json.loads(music["data-automation"])["lanes"][0]["points"]
        gaps = [(a["t"], b["t"]) for a, b in zip(points, points[1:])
                if a["v"] == b["v"] == 0]
        self.assertEqual(gaps, [])
        for offset in range(int(23.8*48000), int(24.7*48000), 2400):
            window = samples[offset:offset+2400]
            rms = (sum(v*v for v in window)/len(window))**.5
            self.assertGreater(rms, .001)

    def test_title_handoff_does_not_flash_an_empty_frame(self):
        for time in (24.5, 24.533333, 24.6):
            frame = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(RENDER),
                "-frames:v", "1", "-vf",
                "crop=1680:945:120:76,scale=160:90,format=gray", "-f", "rawvideo", "-"])
            with self.subTest(time=time):
                self.assertEqual(len(frame), 160*90)
                self.assertGreater(sum(v > 90 for v in frame)/len(frame), .005)

    def test_reveal_to_alignment_keeps_the_window_continuous(self):
        frames = []
        for time in (25.433333, 25.466667):
            frames.append(subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(RENDER),
                "-frames:v", "1", "-vf",
                "crop=1680:945:120:76,scale=160:90,format=gray", "-f", "rawvideo", "-"]))
        self.assertEqual(len(frames[0]), 160*90)
        self.assertEqual(len(frames[1]), len(frames[0]))
        jump = sum(abs(a-b) for a, b in zip(*frames)) / (len(frames[0])*255)
        # Continuous source time should avoid the previous cut's large visual jump.
        self.assertLess(jump, .05)

    def test_platform_wipe_preserves_the_background_gutter(self):
        frames = []
        for time in (15.3, 16.25):
            frames.append(subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(RENDER),
                "-frames:v", "1", "-vf",
                "crop=96:700:0:150,scale=32:64,format=gray", "-f", "rawvideo", "-"]))
        self.assertEqual(len(frames[0]), 32*64)
        difference = sum(abs(a-b) for a, b in zip(*frames)) / (len(frames[0])*255)
        self.assertLess(difference, .005)

    def test_music_continues_at_platform_cut_and_old_twenty_one_second_gap(self):
        for start in (16.2, 20.85):
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-ss", str(start), "-i", str(RENDER), "-t", "0.5",
                "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"])
            samples = array.array("f")
            samples.frombytes(raw)
            for offset in range(0, len(samples)-2400, 2400):
                window = samples[offset:offset+2400]
                rms = (sum(v*v for v in window)/len(window))**.5
                self.assertGreater(rms, .005)

    def test_match_scenes_use_one_continuous_source_and_audition_is_separate(self):
        expected_end = 0
        for scene in ("reveal", "alignment", "result"):
            tags = Elements(PROJECT / f"compositions/{scene}.html").tags
            videos = [a for tag, a in tags if tag == "video"]
            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0]["src"], "assets/match-continuous.mp4")
            self.assertAlmostEqual(float(videos[0].get("data-media-start", 0)), expected_end)
            expected_end += float(videos[0]["data-duration"])
        audition = Elements(PROJECT / "compositions/audition.html").tags
        video = next(a for tag, a in audition if tag == "video")
        self.assertEqual(video["src"], "assets/highlight-picture.mp4")
        self.assertEqual(float(video["data-duration"]), 12)
        self.assertFalse(any("caption" in a.get("class", "").split() for _, a in audition))
        self.assertGreater(float(video["data-duration"]), 7)

    def test_each_stitched_cell_has_no_extended_freeze(self):
        for cell in range(1, 10):
            path = PROJECT / f"assets/global-cell-{cell}.mp4"
            raw = subprocess.check_output([
                "ffmpeg", "-v", "error", "-i", str(path), "-vf",
                "crop=562:310:0:0,scale=64:36,format=gray", "-f", "rawvideo", "-"])
            size = 64*36
            frames = [raw[i:i+size] for i in range(0, len(raw), size)]
            longest = run = 0
            for a, b in zip(frames, frames[1:]):
                difference = sum(abs(x-y) for x, y in zip(a, b))/size
                run = run+1 if difference < .35 else 0
                longest = max(longest, run)
            with self.subTest(cell=cell):
                self.assertGreater(len(frames), 175)
                self.assertLessEqual(longest/30, .3)


if __name__ == "__main__":
    unittest.main()
