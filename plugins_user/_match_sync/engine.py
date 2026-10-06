"""Bounded media history and conservative scene matching; no network or GUI."""
from __future__ import annotations

import math
import threading
from array import array
from bisect import bisect_left
from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import median

try:
    import numpy as np
except ImportError:
    np = None

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
    feature: bytes = b""


@dataclass(frozen=True)
class Match:
    lag: float | None
    confidence: float
    reason: str
    refined: bool = False
    playback_error: float | None = None
    candidates: tuple[float, ...] = ()


def match_scenes(reference: list[Sample], other: list[Sample]) -> Match:
    """Positive lag means the other feed receives the same scene later."""
    if len(reference) < 8 or len(other) < 8:
        return Match(None, 0, "正在收集比赛画面")
    dynamics = []
    for samples in (reference, other):
        dynamic = 0
        for sample in samples[1:]:
            dynamic |= sample.signature ^ samples[0].signature
        dynamics.append(dynamic)
    # Ignore moving overlays whose positions never change in the other feed.
    dynamic = dynamics[0] & dynamics[1]
    bits = dynamic.bit_count()
    if bits < 16:
        return Match(None, 0, "框选区域变化不足；可扩大比赛区域或对照微调")
    groups = defaultdict(list)
    appearance_distances = None
    if np is not None and all(s.feature and len(s.feature) == 256 for s in reference + other):
        a_features = np.frombuffer(b"".join(s.feature for s in reference), dtype=np.uint8).reshape(-1, 16, 16)[:, ::4, ::4].reshape(-1, 16).astype(np.int16)
        b_features = np.frombuffer(b"".join(s.feature for s in other), dtype=np.uint8).reshape(-1, 16, 16)[:, ::4, ::4].reshape(-1, 16).astype(np.int16)
        appearance_distances = np.abs(a_features[:, None, :] - b_features[None, :, :]).mean(axis=2) / 128
    for ai, a in enumerate(reference):
        if a.texture < 4:
            continue
        for bi, b in enumerate(other):
            if b.texture < 4:
                continue
            distance = ((a.signature ^ b.signature) & dynamic).bit_count() / bits
            if appearance_distances is not None:
                distance = min(distance, float(appearance_distances[ai, bi]))
            if distance <= 0.20:
                lag = b.time - a.time
                if abs(lag) <= HISTORY_SECONDS - 5:
                    key = round(lag * 2)
                    # Overlapping buckets keep jitter at a half-second edge together.
                    for nearby in (key - 1, key, key + 1):
                        groups[nearby].append((a, b, distance, lag))
    ranked = []
    for key, pairs in groups.items():
        lag = median(p[3] for p in pairs)
        end = min(reference[-1].time, other[-1].time - lag)
        pairs = [p for p in pairs if abs(p[3] - lag) <= .35 and p[0].time >= end - 8]
        if not pairs:
            continue
        # Each frame contributes once; require an ordered sequence, not isolated hits.
        used_a, used_b = set(), set()
        sequence = []
        for pair in sorted(pairs, key=lambda p: p[2]):
            if pair[0].time not in used_a and pair[1].time not in used_b:
                used_a.add(pair[0].time)
                used_b.add(pair[1].time)
                sequence.append(pair)
        pairs = sorted(sequence, key=lambda p: p[0].time)
        if any(b[1].time <= a[1].time for a, b in zip(pairs, pairs[1:])):
            continue
        # A static screen or repeated near-identical frames cannot establish time.
        unique_a = {pair[0].signature for pair in pairs}
        unique_b = {pair[1].signature for pair in pairs}
        support = min(len(unique_a), len(unique_b))
        recent = min(reference[-1].time - max(p[0].time for p in pairs),
                     other[-1].time - max(p[1].time for p in pairs))
        if support < 6 or recent > 1.5 or pairs[-1][0].time - pairs[0][0].time < 2.5:
            continue
        distance = sum(p[2] for p in pairs) / len(pairs)
        # Reward precise matches much more than a large number of vaguely
        # similar scoreboards; static graphics otherwise dominate the vote.
        ranked.append((support * math.exp(-24 * distance), key, support, distance, pairs))
    if not ranked:
        return Match(None, 0, "未找到共同的动态比赛画面；可扩大匹配区域或对照微调")
    ranked.sort(reverse=True, key=lambda item: item[0])
    score, key, support, distance, pairs = ranked[0]
    lag = median(p[3] for p in pairs)
    candidates = []
    if reference[0].feature and other[0].feature:
        for item in ranked:
            candidate = median(p[3] for p in item[4])
            if all(abs(candidate - existing) >= 1.5 for existing in candidates):
                candidates.append(candidate)
            if len(candidates) >= 8:
                break
    rival = next((item for item in ranked[1:] if abs(median(p[3] for p in item[4]) - lag) >= .75), None)
    if rival and rival[0] >= score * 0.85:
        return Match(None, 0, "画面存在重复或回放，时间差不明确", candidates=tuple(candidates))
    confidence = min(1.0, support / 10) * (1 - distance)
    return Match(lag, confidence, "已匹配共同比赛画面", candidates=tuple(candidates))


