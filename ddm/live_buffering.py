"""Bounded packet caching and refill recovery for high bitrate domestic streams."""
import math


BUFFERED_PROFILES = frozenset(('douyu', 'douyin'))


def cache_options(profile, *, silent=False):
    buffered = not silent and profile in BUFFERED_PROFILES
    return {'demuxer-max-bytes': '64MiB' if buffered else '16MiB',
            'cache-pause-initial': buffered,
            'cache-pause-wait': 3 if buffered else 1}


class RefillWatch:
    """Watch the video cache timestamp, not incoming audio bytes alone."""
    IDLE_TICKS = 6
    MAX_REFILL_TICKS = 20

    def __init__(self):
        self.reset()

    def reset(self):
        self.end = None
        self.idle_ticks = self.IDLE_TICKS

    def wait_limit(self, default, end):
        if not isinstance(end, (int, float)) or not math.isfinite(end):
            self.reset()
            return default
        if end > 0 and (self.end is None or end > self.end):
            self.idle_ticks = 0
        elif self.end is not None and end < self.end:
            self.idle_ticks = self.IDLE_TICKS
        else:
            self.idle_ticks += 1
        self.end = end
        return max(default, self.MAX_REFILL_TICKS) if self.idle_ticks < self.IDLE_TICKS else default
