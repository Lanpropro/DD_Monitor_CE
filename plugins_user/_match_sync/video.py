"""Original encoded video history and bounded, asynchronous native pictures."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
import threading
import time

from PySide6.QtGui import QImage

try:
    import av
except ImportError:
    av = None

from .engine import History, np


class StreamInput:
    """Windows subprocess pipes advertise seek() but cannot actually seek."""

    def __init__(self, pipe):
        self.pipe = pipe

    def read(self, size):
        return self.pipe.read(size)


def image_from_frame(frame):
    rgb = frame.reformat(format="bgra")
    plane = rgb.planes[0]
    if np is None:
        return QImage(bytes(plane), rgb.width, rgb.height, plane.line_size, QImage.Format_ARGB32).copy()
    image = QImage(rgb.width, rgb.height, QImage.Format_ARGB32)
    source = np.frombuffer(plane, dtype=np.uint8).reshape(rgb.height, plane.line_size)
    target = np.frombuffer(image.bits(), dtype=np.uint8).reshape(rgb.height, image.bytesPerLine())
    target[:, :rgb.width * 4] = source[:, :rgb.width * 4]
    return image


@dataclass(frozen=True)
class EncodedPacket:
    sequence: int
    data: bytes
    pts: int | None
    dts: int | None
    duration: int
    time_base: object
    keyframe: bool

    @property
    def time(self):
        return float((self.pts if self.pts is not None else self.dts or 0) * self.time_base)

    def decode_packet(self):
        packet = av.Packet(self.data)
        packet.pts, packet.dts = self.pts, self.dts
        packet.duration, packet.time_base = self.duration, self.time_base
        return packet


class VideoHistory(History):
    """Retain complete GOPs under the existing time/byte limits, without JPEG."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.packets = deque()
        self.codec = None
        self.sequence = 0
        self.received_frames = 0
        self.details = deque()
        self.pending_frames = deque()
        self.previous = None
        self.intervals = deque()

    def _track(self, timestamp):
        if not self.intervals or timestamp - self.intervals[-1][1] > .25:
            self.intervals.append([timestamp, timestamp])
        else:
            self.intervals[-1][1] = timestamp

    def segment_at(self, timestamp):
        if self.previous is not None:
            bounds = self.previous.bounds()
            if bounds and bounds[0] <= timestamp <= bounds[1] + .05:
                return self.previous
        bounds = super().bounds()
        if bounds and bounds[0] <= timestamp <= bounds[1] + .05:
            return self
        return None

    def bounds_at(self, timestamp):
        segment = self.segment_at(timestamp)
        if segment is not None and segment is not self:
            return segment.bounds_at(timestamp)
        with self.lock:
            bounds = super().bounds()
            if bounds is None:
                return None
            while self.intervals and self.intervals[0][1] < bounds[0]:
                self.intervals.popleft()
            for start, end in self.intervals:
                if timestamp <= end + .05:
                    return max(start, bounds[0]), min(end, bounds[1])
            return bounds

    def frame_at(self, timestamp):
        segment = self.segment_at(timestamp)
        if segment is not None and segment is not self:
            return segment.frame_at(timestamp)
        bounds = self.bounds_at(timestamp)
        if bounds is None or not bounds[0] <= timestamp <= bounds[1] + .05:
            return None
        return super().frame_at(timestamp)

    def pcm_at(self, timestamp, frames):
        segment = self.segment_at(timestamp)
        if segment is not None and segment is not self:
            return segment.pcm_at(timestamp, frames)
        return super().pcm_at(timestamp, frames)

    def trim_bytes(self, limit):
        with self.lock:
            while self.packets and self.byte_size > limit:
                self.byte_size -= len(self.packets.popleft().data)
                while self.packets and not self.packets[0].keyframe:
                    self.byte_size -= len(self.packets.popleft().data)
            first = self.packets[0].time + (self.origin or 0) if self.packets else float('inf')
            while self.frames and self.frames[0][0] < first:
                self.frames.popleft()

    def set_origin(self, origin):
        with self.lock:
            self.origin = origin
            self.frames.extend((origin + pts, pts) for pts in self.pending_frames)
            for timestamp, _pts in self.frames:
                self._track(timestamp)
            self.pending_frames.clear()
            self.samples = deque(replace(sample, time=origin + sample.time) for sample in self.samples)
            self.details = deque(replace(sample, time=origin + sample.time) for sample in self.details)

    def snapshots(self):
        return super().snapshots() if self.origin is not None else []

    def append_packet(self, packet):
        with self.lock:
            record = EncodedPacket(self.sequence, bytes(packet), packet.pts, packet.dts,
                                   packet.duration, packet.time_base, packet.is_keyframe)
            self.sequence += 1
            if not self.packets and not record.keyframe:
                return
            self.packets.append(record)
            self.byte_size += len(record.data)
            if self.previous is not None:
                self.previous.trim_bytes(max(0, self.byte_limit - self.byte_size))
            while self.packets and (self.byte_size > self.byte_limit or
                                    record.time - self.packets[0].time > self.seconds):
                self.byte_size -= len(self.packets.popleft().data)
                # A decoder cannot start in the middle of an inter-frame GOP.
                while self.packets and not self.packets[0].keyframe:
                    self.byte_size -= len(self.packets.popleft().data)
            first = self.packets[0].time if self.packets else float("inf")
            if self.origin is None:
                while self.pending_frames and self.pending_frames[0] < first:
                    self.pending_frames.popleft()
            else:
                first += self.origin
                while self.frames and self.frames[0][0] < first:
                    self.frames.popleft()

    def append(self, timestamp, pts, sample=None):
        with self.lock:
            if self.packets and pts >= self.packets[0].time:
                if self.origin is None:
                    self.pending_frames.append(pts)
                else:
                    self.frames.append((timestamp, pts))
                    self._track(timestamp)
            self.received_frames += 1
            if sample is not None:
                self.samples.append(sample)
            while self.samples and timestamp - self.samples[0].time > self.seconds:
                self.samples.popleft()

    def packet_range(self, sequence, target):
        with self.lock:
            if not self.packets or self.codec is None:
                return None
            reset = sequence is None or sequence < self.packets[0].sequence
            packets = []
            for packet in reversed(self.packets):
                if not reset and packet.sequence < sequence:
                    break
                packets.append(packet)
                if reset and packet.keyframe and packet.time <= target:
                    break
            if reset and (not packets or not packets[-1].keyframe or packets[-1].time > target):
                return None
            packets.reverse()
            return self.codec, packets, reset


