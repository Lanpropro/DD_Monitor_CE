"""Prepare the supplied scene-06 recordings for the fixed-length design edit."""

import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REFERENCE = PROJECT.parents[1] / "Video_reference"
OUTPUT = PROJECT / "assets" / "rec"


def encode(inputs, filters, output, duration):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for source in inputs:
        command += ["-i", str(REFERENCE / source)]
    command += [
        "-filter_complex", filters, "-map", "[v]", "-an", "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUTPUT / output),
    ]
    subprocess.run(command, check=True)
    print(OUTPUT / output)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    encode(["录制.mp4"],
           "[0:v]crop=2820:1586:0:100,setpts=PTS/2.36,fps=30,scale=1680:946,setsar=1[v]",
           "06-follow-recorded.mp4", 6.8)
    encode(["pr片段.mp4"],
           "[0:v]crop=2450:1378:0:80,setpts=PTS/2.117,fps=30,scale=1690:950,setsar=1[v]",
           "06-replay-recorded.mp4", 7.5)
    for index, source in enumerate(("画面墙1.mp4", "画面墙2.mp4")):
        encode([source],
               "[0:v]crop=2928:1800:340:128,fps=30,scale=1580:972,setsar=1[v]",
               f"06-wall-{chr(ord('a') + index)}.mp4", 6.4)
    # Wall 3 has six live tiles and an empty bottom row. Complete the montage
    # with the moving bottom row from wall 1, joined on the existing gutter.
    encode(["画面墙3.mp4", "画面墙1.mp4"],
           "[0:v]crop=2928:1168:340:128[top];"
           "[1:v]crop=2928:632:340:1296[bottom];"
           "[top][bottom]vstack=inputs=2,fps=30,scale=1580:972,setsar=1[v]",
           "06-wall-c.mp4", 6.4)


if __name__ == "__main__":
    main()
