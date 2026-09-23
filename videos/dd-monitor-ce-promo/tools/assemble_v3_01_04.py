"""Join the four HTML-rendered v3 scenes with picture transitions and music gaps."""

import subprocess
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
RENDERS = PROJECT / "renders"
OUTPUT = RENDERS / "v3-01-04-preview.mp4"

# Scene lengths: 12.0, 6.0, 8.4, 15.5 seconds. The three joins overlap.
FIRST_JOIN = 11.5
SECOND_JOIN = 16.85
FOURTH_START = 24.55
FINAL_LENGTH = 41.55


def music_gain():
    """Keep music in picture-only gaps and fade it around recorded sound."""
    levels = [
        (25.65, "0.6"),
        (25.95, "0.6*(25.95-t)/0.3"),
        (33.15, "0"),
        (33.45, "0.45*(t-33.15)/0.3"),
        (34.95, "0.45"),
        (35.25, "0.45*(35.25-t)/0.3"),
        (39.85, "0"),
        (40.15, "0.45*(t-39.85)/0.3"),
        (41.05, "0.45"),
        (41.55, "0.45*(41.55-t)/0.5"),
    ]
    expression = "0"
    for time, level in reversed(levels):
        expression = f"if(lt(t,{time}),{level},{expression})"
    return expression


def main():
    inputs = [
        RENDERS / "v3-01-intro-30fps.mp4",
        RENDERS / "v3-02-layout-30fps.mp4",
        RENDERS / "v3-03-hover-30fps.mp4",
        RENDERS / "v3-04-audio-30fps.mp4",
        PROJECT / "assets" / "bgm" / "track.loop.mp3",
    ]
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(f"Render the missing source first: {path}")

    filters = []
    for index in range(4):
        filters.append(f"[{index}:v]fps=30,settb=AVTB,format=yuv420p,setsar=1[v{index}]")
    filters += [
        f"[v0][v1]xfade=transition=fade:duration=0.5:offset={FIRST_JOIN}[v01]",
        f"[v01][v2]xfade=transition=fadeblack:duration=0.65:offset={SECOND_JOIN}[v012]",
        f"[v012][v3]xfade=transition=slideleft:duration=0.7:offset={FOURTH_START},"
        "tpad=stop_mode=clone:stop_duration=1.5[vout]",
        f"[4:a]atrim=0:{FINAL_LENGTH},asetpts=PTS-STARTPTS,"
        f"volume='{music_gain()}':eval=frame,"
        "aformat=sample_rates=48000:channel_layouts=stereo[bed]",
        f"[3:a]volume=2,adelay={int(FOURTH_START * 1000)}:all=1,"
        f"atrim=0:{FINAL_LENGTH},aformat=sample_rates=48000:channel_layouts=stereo[live]",
        "[bed][live]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[aout]",
    ]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for path in inputs:
        cmd += ["-i", str(path)]
    cmd += [
        "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
        "-t", str(FINAL_LENGTH), "-r", "30", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(OUTPUT),
    ]
    subprocess.run(cmd, check=True)
    print(OUTPUT)


if __name__ == "__main__":
    main()
