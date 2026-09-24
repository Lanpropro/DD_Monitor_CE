"""Verify the recorded-wall placeholder preview and its join to scenes 01–05."""

import array
import json
import math
import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCENE = PROJECT / "renders" / "v3-06-oss-30fps.mp4"
PREVIEW = PROJECT / "renders" / "v3-01-06-preview.mp4"


def probe(path):
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,r_frame_rate,channels", "-of", "json", str(path),
    ], text=True))


def frame(path, time):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(path),
        "-frames:v", "1", "-vf", "scale=32:18,format=gray", "-f", "rawvideo", "-",
    ])


def rms(time):
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-t", "0.4",
        "-i", str(PREVIEW), "-vn", "-f", "s16le", "-ar", "48000", "-ac", "2", "-",
    ])
    samples = array.array("h")
    samples.frombytes(data)
    return math.sqrt(sum(value * value for value in samples) / len(samples))


def main():
    html = (PROJECT / "compositions" / "v3" / "18-06-oss.html").read_text(encoding="utf-8")
    assert "插件目录录屏 · 待替换" in html
    assert "软件右键操作录屏 · 待替换" in html
    assert "06-wall-live.mp4" in html and "grid-1.png" not in html

    assert abs(float(probe(SCENE)["format"]["duration"]) - 15.5) < 0.04
    info = probe(PREVIEW)
    assert abs(float(info["format"]["duration"]) - 63.4) < 0.04
    assert info["streams"][0]["r_frame_rate"] == "30/1"
    assert info["streams"][1]["channels"] == 2

    assert sum(frame(SCENE, 2.0)) > sum(frame(SCENE, 4.5)), "white to purple scene change missing"
    assert sum(frame(SCENE, 8.5)) > sum(frame(SCENE, 4.5)), "purple to white scene change missing"
    a, b = frame(SCENE, 12.8), frame(SCENE, 14.0)
    assert sum(abs(x - y) for x, y in zip(a, b)) > 500, "recorded wall appears frozen"
    for time in (47.5, 49.0, 55.0, 62.0):
        assert rms(time) > 400, f"music gap at {time}s"
    print("v3 01–06: placeholder, live wall motion, scene joins and continuous stereo music verified")


if __name__ == "__main__":
    main()
