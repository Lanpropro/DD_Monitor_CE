"""Check the real footage and channel routing used by v3 beat 04."""

import json
import subprocess
import wave
from html.parser import HTMLParser
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
HTML = PROJECT / "compositions" / "v3" / "18-04-audio.html"


class MediaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.page = None
        self.pages = {}
        self.videos = {}
        self.audio = {}
        self.root = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") == "root":
            self.root = values
        if tag == "div" and values.get("id") in {"grid-page", "left-page", "right-page"}:
            self.page = values["id"]
            self.pages[self.page] = None
        if tag == "video" and self.page:
            assert self.pages[self.page] is None, f"multiple videos in {self.page}"
            self.pages[self.page] = values["src"]
            self.videos[values["id"]] = values
        if tag == "audio":
            self.audio[values["id"]] = values

    def handle_endtag(self, tag):
        if tag == "div" and self.page:
            self.page = None


def duration(path):
    result = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        text=True,
    )
    return float(json.loads(result)["format"]["duration"])


def frame(path, time, crop=None):
    filters = ([f"crop={crop}"] if crop else []) + ["scale=64:36", "format=gray"]
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(time), "-i", str(path),
        "-frames:v", "1", "-vf", ",".join(filters), "-f", "rawvideo", "-",
    ])


def keyframe_times(path):
    output = subprocess.check_output([
        "ffprobe", "-v", "error", "-skip_frame", "nokey", "-show_entries",
        "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path),
    ], text=True)
    return [float(line.rstrip(",")) for line in output.splitlines() if line]


def channel_peak(path, channel):
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        samples = memoryview(wav.readframes(wav.getnframes())).cast("h")
        return max(abs(sample) for sample in samples[channel::2])


def window_peak(path, start, seconds):
    with wave.open(str(path), "rb") as wav:
        wav.setpos(int(start * wav.getframerate()))
        samples = memoryview(wav.readframes(int(seconds * wav.getframerate()))).cast("h")
        return max(abs(sample) for sample in samples)


def main():
    parser = MediaParser()
    parser.feed(HTML.read_text(encoding="utf-8"))
    assert parser.pages == {
        "grid-page": "assets/rec/audio-grid-live.mp4",
        "left-page": "assets/rec/audio-left-live.mp4",
        "right-page": "assets/rec/audio-right-live.mp4",
    }
    assert float(parser.root["data-duration"]) == 17
    assert duration(PROJECT / parser.pages["grid-page"]) >= 9
    assert duration(PROJECT / parser.pages["left-page"]) >= 9
    assert duration(PROJECT / parser.pages["right-page"]) >= 9
    for video in parser.videos.values():
        assert duration(PROJECT / video["src"]) >= float(video["data-duration"])
    for video in (parser.videos["left-video"], parser.videos["right-video"]):
        assert float(video["data-start"]) + float(video["data-duration"]) == float(parser.root["data-duration"])
        path = PROJECT / video["src"]
        assert sum(abs(a - b) for a, b in zip(frame(path, 7.6), frame(path, 8.5))) > 1000, f"{path.name} freezes before the transition"
        times = keyframe_times(path)
        assert max(b - a for a, b in zip(times, times[1:])) <= 1.05, f"{path.name} has sparse keyframes"
    assert sum(frame(PROJECT / parser.pages["left-page"], 7.5, "1200:700:170:70")) / (64 * 36) > 40, "left stream shows a loading blackout"
    assert len(parser.audio) == 3
    grid = parser.audio["grid-live-audio"]
    left = parser.audio["left-live-audio"]
    right = parser.audio["right-live-audio"]
    for audio in (grid, left, right):
        assert duration(PROJECT / audio["src"]) >= float(audio["data-duration"])
    grid_audio = PROJECT / grid["src"]
    for start in (0.7, 3.1, 5.5):
        assert window_peak(grid_audio, start, 0.5) > 0, f"silent grid operation at {start}s"
    assert float(grid["data-duration"]) >= 7.2
    assert left["data-start"] == right["data-start"], "left and right must start together"
    assert left["data-duration"] == right["data-duration"]
    assert float(right["data-duration"]) >= 4
    assert float(left["data-start"]) + float(left["data-duration"]) <= float(parser.root["data-duration"])
    assert channel_peak(PROJECT / left["src"], 0) > 0
    assert channel_peak(PROJECT / left["src"], 1) == 0
    assert channel_peak(PROJECT / right["src"], 0) == 0
    assert channel_peak(PROJECT / right["src"], 1) > 0
    print("v3 beat 04: extended grid sounds and simultaneous stereo pages verified")


if __name__ == "__main__":
    main()
