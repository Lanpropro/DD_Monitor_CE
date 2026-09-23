"""Rebuild scene 03 from the original recording, skipping preview loading gaps."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROJECT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Video_reference" / "聚焦卡片_卡片预览.mp4"
OUTPUT = PROJECT / "assets" / "rec" / "focus-clip.mp4"

# Keep the original hover order. Each cut lands while the camera moves to a card.
SEGMENTS = ((0, 1.7, 0.9), (3, 5, 2.3), (5, 10.3, 2.55), (13, 15, 2.616667))


def main():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    filters = ["[0:v]crop=3270:1822:1:0,split=4" + "".join(f"[s{i}]" for i in range(4))]
    for i, (start, end, duration) in enumerate(SEGMENTS):
        filters.append(
            f"[s{i}]trim=start={start}:end={end},"
            f"setpts=(PTS-STARTPTS)*{duration}/{end-start},fps=30[v{i}]"
        )
    filters.append(
        "".join(f"[v{i}]" for i in range(4))
        + "concat=n=4:v=1:a=0,unsharp=5:5:0.65:5:5:0,format=yuv420p[out]"
    )
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE),
        "-filter_complex", ";".join(filters), "-map", "[out]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "13", "-g", "30",
        "-keyint_min", "30", "-movflags", "+faststart", str(OUTPUT),
    ], check=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
