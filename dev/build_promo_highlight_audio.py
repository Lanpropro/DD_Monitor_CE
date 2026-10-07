"""Restore the approved highlight's sound from two visually aligned local replays."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "videos/dd-monitor-ce-plugins-promo"


def run(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def build():
    sync = json.loads((PROJECT / "highlight-sync.json").read_text(encoding="utf-8"))
    duration = sync["duration"]
    evidence = ROOT / "work/highlight-sync"
    evidence.mkdir(parents=True, exist_ok=True)
    mono = []
    for name in ("machine", "csboy"):
        source = sync[name]
        handle = evidence / f"{name}-aligned-handles.wav"
        run("-ss", source["start"]+source["audio_advance_seconds"]-5,
            "-i", ROOT / source["source"],
            "-t", duration+10, "-map", "0:a:0", "-ac", 1, "-ar", 48000,
            "-c:a", "pcm_s16le", handle)
        path = evidence / f"{name}-aligned.wav"
        run("-ss", 5, "-i", handle, "-t", duration, "-c:a", "pcm_s16le", path)
        mono.append(path)
    mix = sync["mix"]
    left, right = mix["left"], mix["right"]
    filters = (
        f"[0:a]volume={mix['machine_gain']}[m];"
        f"[1:a]volume={mix['csboy_gain']}[c];"
        "[m][c]join=inputs=2:channel_layout=stereo:map=0.0-FL|1.0-FR[j];"
        f"[j]pan=stereo|c0={left['machine']}*c0+{left['csboy']}*c1|"
        f"c1={right['machine']}*c0+{right['csboy']}*c1[out]"
    )
    run("-i", mono[0], "-i", mono[1], "-filter_complex", filters,
        "-map", "[out]", "-ar", mix["sample_rate"], "-c:a", "pcm_s16le",
        PROJECT / sync["audio_asset"])
    run("-ss", sync["picture_start"], "-i", ROOT / sync["picture_source"],
        "-t", duration, "-an", "-vf", "scale=1920:1080,fps=30",
        "-c:v", "libx264", "-preset", "fast", "-crf", 18,
        "-g", 30, "-keyint_min", 30, "-sc_threshold", 0,
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        PROJECT / sync["picture_asset"])
    run("-i", PROJECT / sync["picture_asset"], "-i", PROJECT / sync["audio_asset"],
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "256k", "-t", duration,
        "-movflags", "+faststart", PROJECT / sync["preview"])
    print("Built 12-second aligned highlight and stereo commentary; handles retained locally.")


if __name__ == "__main__":
    build()
