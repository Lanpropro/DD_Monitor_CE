"""Bounded media history and conservative scene matching; no network or GUI."""
from __future__ import annotations

import math
import threading
from array import array
from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import median

RATE = 48_000
FPS = 30
HISTORY_SECONDS = 60
FRAME_BYTES_LIMIT = 96 * 1024 * 1024
SIGNATURE_BITS = 512


@dataclass(frozen=True)
class Sample:
    time: float
    signature: int
    texture: float


@dataclass(frozen=True)
class Match:
    lag: float | None
    confidence: float
    reason: str


def match_scenes(reference: list[Sample], other: list[Sample]) -> Match:
    """Positive lag means the other feed receives the same scene later."""
    if len(reference) < 10 or len(other) < 10:
        return Match(None, 0, "正在收集比赛画面")
    dynamic = 0
    for samples in (reference, other):
        for sample in samples[1:]:
            dynamic |= sample.signature ^ samples[0].signature
    bits = dynamic.bit_count()
    if bits < 16:
        return Match(None, 0, "框选区域变化不足；可扩大比赛区域或对照微调")
    groups = defaultdict(list)
    for a in reference:
        if a.texture < 4:
            continue
        for b in other:
            if b.texture < 4:
                continue
            distance = ((a.signature ^ b.signature) & dynamic).bit_count() / bits
            if distance <= 0.20:
                lag = b.time - a.time
                if abs(lag) <= HISTORY_SECONDS - 5:
                    groups[round(lag * 2)].append((a, b, distance, lag))
    ranked = []
    for key, pairs in groups.items():
        # A static screen or repeated near-identical frames cannot establish time.
        unique_a = {pair[0].signature for pair in pairs}
        unique_b = {pair[1].signature for pair in pairs}
        support = min(len(unique_a), len(unique_b))
        recent = min(reference[-1].time - max(p[0].time for p in pairs),
                     other[-1].time - max(p[1].time for p in pairs))
        if support < 6 or recent > 3:
            continue
        distance = sum(p[2] for p in pairs) / len(pairs)
        # Reward precise matches much more than a large number of vaguely
        # similar scoreboards; static graphics otherwise dominate the vote.
        ranked.append((support * math.exp(-24 * distance), key, support, distance, pairs))
    if not ranked:
        return Match(None, 0, "未找到共同的动态比赛画面；可扩大匹配区域或对照微调")
    ranked.sort(reverse=True, key=lambda item: item[0])
    score, key, support, distance, pairs = ranked[0]
    rival = next((item for item in ranked[1:] if abs(item[1] - key) >= 4), None)
    if rival and rival[0] >= score * 0.85:
        return Match(None, 0, "画面存在重复或回放，时间差不明确")
    confidence = min(1.0, support / 12) * (1 - distance)
    return Match(median(p[3] for p in pairs), confidence, "已匹配共同比赛画面")


class AudioRing:
    """Stereo S16 PCM indexed by media sample, with zero-filled missing ranges."""

    def __init__(self, seconds: float = HISTORY_SECONDS):
        self.capacity = max(1, int(seconds * RATE))
        self.data = bytearray(self.capacity * 4)
        self.end = 0
        self.lock = threading.RLock()

    def append(self, pcm: bytes) -> None:
        if len(pcm) % 4:
            raise ValueError("PCM must contain complete stereo frames")
        frames = len(pcm) // 4
        with self.lock:
            new_end = self.end + frames
            if frames > self.capacity:
                pcm = pcm[-self.capacity * 4:]
                frames = self.capacity
            start = (new_end - frames) % self.capacity * 4
            first = min(len(pcm), len(self.data) - start)
            self.data[start:start + first] = pcm[:first]
            self.data[:len(pcm) - first] = pcm[first:]
            self.end = new_end

    def read(self, start: int, frames: int) -> bytes:
        output = bytearray(frames * 4)
        with self.lock:
            begin = max(start, 0, self.end - self.capacity)
            end = min(start + frames, self.end)
            if end <= begin:
                return bytes(output)
            offset = begin % self.capacity * 4
            length = (end - begin) * 4
            first = min(length, len(self.data) - offset)
            target = (begin - start) * 4
            output[target:target + first] = self.data[offset:offset + first]
            output[target + first:target + length] = self.data[:length - first]
        return bytes(output)


