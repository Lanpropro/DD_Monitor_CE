"""Translate FFmpeg segment times into independent replay and danmaku positions."""
from bisect import bisect_right
from dataclasses import dataclass
import csv
import math
from pathlib import Path


def format_time(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


@dataclass(frozen=True)
class ReplayClip:
    path: Path
    duration: float
    captured_until: float


def replay_index_path(part):
    return part.with_name(part.stem.rsplit('_', 1)[0] + '.csv')


def completed_clips(parts):
    durations = {}
    for index in dict.fromkeys(map(replay_index_path, parts)):
        try:
            with index.open(encoding='utf-8', newline='') as handle:
                for row in csv.reader(handle):
                    if len(row) != 3:
                        continue
                    path, start, end = row
                    try:
                        duration = float(end) - float(start)
                    except ValueError:
                        continue  # A concurrent write can leave one incomplete line.
                    if math.isfinite(duration) and duration > 0:
                        durations[Path(path).name] = duration
        except FileNotFoundError:
            continue
    return tuple(ReplayClip(part, durations[part.name], part.stat().st_mtime)
                 for part in parts if part.name in durations)


class ReplayTimeline:
    def __init__(self, clips, previous=None):
        self.clips = clips
        self.offsets = []
        self.start = 0.0
        if previous and previous.clips and clips:
            first = clips[0]
            known = dict(zip((clip.path for clip in previous.clips), previous.offsets))
            if first.path in known:
                self.start = known[first.path]
            else:
                gap = first.captured_until - first.duration - previous.clips[-1].captured_until
                self.start = previous.end + max(0, gap)
        self.end = self.start
        for clip in clips:
            self.offsets.append(self.end)
            self.end += clip.duration

    def media_url(self):
        entries = []
        for clip in self.clips:
            path = clip.path.as_posix()
            entries.append(f'%{len(path.encode("utf-8"))}%{path},length={clip.duration:.6f}')
        return 'edl://' + ';'.join(entries)

    def frame_source(self, position):
        if not self.clips:
            return None
        index = max(0, bisect_right(self.offsets, position) - 1)
        clip = self.clips[index]
        return clip.path, min(max(0, position - self.offsets[index]), max(0, clip.duration - .15))

    def comments(self, events):
        # Match each event to the wall-clock interval of its captured segment. The
        # first matching boundary ends the interval, so gaps between inputs stay gaps.
        captured = sorted((clip.captured_until, offset, clip.duration)
                          for offset, clip in zip(self.offsets, self.clips))
        ends = [end for end, _offset, _duration in captured]
        comments = []
        for stamp, event in events:
            index = bisect_right(ends, stamp)
            if index < len(captured):
                end, offset, duration = captured[index]
                if stamp >= end - duration:
                    comments.append((offset + (stamp - (end - duration)), event))
        return sorted(comments, key=lambda item: item[0])
