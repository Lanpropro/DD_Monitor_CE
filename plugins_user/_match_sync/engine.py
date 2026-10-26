"""Bounded media history and conservative scene matching; no network or GUI."""
from __future__ import annotations

import math
import threading
from array import array
from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import median

try:
    import numpy as np
except ImportError:
    np = None

try:
    import audioop
except ImportError:
    audioop = None


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
    evidence_end: float | None = None


def feature_distances(a, b):
    distances = np.empty((len(a), len(b)), dtype=np.float64)
    # Bound temporary memory for detailed timer features and long histories.
    for start in range(0, len(a), 16):
        distances[start:start + 16] = np.abs(a[start:start + 16, None, :] - b[None, :, :]).mean(axis=2) / 128
    return distances


def match_scenes(reference: list[Sample], other: list[Sample], *, focused=False) -> Match:
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
    length = len(reference[0].feature)
    features_ready = np is not None and length in (256, 1536, 6144) and all(len(s.feature) == length for s in reference + other)
    if bits < (8 if focused else 16) and not (focused and features_ready):
        return Match(None, 0, "框选区域变化不足；可扩大比赛区域或对照微调")
    groups = defaultdict(list)
    appearance_distances = None
    if features_ready:
        a_features = np.frombuffer(b"".join(s.feature for s in reference), dtype=np.uint8).reshape(-1, length).astype(np.int16)
        b_features = np.frombuffer(b"".join(s.feature for s in other), dtype=np.uint8).reshape(-1, length).astype(np.int16)
        if focused:
            active = (np.ptp(a_features, axis=0) >= 12) & (np.ptp(b_features, axis=0) >= 12)
            if np.count_nonzero(active) < 16:
                return Match(None, 0, "框选区域变化不足；请框选连续变化的数字并包含少量背景")
            appearance_distances = feature_distances(a_features[:, active], b_features[:, active])
        else:
            height, width = {256: (16, 16), 1536: (24, 64), 6144: (48, 128)}[length]
            a_features = a_features.reshape(-1, height, width)[:, ::height // 4, ::width // 4].reshape(-1, 16)
            b_features = b_features.reshape(-1, height, width)[:, ::height // 4, ::width // 4].reshape(-1, 16)
            appearance_distances = feature_distances(a_features, b_features)
    if appearance_distances is not None:
        a_bits = np.frombuffer(b"".join(s.signature.to_bytes(64, "little") for s in reference), dtype=np.uint8).reshape(-1, 64)
        b_bits = np.frombuffer(b"".join(s.signature.to_bytes(64, "little") for s in other), dtype=np.uint8).reshape(-1, 64)
        mask = np.frombuffer(dynamic.to_bytes(64, "little"), dtype=np.uint8)
        distances = (appearance_distances if focused else
                     np.minimum(appearance_distances, np.bitwise_count((a_bits[:, None, :] ^ b_bits[None, :, :]) & mask).sum(axis=2) / bits))
        lags = np.array([s.time for s in other])[None, :] - np.array([s.time for s in reference])[:, None]
        eligible = (distances <= .20) & (np.abs(lags) <= HISTORY_SECONDS - 5)
        if not focused:
            eligible &= np.array([s.texture >= 4 for s in reference])[:, None]
            eligible &= np.array([s.texture >= 4 for s in other])[None, :]
        indices = np.nonzero(eligible)
        comparisons = ((reference[ai], other[bi], float(distances[ai, bi])) for ai, bi in zip(*indices))
    else:
        comparisons = ((a, b, ((a.signature ^ b.signature) & dynamic).bit_count() / bits)
                       for a in reference if a.texture >= 4 for b in other if b.texture >= 4)
    for a, b, distance in comparisons:
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
        unique_a = {pair[0].feature if focused and features_ready else pair[0].signature for pair in pairs}
        unique_b = {pair[1].feature if focused and features_ready else pair[1].signature for pair in pairs}
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
        if focused:
            return Match(None, 0, "正在收集框选区域的连续变化；两路请只框选相同计时数字并保留少量背景")
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


def assisted_match(lag: float, reference: list[Sample], other: list[Sample], *, focused=False) -> Match:
    """Use a human estimate to restrict, rather than bypass, scene verification."""
    return refine_match(Match(None, 0, "人工辅助搜索", candidates=tuple(lag + step * 1.5 for step in range(-2, 3))),
                        reference, other, focused=focused)


def refine_match(match: Match, reference: list[Sample], other: list[Sample], *, focused=False) -> Match:
    """Refine a coarse candidate using recent ordered, normalized grayscale scenes."""
    if np is None:
        return Match(None, 0, "缺少精校正组件 NumPy，请更新 requirements.txt 中的依赖")
    if match.candidates:
        results = [refine_match(Match(candidate, .9, "粗匹配候选"), reference, other, focused=focused)
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
    begin = max(end - (8 if focused else 4), reference[0].time, other[0].time - lag)
    a = [sample for sample in reference if begin <= sample.time <= end and (sample.texture >= 4 or focused and sample.feature)]
    b = [sample for sample in other if begin - 1 + lag <= sample.time <= end + 1 + lag and (sample.texture >= 4 or focused and sample.feature)]
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
    distances = feature_distances(a_features[:, active], b_features[:, active])
    a_times, b_times = np.array([s.time for s in a]), np.array([s.time for s in b])
    if focused:
        # Timer digits hold for a second: their transitions, rather than the
        # repeated still frames, establish sub-second timing in an explicit ROI.
        changes = np.flatnonzero(np.abs(np.diff(a_features[:, active], axis=0)).mean(axis=1) / 128 >= .04)
        if len(changes) < 3:
            return Match(None, 0, "框选区域变化不足；请确认数字连续变化，两路框选相同数字并保留少量背景")
        if len(changes) < len(a) * .2:
            if len({sample.feature for sample in a}) < 6:
                return Match(None, 0, "正在收集计时器连续变化；至少需要六个不同读数")
            edges = np.unique(np.clip((changes[:, None] + np.arange(-1, 4)).ravel(), 0, len(a) - 1))
            distances, a_times, a_features = distances[edges], a_times[edges], a_features[edges]
            a = [a[index] for index in edges]
    candidates = lag + np.arange(-40, 41) * .025
    wanted = a_times[None, :] + candidates[:, None]
    right = np.searchsorted(b_times, wanted)
    left, right = np.clip(right - 1, 0, len(b) - 1), np.clip(right, 0, len(b) - 1)
    indices = np.where(np.abs(b_times[left] - wanted) <= np.abs(b_times[right] - wanted), left, right)
    valid = np.abs(b_times[indices] - wanted) <= .055
    unique = np.ones_like(valid)
    unique[:, 1:] = (np.diff(indices, axis=1) != 0) | ~valid[:, :-1]
    valid &= unique
    counts = valid.sum(axis=1)
    errors = distances[np.arange(len(a))[None, :], indices]
    scores = (errors * valid).sum(axis=1) / np.maximum(1, counts)
    # Both ordered halves must agree; keep the same one-to-one support guards.
    first = valid & (np.cumsum(valid, axis=1) <= counts[:, None] // 2)
    second = valid & ~first
    halves = np.maximum((errors * first).sum(axis=1) / np.maximum(1, first.sum(axis=1)),
                        (errors * second).sum(axis=1) / np.maximum(1, second.sum(axis=1)))
    admitted = (counts >= max(12 if focused else 30, len(a) * .8)) & (halves <= .20)
    scores = np.where(admitted, scores, np.inf)
    best = int(np.argmin(scores))
    score = float(scores[best])
    if not np.isfinite(score):
        return Match(None, 0, "精校正尚未确认，保持已确认偏移")
    rivals = scores[np.abs(candidates - candidates[best]) >= .2]
    if score > .15 or (len(rivals) and float(rivals.min()) <= score + .025):
        return Match(None, 0, "精校正时间差不明确，保持已确认偏移")
    # The sample timestamps refine the grid centre without inventing sub-frame time.
    good = valid[best] & (errors[best] <= .20)
    if length == 256 and not focused:
        grid = np.arange(256).reshape(16, 16)
        regions = [grid[y:y + 8, x:x + 8].ravel() for y in (0, 8) for x in (0, 8)]
        supported = 0
        for region in regions:
            area = region[active[region]]
            if len(area) >= 8:
                error = np.abs(a_features[good][:, area] - b_features[indices[best, good]][:, area]).mean() / 128
                supported += error <= .20
        if supported < 2:
            return Match(None, 0, "共同比赛区域不足；请框选比赛画面，避开局部动画")
    precise = float(np.median(b_times[indices[best, good]] - a_times[good]))
    confidence = min(1.0, int(counts[best]) / (30 if focused else 60)) * max(0, 1 - score)
    return Match(precise, confidence, "已精校正共同比赛画面", refined=True, evidence_end=float(a_times[-1]))


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

    def bounds_at(self, timestamp):
        return self.bounds()

    def snapshots(self) -> list[Sample]:
        with self.lock:
            return list(self.samples)

    def pcm_at(self, timestamp: float, frames: int) -> bytes:
        origin = self.origin
        if origin is None:
            return bytes(frames * 4)
        return self.audio.read(round((timestamp - origin) * RATE), frames)


def route_pcm_s16_stereo(data: bytes, channel: int) -> bytes:
    """把立体声混成单声道，只放到指定的物理输出侧。"""
    if channel not in (3, 4):
        return data                     # 不路由就原样返回，一个字节都不用动
    if len(data) % 4:
        raise ValueError("stereo S16 PCM must contain complete frames")

    if audioop is not None:
        mono = audioop.tomono(data, 2, 0.5, 0.5)          # 左右各半 → 单声道
        return audioop.tostereo(mono, 2,
                                1.0 if channel == 3 else 0.0,
                                1.0 if channel == 4 else 0.0)

    output = bytearray(len(data))
    source = memoryview(data).cast("h")
    target = memoryview(output).cast("h")
    for index in range(0, len(source), 2):
        mono = (int(source[index]) + int(source[index + 1])) // 2
        if channel == 3:
            target[index] = mono
        else:
            target[index + 1] = mono
    return bytes(output)


def mix_pcm(inputs: list[tuple[bytes, int]], frames: int) -> bytes:
    """Linear per-room volumes, shared headroom, and a single final clamp."""
    enabled = [(pcm, max(0, min(100, volume)) / 100)
               for pcm, volume in inputs if volume > 0]
    if not enabled:
        return bytes(frames * 4)
    headroom = max(1.0, sum(gain for _pcm, gain in enabled))
    if np is not None:
        output = np.zeros(frames * 2, dtype=np.float64)
        for pcm, gain in enabled:
            samples = np.frombuffer(pcm, dtype=np.int16)
            output[:len(samples)] += samples.astype(np.float64) * gain / headroom
        return np.clip(np.rint(output), -32768, 32767).astype(np.int16).tobytes()
    output = [0.0] * (frames * 2)
    for pcm, gain in enabled:
        samples = memoryview(pcm).cast("h")
        for index, sample in enumerate(samples):
            output[index] += sample * gain / headroom
    return array("h", (max(-32768, min(32767, round(value)))
                       for value in output)).tobytes()


class SafetyBuffer:
    """Bounded jitter target; playback reaches it through gradual clock changes."""
    def __init__(self):
        self.target = 6.0
        self.arrivals = {}
        self.gaps = deque(maxlen=240)
        self.last_change = None

    def observe(self, key, arrival, fps):
        previous = self.arrivals.get(key)
        if arrival and (previous is None or arrival > previous):
            self.arrivals[key] = arrival
            if previous is not None:
                self.gaps.append(max(0.0, arrival - previous - 1 / max(1, fps)))

    def rate(self, now, available, minimum=0.0):
        dt = max(0, min(1, now - self.last_change)) if self.last_change is not None else 0
        self.last_change = now
        if len(self.gaps) >= 30:
            ordered = sorted(self.gaps)
            desired = max(4.0, min(8.0, 4.0 + 2 * ordered[int((len(ordered) - 1) * .95)]))
            self.target = desired if desired > self.target else max(desired, self.target - .02 * dt)
        error = available - max(self.target, minimum)
        return 1.0 if abs(error) <= .1 else max(.98, min(1.01, 1 + error * .01))


class LateBuffer:
    """Build limited common headroom through gentle playback, never a seek."""
    reserve_seconds = 2.0
    max_seconds = 240

    def __init__(self, reserve_seconds=2.0):
        self.reserve_seconds = reserve_seconds
        self.floor = 0.0
        self.since = {}
        self.failed = {}
        self.blocked = set()
        self.rooms = set()
        self.started = None
        self.initial_gaps = {}
        self.deadline = 0.0
        self.retry_after = 0.0
        self.limited = set()

    @property
    def building(self):
        return self.started is not None

    def update(self, now, ahead, capacity, deficits):
        late = {key: gap for key, gap in deficits.items() if gap > .05}
        short = {key: gap for key, gap in deficits.items() if gap > -self.reserve_seconds + .5}
        self.since = {key: self.since.get(key, now) for key in short}
        self.failed = {key: gap for key, gap in self.failed.items()
                       if key in late and late[key] >= gap - .5}
        persistent = {key: short[key] for key in short if now - self.since[key] >= 5}
        self.blocked = {key for key, gap in persistent.items()
                        if gap > .05 and (gap + .5 > .02 * 120 or ahead + gap + .5 > capacity or key in self.failed)}
        self.limited = {key for key, gap in persistent.items()
                        if key not in self.blocked and ahead + gap + self.reserve_seconds > capacity}
        if self.building:
            self.rooms.intersection_update(deficits)
            gap = max((deficits[key] for key in self.rooms), default=-self.reserve_seconds)
            growing = {key for key in self.rooms if now - self.started >= 15
                       and deficits[key] > .05 and deficits[key] > self.initial_gaps[key] + .5}
            exhausted = (self.floor > capacity or now >= self.deadline or bool(growing)
                         or ahead >= self.floor - .1 and gap > .05)
            if exhausted:
                limited = {key for key in self.rooms if ahead + deficits[key] + self.reserve_seconds > capacity}
                self.failed.update({key: late[key] for key in (growing or limited or self.rooms) if key in late})
                self.blocked.update(self.failed)
            if not self.rooms or exhausted or ahead >= self.floor - .1:
                # Preserve acquired headroom; do not speed back towards the
                # former live edge when a slow feed is finally admitted.
                self.floor = max(0, min(self.floor, ahead))
                self.started = None
                self.rooms.clear()
                self.retry_after = now + 20
        eligible = set(persistent) - self.blocked
        eligible = {key for key in eligible if now >= self.retry_after or persistent[key] > .05}
        if not self.building and eligible:
            self.rooms = eligible
            self.initial_gaps = {key: persistent[key] for key in eligible}
            self.floor = max(self.floor, ahead + max(self.initial_gaps.values()) + self.reserve_seconds)
            self.deadline = now + max(self.max_seconds, (max(self.initial_gaps.values()) + self.reserve_seconds) / .02 + 30)
            self.started = now
        self.floor = max(0, min(self.floor, capacity))
        return self.building


def resample_pcm(pcm, frames):
    """Small shared audio/video speed changes; stereo and frame count retained."""
    source = np.frombuffer(pcm, dtype=np.int16).reshape(-1, 2)
    if len(source) == frames:
        return pcm
    positions = np.arange(frames) * len(source) / frames
    left = np.minimum(positions.astype(np.int64), len(source) - 1)
    right = np.minimum(left + 1, len(source) - 1)
    weight = (positions - left)[:, None]
    mixed = source[left].astype(np.float64) * (1 - weight) + source[right] * weight
    return np.clip(np.rint(mixed), -32768, 32767).astype(np.int16).tobytes()


class Alignment:
    def __init__(self):
        self.reference = ""
        self.lags: dict[str, float] = {}
        self.candidates: dict[str, tuple[float, int]] = {}
        self.automatic = True
        self.manual_locked = False
        self.buffer_seconds = 2.0

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
                # Small tracking jitter must stay inside the picture prefetch,
                # rather than repeatedly seeking backwards through a full GOP.
                self.lags[room_id] = current + max(-.025, min(.025, (match.lag - current) * .5))
            else:
                self.lags[room_id] = match.lag
            return True
        return False

    def shifts(self, delays: dict[str, float]) -> dict[str, float]:
        lags = self.lags if self.automatic or self.manual_locked else {}
        positions = {key: lags.get(key, 0) - delay for key, delay in delays.items()}
        slowest = max([0.0] + [lags.get(key, 0) for key in delays] + list(positions.values()))
        # The slowest source stays at least two seconds behind its decoder.
        return {key: position - slowest - self.buffer_seconds for key, position in positions.items()}
