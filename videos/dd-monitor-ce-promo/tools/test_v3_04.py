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
        self.audio = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "div" and values.get("id") in {"grid-page", "left-page", "right-page"}:
            self.page = values["id"]
            self.pages[self.page] = None
        if tag == "video" and self.page:
            assert self.pages[self.page] is None, f"multiple videos in {self.page}"
            self.pages[self.page] = values["src"]
        if tag == "audio":
            self.audio[values["id"]] = values["src"]

    def handle_endtag(self, tag):
        if tag == "div" and self.page:
            self.page = None


def duration(path):
    result = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        text=True,
    )
    return float(json.loads(result)["format"]["duration"])


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
    assert duration(PROJECT / parser.pages["grid-page"]) >= 7
    assert duration(PROJECT / parser.pages["left-page"]) >= 5
    assert duration(PROJECT / parser.pages["right-page"]) >= 5
    assert len(parser.audio) == 3
    grid_audio = PROJECT / parser.audio["grid-live-audio"]
    for start in (0.7, 2.4, 4.1):
        assert window_peak(grid_audio, start, 0.5) > 0, f"silent grid operation at {start}s"
    assert channel_peak(PROJECT / parser.audio["left-live-audio"], 0) > 0
    assert channel_peak(PROJECT / parser.audio["left-live-audio"], 1) == 0
    assert channel_peak(PROJECT / parser.audio["right-live-audio"], 0) == 0
    assert channel_peak(PROJECT / parser.audio["right-live-audio"], 1) > 0
    print("v3 beat 04: three real videos and left/right audio channels verified")


if __name__ == "__main__":
    main()