class History:
    def __init__(self, seconds: float = HISTORY_SECONDS,
                 byte_limit: int = FRAME_BYTES_LIMIT):
        self.seconds = seconds
        self.byte_limit = byte_limit
        self.frames = deque()
        self.samples = deque()
        self.byte_size = 0
        self.origin: float | None = None
        self.lock = threading.RLock()
        self.audio = AudioRing(seconds)

    def append(self, timestamp: float, jpeg: bytes, sample: Sample | None = None):
        with self.lock:
            if self.origin is None:
                self.origin = timestamp
            self.frames.append((timestamp, jpeg))
            self.byte_size += len(jpeg)
            while self.frames and (self.byte_size > self.byte_limit or
                                  timestamp - self.frames[0][0] > self.seconds):
                self.byte_size -= len(self.frames.popleft()[1])
            if sample is not None:
                self.samples.append(sample)
            while self.samples and timestamp - self.samples[0].time > self.seconds:
                self.samples.popleft()

    def frame_at(self, timestamp: float) -> tuple[float, bytes] | None:
        with self.lock:
            if not self.frames or timestamp < self.frames[0][0]:
                return None
            if timestamp > self.frames[-1][0] + 1:
                return None
            return next((item for item in reversed(self.frames)
                         if item[0] <= timestamp), None)

    def latest(self) -> tuple[float, bytes] | None:
        with self.lock:
            return self.frames[-1] if self.frames else None

    def bounds(self) -> tuple[float, float] | None:
        with self.lock:
            return (self.frames[0][0], self.frames[-1][0]) if self.frames else None

    def snapshots(self) -> list[Sample]:
        with self.lock:
            return list(self.samples)

    def pcm_at(self, timestamp: float, frames: int) -> bytes:
        origin = self.origin
        if origin is None:
            return bytes(frames * 4)
        return self.audio.read(round((timestamp - origin) * RATE), frames)


def mix_pcm(inputs: list[tuple[bytes, int]], frames: int) -> bytes:
    """Linear per-room volumes, shared headroom, and a single final clamp."""
    enabled = [(pcm, max(0, min(100, volume)) / 100)
               for pcm, volume in inputs if volume > 0]
    if not enabled:
        return bytes(frames * 4)
    headroom = max(1.0, sum(gain for _pcm, gain in enabled))
    output = [0.0] * (frames * 2)
    for pcm, gain in enabled:
        samples = memoryview(pcm).cast("h")
        for index, sample in enumerate(samples):
            output[index] += sample * gain / headroom
    return array("h", (max(-32768, min(32767, round(value)))
                       for value in output)).tobytes()


class Alignment:
    def __init__(self):
        self.reference = ""
        self.lags: dict[str, float] = {}
        self.candidates: dict[str, tuple[float, int]] = {}
        self.automatic = True

    def select_reference(self, room_id: str) -> None:
        origin = self.lags.get(room_id, 0)
        self.lags = {key: value - origin for key, value in self.lags.items()}
        self.lags[room_id] = 0
        self.reference = room_id
        self.candidates.clear()

    def accept(self, room_id: str, match: Match) -> bool:
        if match.lag is None or not math.isfinite(match.lag):
            self.candidates.pop(room_id, None)
            return False
        previous, count = self.candidates.get(room_id, (match.lag, 0))
        count = count + 1 if abs(previous - match.lag) <= 0.6 else 1
        self.candidates[room_id] = (match.lag, count)
        if count >= 2:
            self.lags[room_id] = match.lag
            return True
        return False

    def shifts(self, delays: dict[str, float]) -> dict[str, float]:
        lags = self.lags if self.automatic else {}
        positions = {key: lags.get(key, 0) - delay for key, delay in delays.items()}
        slowest = max([0.0] + [lags.get(key, 0) for key in delays] + list(positions.values()))
        # The slowest source stays at least two seconds behind its decoder.
        return {key: position - slowest - 2.0 for key, position in positions.items()}
