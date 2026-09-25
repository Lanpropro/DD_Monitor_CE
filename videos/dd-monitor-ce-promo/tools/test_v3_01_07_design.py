"""Verify the revised sample's four beats, end card, and continuous audio."""

import array
import json
import math
import re
import subprocess
from pathlib import Path

from assemble_v3_01_07_design import live_gain


PROJECT = Path(__file__).resolve().parents[1]
SCENE = PROJECT / "renders" / "v3-06-design-30fps.mp4"
PREVIEW = PROJECT / "renders" / "v3-01-07-design-preview.mp4"
ENDING = PROJECT / "renders" / "v3-07-end-30fps.mp4"


def probe(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,r_frame_rate,channels,width,height", "-of", "json", str(path),
    ], text=True))


def frame(path, time, crop=None):
    filters = ([f"crop={crop}"] if crop else []) + ["scale=64:36", "format=gray"]
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(path),
        "-frames:v", "1", "-vf", ",".join(filters), "-f", "rawvideo", "-",
    ])


def difference(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def rms(time):
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-t", "0.4",
        "-i", str(PREVIEW), "-vn", "-f", "s16le", "-ar", "48000", "-ac", "2", "-",
    ])
    samples = array.array("h")
    samples.frombytes(data)
    return math.sqrt(sum(value * value for value in samples) / len(samples))


def stereo_rms(time):
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-t", "1",
        "-i", str(PREVIEW), "-vn", "-f", "s16le", "-ar", "48000", "-ac", "2", "-",
    ])
    samples = array.array("h")
    samples.frombytes(data)
    return tuple(math.sqrt(sum(v * v for v in samples[channel::2]) / (len(samples) // 2))
                 for channel in (0, 1))


def music_match():
    """Confirm the rendered bed matches the extracted Microsoft Loop spectrum."""
    import numpy as np

    def sample(path):
        data = subprocess.check_output([
            "ffmpeg", "-v", "error", "-ss", "5", "-t", "1",
            "-i", str(path), "-vn", "-f", "s16le", "-ar", "12000", "-ac", "1", "-",
        ])
        values = array.array("h")
        values.frombytes(data)
        return values

    source = np.asarray(sample(PROJECT / "assets" / "bgm" / "ms-loop.wav"), dtype=float)
    rendered = np.asarray(sample(PREVIEW), dtype=float)
    window = np.hanning(len(source))
    source_spectrum = np.log1p(np.abs(np.fft.rfft(source * window)))
    rendered_spectrum = np.log1p(np.abs(np.fft.rfft(rendered * window)))
    return float(np.corrcoef(source_spectrum, rendered_spectrum)[0, 1])


def fade_levels():
    """Measure the actual FFmpeg gain expression with a steady test tone."""
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=16",
        "-af", f"volume='{live_gain()}':eval=frame",
        "-f", "s16le", "-ac", "1", "-",
    ])
    samples = array.array("h")
    samples.frombytes(data)

    def level(time):
        values = samples[round(time * 48000):round((time + .1) * 48000)]
        return math.sqrt(sum(value * value for value in values) / len(values))

    return level


