"""Verify that each focused card shows a loaded preview in scene 03."""

import json
import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
CLIP = PROJECT / "assets" / "rec" / "focus-clip.mp4"
SCENE = PROJECT / "renders" / "v3-03-hover-30fps.mp4"


def mean_pixel(video, time, crop):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(video),
        "-frames:v", "1", "-vf", f"crop={crop},scale=1:1,format=rgb24",
        "-f", "rawvideo", "-",
    ])


def main():
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,r_frame_rate",
        "-of", "json", str(CLIP),
    ], text=True))
    assert info["streams"][0]["width"] == 3270
    assert info["streams"][0]["height"] == 1822
    assert info["streams"][0]["r_frame_rate"] == "30/1"
    assert abs(float(info["format"]["duration"]) - 8.382) < 0.04
    for time, crop in ((1.7, "160:80:40:550"), (4.5, "160:80:40:715"), (6.6, "160:80:40:880")):
        assert sum(mean_pixel(CLIP, time, crop)) / 3 > 35, f"source preview is black at {time}s"
    for time in (2.5, 4.5, 6.6):
        assert sum(mean_pixel(SCENE, time, "100:80:880:470")) / 3 > 35, f"rendered preview is black at {time}s"
    print("v3 scene 03: three loaded previews in source and rendered scene")


if __name__ == "__main__":
    main()
