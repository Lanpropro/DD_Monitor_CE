"""Verify the revised sample's four beats, end card, and continuous audio."""

import array
import json
import math
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
        "format=duration:stream=codec_type,r_frame_rate,channels", "-of", "json", str(path),
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
    assembly = (PROJECT / "tools" / "assemble_v3_01_07_design.py").read_text(encoding="utf-8")
    assert '"ms-loop.wav"' in assembly and '"track.loop.mp3"' not in assembly
    assert "1+5 操作录屏待替换" in html
    assert "PR 页面录屏待替换" in html
    assert all(f"06-wall-{letter}.mp4" in html for letter in "abc")
    assert "插件" not in html
    assert abs(float(probe(SCENE)["format"]["duration"]) - 27.4) < .04

    info = probe(PREVIEW)
    assert abs(float(info["format"]["duration"]) - 78.55) < .04
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
    assert level(8.0) > level(8.4) * 2, "first live-sound fade-out is missing"
    assert level(12.0) > level(11.3) * 1.7, "stereo live-sound fade-in is missing"
    assert level(14.6) > level(15.1) * 2, "stereo live-sound fade-out is missing"
    print("v3 01–07 design: moving camera/arcs/wall, logo ending and continuous stereo music verified")


if __name__ == "__main__":
    main()