def refine_match(match: Match, reference: list[Sample], other: list[Sample]) -> Match:
    """Refine a coarse candidate using recent ordered, normalized grayscale scenes."""
    if np is None:
        return Match(None, 0, "缺少精校正组件 NumPy，请更新 requirements.txt 中的依赖")
    if match.candidates:
        results = [refine_match(Match(candidate, .9, "粗匹配候选"), reference, other)
                   for candidate in match.candidates]
        results = sorted((result for result in results if result.lag is not None),
                         key=lambda result: result.confidence, reverse=True)
        if not results:
            return Match(None, 0, "粗匹配候选未通过精校正，保持已确认偏移")
        rival = next((result for result in results[1:] if abs(result.lag - results[0].lag) >= .15), None)
        if rival and rival.confidence >= results[0].confidence - .025:
            return Match(None, 0, "连续画面存在多个相近时间差，保持已确认偏移")
        return results[0]
    if match.lag is None:
        return match
    if len(reference) < 40 or len(other) < 40:
        return Match(None, 0, "正在收集精校正画面")
    lag = match.lag
    end = min(reference[-1].time, other[-1].time - lag)
    begin = max(end - 4, reference[0].time, other[0].time - lag)
    a = [sample for sample in reference if begin <= sample.time <= end and sample.texture >= 4]
    b = [sample for sample in other if end - 5 + lag <= sample.time <= end + 1 + lag and sample.texture >= 4]
    if len(a) < 30 or len(b) < 30 or not a[0].feature or not b[0].feature:
        return Match(None, 0, "共同动态画面不足，保持已确认偏移")
    if a[-1].time - a[0].time < 2:
        return Match(None, 0, "精校正需要连续比赛画面")
    length = len(a[0].feature)
    if any(len(sample.feature) != length for sample in a + b):
        return Match(None, 0, "比赛区域已变化，正在重新收集")
    a_features = np.frombuffer(b"".join(s.feature for s in a), dtype=np.uint8).reshape(-1, length).astype(np.int16)
    b_features = np.frombuffer(b"".join(s.feature for s in b), dtype=np.uint8).reshape(-1, length).astype(np.int16)
    active = (np.ptp(a_features, axis=0) >= 12) & (np.ptp(b_features, axis=0) >= 12)
    if np.count_nonzero(active) < 16:
        return Match(None, 0, "比赛区域变化不足，保持已确认偏移")
    distances = np.abs(a_features[:, None, active] - b_features[None, :, active]).mean(axis=2) / 128
    times = [sample.time for sample in b]
    ranked = []
    # 25ms search steps, with support from many frames rather than one best pair.
    for step in range(-40, 41):
        candidate = lag + step * .025
        pairs = []
        used = set()
        for ai, sample in enumerate(a):
            index = bisect_left(times, sample.time + candidate)
            choices = [i for i in (index - 1, index) if 0 <= i < len(b)]
            if not choices:
                continue
            index = min(choices, key=lambda i: abs(times[i] - sample.time - candidate))
            if index in used or abs(times[index] - sample.time - candidate) > .055:
                continue
            used.add(index)
            target = b[index]
            distance = float(distances[ai, index])
            pairs.append((sample, target, distance))
        if len(pairs) < max(30, len(a) * .8):
            continue
        errors = [pair[2] for pair in pairs]
        score = sum(errors) / len(errors)
        # Both halves must agree; transitions or replay boundaries cannot lock.
        middle = len(pairs) // 2
        halves = [sum(p[2] for p in part) / len(part) for part in (pairs[:middle], pairs[middle:])]
        if max(halves) > .20:
            continue
        ranked.append((score, candidate, pairs))
    if not ranked:
        return Match(None, 0, "精校正尚未确认，保持已确认偏移")
    ranked.sort(key=lambda item: item[0])
    score, lag, pairs = ranked[0]
    rival = next((item for item in ranked[1:] if abs(item[1] - lag) >= .2), None)
    if score > .15 or (rival is not None and rival[0] <= score + .025):
        return Match(None, 0, "精校正时间差不明确，保持已确认偏移")
    # The sample timestamps refine the grid centre without inventing sub-frame time.
    precise = median(right.time - left.time for left, right, distance in pairs if distance <= .20)
    confidence = min(1.0, len(pairs) / 60) * max(0, 1 - score)
    return Match(precise, confidence, "已精校正共同比赛画面", refined=True)


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

    def append_at(self, start: int, pcm: bytes) -> None:
        """Place native PCM by PTS, keeping gaps silent and trimming overlaps."""
        with self.lock:
            if start > self.end:
                gap = start - self.end
                if gap >= self.capacity:
                    self.data[:] = bytes(len(self.data))
                    self.end = start
                else:
                    self.append(bytes(gap * 4))
            overlap = max(0, self.end - start)
            self.append(pcm[min(len(pcm), overlap * 4):])

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
        self.manual_locked = False

    def select_reference(self, room_id: str) -> None:
        origin = self.lags.get(room_id, 0)
        self.lags = {key: value - origin for key, value in self.lags.items()}
        self.lags[room_id] = 0
        self.reference = room_id
        self.candidates.clear()

    def accept(self, room_id: str, match: Match) -> bool:
        if self.manual_locked:
            return False
        if match.lag is None or not math.isfinite(match.lag) or match.confidence < .65:
            self.candidates.pop(room_id, None)
            return False
        previous, count = self.candidates.get(room_id, (match.lag, 0))
        count = count + 1 if abs(previous - match.lag) <= (.15 if match.refined else .6) else 1
        self.candidates[room_id] = (match.lag, count)
        if count >= 2:
            current = self.lags.get(room_id)
            if match.refined and current is not None and abs(match.lag - current) <= .2:
                self.lags[room_id] = current + (match.lag - current) * .5
            else:
                self.lags[room_id] = match.lag
            return True
        return False

    def shifts(self, delays: dict[str, float]) -> dict[str, float]:
        lags = self.lags if self.automatic or self.manual_locked else {}
        positions = {key: lags.get(key, 0) - delay for key, delay in delays.items()}
        slowest = max([0.0] + [lags.get(key, 0) for key in delays] + list(positions.values()))
        # The slowest source stays at least two seconds behind its decoder.
        return {key: position - slowest - 2.0 for key, position in positions.items()}
