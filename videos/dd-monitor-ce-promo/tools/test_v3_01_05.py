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
    pixel = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", "44", "-i", str(VIDEO), "-frames:v", "1",
        "-vf", "scale=1:1,format=rgb24", "-f", "rawvideo", "-",
    ])
    assert pixel[2] > pixel[0] * 2 and pixel[2] > pixel[1] * 2, "scene 05 is missing"
    print("v3 01-05: scene 05, music gaps, and simultaneous stereo audio verified")


if __name__ == "__main__":
    main()