def main():
    html = (PROJECT / "compositions" / "v3" / "18-06-design.html").read_text(encoding="utf-8")
    intro = (PROJECT / "compositions" / "v3" / "18-01-intro.html").read_text(encoding="utf-8")
    assembly = (PROJECT / "tools" / "assemble_v3_01_07_design.py").read_text(encoding="utf-8")
    cells = re.findall(r'<img class="pt pt-cell pt-r([0-2]) pt-c([0-2])" id="pR([0-2])C([0-2])" src="assets/rec/grid-([1-9]).png"', intro)
    assert len(cells) == 9 and "pMain" not in intro and "cell-main.png" not in intro
    # 2026-09-24: 格子显示比例（292x166/178/183）与九格素材比例（各列 1.65/1.76/1.77）不一致，
    # 必须用 cover —— contain 会在格内四周留出 background 的深灰，就是用户报的"灰色分割线"
    assert '.pt-cell { object-fit: cover; background: #0e1014; }' in intro
    assert '.pt-c0 { left: 104px; width: 292px; }' in intro
    assert '.pt-c1 { left: 402px; width: 292px; }' in intro
    assert '.pt-c2 { left: 701px; width: 292px; }' in intro
    assert 'tl.to("#appstage", { z: 890, y: 25, duration: 1.50' in intro
    assert 'tl.to("#appstage", { z: 920, duration: 3.20' in intro
    assert cells == [(str(row), str(col), str(row), str(col), str(row * 3 + col + 1))
                     for row in range(3) for col in range(3)]
    assert all((PROJECT / "assets" / "rec" / f"grid-{i}.png").is_file() for i in range(1, 10))
    arrivals = re.findall(r'tl\.to\("(#p(?:R[0-2]C[0-2]|Sb))"[^\n]+\}, ([\d.]+)\);', intro)
    assert [name for name, _ in arrivals] == [
        "#pR2C0", "#pR2C1", "#pR2C2", "#pR1C0", "#pR1C1", "#pR1C2",
        "#pR0C0", "#pR0C1", "#pR0C2", "#pSb",
    ]
    assert all(abs(float(at) - expected) < .001 for (_, at), expected in zip(arrivals, [
        5.334, 5.414, 5.494, 5.715, 5.795, 5.875, 6.096, 6.176, 6.256, 6.477,
    ]))
    assert '"ms-loop.wav"' in assembly and '"track.loop.mp3"' not in assembly
    assert "tpad=stop_mode=clone" not in assembly, "scene 04 must reach its transition without a frozen hold"
    assert '<div id="replayHead">即时重放</div>' in html and "及时重放" not in html
    assert "replayBadge" not in html and "wallBadge" not in html, "recorded scenes must not display source badges"
    assert 'tl.to("#wallCol", { y: 150, duration: 1.45, ease: "back.out(0.8)" }, 21.15)' in html
    assert 'tl.to("#wallCol", { y: -730, duration: 2.1, ease: "sine.inOut" }, 22.6)' in html
    ending_html = (PROJECT / "compositions" / "v3" / "18-07-end.html").read_text(encoding="utf-8")
    assert 'id="musicCredit">BGM · Microsoft-Loop</div>' in ending_html
    assert '}, 2.78);' in ending_html
    assert 'src="assets/rec/06-follow-recorded.mp4"' in html
    assert 'src="assets/rec/06-replay-preview.mp4"' in html
    assert 'src="assets/rec/06-replay-timeline.mp4"' in html
    assert '#longOutline { left: 246px; top: 223px; width: 1122px;' in html
    assert '#shortOutline { left: 1366px; top: 192px; width: 55px;' in html
    assert '更高效的录制切片，切出爆点' in html
    assert 'id="simCursor"' in html and 'id="cursorPulse"' in html
    assert 'const recButtons = [' in html and html.count('y: 914') == 3
    assert 'y: 550 - s * p.y' in html
    assert 'id="longOutline"' in html and 'id="shortOutline"' in html
    assert '.wallPanel { width: 1580px; height: 914px;' in html
    assert '.wallPanel:last-child { height: 588px; }' in html
    assert "操作录屏待替换" not in html and "PR 页面录屏待替换" not in html
    assert all(f"06-wall-{letter}.mp4" in html for letter in "abc")
    for name, duration in (("06-follow-recorded.mp4", 6.8),
                           ("06-replay-preview.mp4", 7.5),
                           ("06-replay-timeline.mp4", 7.5),
                           *((f"06-wall-{letter}.mp4", 6.4) for letter in "abc")):
        path = PROJECT / "assets" / "rec" / name
        assert abs(float(probe(path)["format"]["duration"]) - duration) < .05
    assert all(probe(PROJECT / "assets" / "rec" / f"06-wall-{letter}.mp4")["streams"][0]["height"] == 914
               for letter in "ab")
    assert probe(PROJECT / "assets" / "rec" / "06-wall-c.mp4")["streams"][0]["height"] == 588
    builder = (PROJECT / "tools" / "build_v3_06_recorded_assets.py").read_text(encoding="utf-8")
    assert 'crop=3270:1838:0:0' in builder and 'crop=2928:1088:340:128' in builder
    assert difference(frame(PROJECT / "assets" / "rec" / "06-wall-c.mp4", .5),
                      frame(PROJECT / "assets" / "rec" / "06-wall-c.mp4", 5.5)) > 1500
    assert "插件" not in html
    assert 'id="infoSoftware"' in html
    assert 'background: url("assets/rec/06-layout-placeholder.jpg") center / cover' in html
    assert 'filter: grayscale(1) brightness(.38) blur(1px)' in html
    assert 'tl.to("#infoSoftware", { opacity: .42, x: 0' in html
    assert abs(float(probe(SCENE)["format"]["duration"]) - 27.4) < .04

    info = probe(PREVIEW)
    assert abs(float(info["format"]["duration"]) - 78.55) < .04
    assert difference(frame(PREVIEW, 40.10), frame(PREVIEW, 40.50)) > 1500, "stereo pages froze before scene 05"
    assert info["streams"][0]["r_frame_rate"] == "30/1"
    assert info["streams"][1]["channels"] == 2
    assert music_match() > .8, "rendered music does not match Microsoft Loop"
    assert difference(frame(SCENE, 1.2), frame(SCENE, 3.0)) > 18000, "follow camera did not move"
    assert difference(frame(SCENE, 15.1, "700:700:1140:150"),
                      frame(SCENE, 16.3, "700:700:1140:150")) > 700, "right arcs appear static"
    assert difference(frame(SCENE, 23.4), frame(SCENE, 25.5)) > 18000, "wall did not pull upward"
    assert sum(frame(PREVIEW, 77.4)) > sum(frame(PREVIEW, 75.3)), "logo ending is missing"
    assert sum(frame(ENDING, 3.2, "90:80:990:300")) / (64 * 36) > 90, "second D is hidden in the logo"
    for time in (47.5, 49.0, 60.0, 74.5, 77.0, 78.1):
        assert rms(time) > 400, f"music gap at {time}s"
    assert min(stereo_rms(37.0)) > 700, "one live channel is missing during simultaneous playback"
    level = fade_levels()
    assert level(1.1) < 10 and level(8.8) < 10 and level(10.9) < 10
    assert level(2.3) > level(1.7) * 1.7, "first live-sound fade-in is missing"
    assert level(2.3) > 7000, "first live-sound passage is too quiet"
    assert level(8.0) > level(8.4) * 2, "first live-sound fade-out is missing"
    assert level(12.0) > level(11.3) * 1.7, "stereo live-sound fade-in is missing"
    assert level(14.6) > level(15.1) * 2, "stereo live-sound fade-out is missing"
    print("v3 01–07 design: moving camera/arcs/wall, logo ending and continuous stereo music verified")


if __name__ == "__main__":
    main()
