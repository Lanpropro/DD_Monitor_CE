"""Verify that the 01-05 preview retains scene 05 and a clean stereo music bed."""

import array
import json
import math
import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
VIDEO = PROJECT / "renders" / "v3-01-05-preview.mp4"


def channel_rms(start, seconds=0.5):
    pcm = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(start), "-t", str(seconds),
        "-i", str(VIDEO), "-vn", "-f", "s16le", "-ar", "48000", "-ac", "2", "-",
    ])
    samples = array.array("h")
    samples.frombytes(pcm)
    return tuple(
        math.sqrt(sum(sample * sample for sample in samples[channel::2]) / (len(samples) // 2))
        for channel in (0, 1)
    )


def frame_mean(start, crop=None):
    filters = ([f"crop={crop}"] if crop else []) + ["scale=1:1", "format=rgb24"]
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(start), "-i", str(VIDEO), "-frames:v", "1",
        "-vf", ",".join(filters), "-f", "rawvideo", "-",
    ])


def main():
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,r_frame_rate,channels", "-of", "json", str(VIDEO),
    ], text=True))
    assert abs(float(info["format"]["duration"]) - 48.45) < 0.04
    video, audio = info["streams"]
    assert video["codec_type"] == "video" and video["r_frame_rate"] == "30/1"
    assert audio["codec_type"] == "audio" and audio["channels"] == 2
    for start in (5, 24.7, 33.7, 40.4, 44.0, 47.0):
        assert max(channel_rms(start)) > 500, f"missing music at {start}s"
    left, right = channel_rms(37.0, 1.0)
    assert min(left, right) > 700, "one live channel is too quiet during simultaneous playback"
    flash = frame_mean(24.75)
    assert min(flash) > 245, "03 to 04 white flash is missing"
    assert max(frame_mean(24.3)) < 200, "flash must be distinct from the preceding frame"
    app = frame_mean(44, "350:200:1180:425")
    backdrop = frame_mean(44, "200:150:100:800")
    assert min(app) > 100 and min(backdrop) < 30, "scene 05 software preview is missing"
    print("v3 01-05: white flash, scene 05, music gaps, and simultaneous stereo audio verified")


if __name__ == "__main__":
    main()
