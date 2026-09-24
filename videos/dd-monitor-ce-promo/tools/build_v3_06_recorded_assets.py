"""Prepare the supplied scene-06 recordings for the fixed-length design edit."""

import subprocess
import argparse
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=("follow", "replay", "wall-a", "wall-b", "wall-c"))
    only = parser.parse_args().only
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if only in (None, "follow"):
        encode(["录制.mp4"],
               "[0:v]crop=3270:1838:0:0,setpts=PTS/2.36,fps=30,scale=1680:946,setsar=1[v]",
               "06-follow-recorded.mp4", 6.8)
    if only in (None, "replay"):
        encode(["pr片段.mp4"],
               "[0:v]crop=1430:680:1020:140,setpts=PTS/2.117,fps=30,scale=690:328,setsar=1[v]",
               "06-replay-preview.mp4", 7.5)
        encode(["pr片段.mp4"],
               "[0:v]crop=2480:420:0:1020,setpts=PTS/2.117,fps=30,scale=1520:258,setsar=1[v]",
               "06-replay-timeline.mp4", 7.5)
    for index, source in enumerate(("画面墙1.mp4", "画面墙2.mp4")):
        letter = chr(ord("a") + index)
        if only in (None, f"wall-{letter}"):
            encode([source],
                   "[0:v]crop=2928:1690:340:128,fps=30,scale=1580:914,setsar=1[v]",
                   f"06-wall-{letter}.mp4", 6.4)
    # Wall 3 contains two live rows; crop out its empty bottom row.
    if only in (None, "wall-c"):
        encode(["画面墙3.mp4"],
               "[0:v]crop=2928:1088:340:128,fps=30,scale=1580:588,setsar=1[v]",
               "06-wall-c.mp4", 6.4)


if __name__ == "__main__":
    main()
