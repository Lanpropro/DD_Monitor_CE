"""Prepare local footage derivatives for the editable HTML promo sample."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "videos/dd-monitor-ce-plugins-promo"


def cut(source, target, start, duration, loop=False):
    output = PROJECT / "assets" / target
    command = ["ffmpeg", "-y", "-v", "error"]
    if loop:
        command += ["-stream_loop", "-1"]
    command += ["-ss", str(start), "-i", str(ROOT / source), "-t", str(duration),
                "-an", "-vf", "scale=1920:1080:flags=lanczos,fps=30,setsar=1",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    subprocess.run(command, check=True)
    return {"asset": target, "source": source, "source_start": start,
            "duration": duration, "looped": loop}


def assemble_global_cells():
    selections = json.loads((PROJECT / "cell-selections.json").read_text(encoding="utf-8"))
    positions = [(200,14),(772,14),(1344,14),(200,360),(772,360),
                 (1344,360),(200,708),(772,708),(1344,708)]
    for selection, (x, y) in zip(selections, positions):
        target = PROJECT / "assets" / f"global-cell-{selection['cell']+1}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-threads", "2", "-ss",
                        str(selection["start"]), "-i", str(ROOT / selection["source"]),
                        "-t", "6.06", "-an", "-vf",
                        f"scale=1920:1080:flags=lanczos,crop=562:344:{x}:{y},fps=30,setsar=1",
                        "-c:v", "libx264", "-threads", "2", "-preset", "fast", "-crf", "20",
                        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)], check=True)
    command = ["ffmpeg", "-y", "-v", "error", "-threads", "2", "-ss", "30", "-i",
               str(ROOT / "Video_reference/海外平台九格增补.mp4")]
    for selection in selections:
        command += ["-threads", "2", "-i", str(PROJECT / "assets" /
                    f"global-cell-{selection['cell']+1}.mp4")]
    filters = ["[0:v]scale=1920:1080,fps=30,setsar=1[base]"]
    for i, (x, y) in enumerate(positions):
        previous = "base" if i == 0 else f"mix{i}"
        filters.append(f"[{previous}][{i+1}:v]overlay={x}:{y}:shortest=1[mix{i+1}]")
    command += ["-filter_complex", ";".join(filters), "-map", "[mix9]", "-an", "-t", "6.06",
                "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "20",
                "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(PROJECT / "assets/global-stitched.mp4")]
    subprocess.run(command, check=True)
    return {"asset": "global-stitched.mp4", "method": "nine independently selected ranges",
            "duration": 6.06, "selections": selections}


def assemble_domestic_cells():
    selections = json.loads((PROJECT / "domestic-cell-selections.json").read_text(encoding="utf-8"))
    for selection in selections:
        crop = ":".join(map(str, selection["crop"]))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(selection["start"]),
                        "-i", str(ROOT / selection["source"]), "-t", str(selection["duration"]),
                        "-an", "-vf", f"scale=1920:1080:flags=lanczos,crop={crop},fps=30,setsar=1",
                        "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "20",
                        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        str(PROJECT / "assets" / selection["asset"])], check=True)
    command = ["ffmpeg", "-y", "-v", "error", "-i", str(PROJECT / "assets/domestic-apex.mp4")]
    for selection in selections:
        command += ["-i", str(PROJECT / "assets" / selection["asset"])]
    filters = []
    for i, selection in enumerate(selections):
        previous = "0:v" if i == 0 else f"mix{i}"
        x, y = selection["position"]
        filters.append(f"[{previous}][{i+1}:v]overlay={x}:{y}:shortest=1[mix{i+1}]")
    command += ["-filter_complex", ";".join(filters), "-map", "[mix2]", "-an", "-t", "16.4",
                "-c:v", "libx264", "-threads", "4", "-preset", "fast", "-crf", "20",
                "-g", "30", "-keyint_min", "30", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(PROJECT / "assets/domestic-apex-v6.mp4")]
    subprocess.run(command, check=True)
    return {"asset": "domestic-apex-v6.mp4", "source": "Video_reference/国内apex 1+5.mp4",
            "source_start": 0, "duration": 16.4, "looped": False,
            "method": "Replace two stalled lower panes with recorded smooth ranges",
            "selections": selections}


def main():
    (PROJECT / "assets").mkdir(parents=True, exist_ok=True)
    sources = [
        cut("Video_reference/国内apex 1+5.mp4", "domestic-apex.mp4", 0, 16.4),
        assemble_domestic_cells(),
        cut("Video_reference/海外平台九格增补.mp4", "global.mp4", 10, 8),
        cut("Video_reference/二路直播对齐.mp4", "align-compare.mp4", 8, 6),
        cut("Video_reference/二路直播对齐.mp4", "align-result.mp4", 16, 6),
        cut("Video_reference/二路同播cs.mp4", "match-reveal.mp4", 4, 5),
        cut("Video_reference/二路同播cs.mp4", "match-result.mp4", 9, 4),
        cut("Video_reference/双人精彩时刻.mp4", "danmaku.mp4", 22, 8),
        cut("Video_reference/二路直播对齐.mp4", "match-continuous.mp4", 6, 28),
        assemble_global_cells(),
    ]
    (PROJECT / "sources.json").write_text(json.dumps(sources, ensure_ascii=False,
                                                  indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