class PictureReader:
    """Only requested main/comparison pictures get full resolution RGB conversion."""

    def __init__(self):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.cancelled = threading.Event()
        self.thread = None
        self.history = None
        self.target = None
        self.images = {}
        self.requested = 0.0
        self.decode_ms = 0.0
        self.decoded = 0
        self.byte_limit = 64 * 1024 * 1024
        self.max_frames = 8
        self.fps = 60.0
        self.lead = .1
        self.active = True
        self.snapshot_until = 0.0
        self.reset_requested = False

    def configure(self, byte_limit, fps, lead=.35, active=True):
        with self.lock:
            previous_active = self.active
            self.active = active or time.monotonic() < self.snapshot_until
            if not self.active:
                self.reset_requested |= previous_active
                self.target = None
                self.images.clear()
            if (self.byte_limit, self.fps, self.lead, self.max_frames) == (byte_limit, max(1, fps), lead, 24):
                return
            self.byte_limit = byte_limit
            self.max_frames = 24
            self.fps = max(1, fps)
            self.lead = lead
            while len(self.images) > 1 and sum(image.sizeInBytes() for image in self.images.values()) > byte_limit:
                self.images.pop(next(iter(self.images)))

    def get(self, history, frame, exact=False):
        with self.lock:
            # Explicit crop dialogs may request a snapshot of a hidden source.
            self.active = True
            if exact:
                self.snapshot_until = time.monotonic() + .5
            if self.history is not history:
                self.images.clear()
                self.history = history
            self.requested = time.monotonic()
            cached_backward = frame[0] in self.images and self.target is not None and frame[0] < self.target[0]
            if not cached_backward and (frame != self.target or frame[0] not in self.images):
                if self.target is not None and (frame[1] < self.target[1] - .05 or frame[1] > self.target[1] + .5):
                    self.reset_requested = True
                self.target = frame
                self.wake.set()
            if self.thread is None and not self.cancelled.is_set():
                self.thread = threading.Thread(target=self._run, name="match-sync-picture", daemon=True)
                self.thread.start()
            image = self.images.get(frame[0])
            if image is None and not exact:
                past = [key for key in self.images if frame[0] - .15 <= key <= frame[0]]
                if past:
                    key = max(past)
                    return key, self.images[key]
            return (frame[0], image) if image is not None else None

    def _run(self):
        codec = None
        owner = None
        sequence = None
        decoded_until = None
        capacity = 8
        try:
            while not self.cancelled.is_set():
                if not self.wake.wait(1):
                    with self.lock:
                        if time.monotonic() - self.requested >= 1:
                            self.images.clear()
                            codec = owner = sequence = decoded_until = None
                    continue
                self.wake.clear()
                if self.cancelled.is_set():
                    break
                with self.lock:
                    if self.reset_requested:
                        codec = owner = sequence = decoded_until = None
                        self.reset_requested = False
                    if self.target is None or not self.active:
                        codec = owner = sequence = decoded_until = None
                        continue
                    history, (timestamp, target) = self.history, self.target
                if owner is not history:
                    codec = sequence = decoded_until = None
                    with self.lock:
                        self.images.clear()
                horizon = target + min(self.lead, max(1, capacity * 3 // 4) / self.fps)
                if decoded_until is not None and decoded_until >= horizon:
                    continue
                result = history.packet_range(sequence, target)
                if result is None:
                    continue
                config, packets, reset = result
                if codec is None or reset:
                    decoded_until = None
                    codec = av.CodecContext.create(config[0], "r")
                    codec.extradata = config[1]
                    codec.thread_count = 2
                    # Seekable picture workers must release promptly on switch/close.
                    # Frame-thread teardown can block the GUI when two are active.
                    codec.thread_type = "SLICE"
                owner = history
                for packet in packets:
                    if self.cancelled.is_set():
                        break
                    with self.lock:
                        if (not self.active or self.target is None or self.history is not history
                                or self.reset_requested):
                            break
                    started = time.perf_counter()
                    frames = codec.decode(packet.decode_packet())
                    sequence = packet.sequence + 1
                    complete = False
                    for frame in frames:
                        pts = float(frame.pts * frame.time_base)
                        decoded_until = pts
                        with self.lock:
                            requested_target = self.target[1] if self.target is not None else target
                        if pts + .00001 < max(target, requested_target - .05):
                            continue
                        image = image_from_frame(frame)
                        key = history.origin + pts
                        with self.lock:
                            if not self.active or self.history is not history or self.cancelled.is_set():
                                break
                            self.images[key] = image
                            capacity = max(1, min(self.max_frames, self.byte_limit // image.sizeInBytes()))
                            horizon = target + min(self.lead, max(1, capacity * 3 // 4) / self.fps)
                            while len(self.images) > capacity:
                                self.images.pop(next(iter(self.images)))
                            self.decoded += 1
                        complete = pts >= horizon
                    self.decode_ms = (time.perf_counter() - started) * 1000
                    if complete:
                        break
        finally:
            with self.lock:
                self.images.clear()

    def stop(self):
        self.cancelled.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(1)
