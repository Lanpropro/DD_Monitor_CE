"""Original encoded video history and bounded, asynchronous native pictures."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time

from PySide6.QtGui import QImage

try:
    import av
except ImportError:
    av = None

from .engine import History


class StreamInput:
    """Windows subprocess pipes advertise seek() but cannot actually seek."""

    def __init__(self, pipe):
        self.pipe = pipe

    def read(self, size):
        return self.pipe.read(size)


def image_from_frame(frame):
    rgb = frame.reformat(format="bgra")
    plane = rgb.planes[0]
    return QImage(bytes(plane), rgb.width, rgb.height, plane.line_size, QImage.Format_ARGB32).copy()


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

    def append_packet(self, packet):
        with self.lock:
            record = EncodedPacket(self.sequence, bytes(packet), packet.pts, packet.dts,
                                   packet.duration, packet.time_base, packet.is_keyframe)
            self.sequence += 1
            if not self.packets and not record.keyframe:
                return
            self.packets.append(record)
            self.byte_size += len(record.data)
            while self.packets and (self.byte_size > self.byte_limit or
                                    record.time - self.packets[0].time > self.seconds):
                self.byte_size -= len(self.packets.popleft().data)
                # A decoder cannot start in the middle of an inter-frame GOP.
                while self.packets and not self.packets[0].keyframe:
                    self.byte_size -= len(self.packets.popleft().data)
            if self.origin is not None:
                first = self.origin + self.packets[0].time if self.packets else float("inf")
                while self.frames and self.frames[0][0] < first:
                    self.frames.popleft()

    def append(self, timestamp, pts, sample=None):
        with self.lock:
            if self.packets and pts >= self.packets[0].time:
                self.frames.append((timestamp, pts))
            self.received_frames += 1
            if sample is not None:
                self.samples.append(sample)
            while self.samples and timestamp - self.samples[0].time > self.seconds:
                self.samples.popleft()

    def packet_range(self, sequence, target):
        with self.lock:
            packets = list(self.packets)
            if not packets or self.codec is None:
                return None
            if sequence is None or sequence < packets[0].sequence:
                starts = [i for i, packet in enumerate(packets) if packet.keyframe and packet.time <= target]
                if not starts:
                    return None
                packets = packets[starts[-1]:]
                reset = True
            else:
                packets = [packet for packet in packets if packet.sequence >= sequence]
                reset = False
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

    def get(self, history, frame, exact=False):
        with self.lock:
            if self.history is not history:
                self.images.clear()
                self.history = history
            self.requested = time.monotonic()
            if frame != self.target or frame[0] not in self.images:
                self.target = frame
                self.wake.set()
            if self.thread is None and not self.cancelled.is_set():
                self.thread = threading.Thread(target=self._run, name="match-sync-picture", daemon=True)
                self.thread.start()
            image = self.images.get(frame[0])
            if image is None and not exact:
                past = [key for key in self.images if frame[0] - .05 <= key <= frame[0]]
                if past:
                    key = max(past)
                    return key, self.images[key]
            return (frame[0], image) if image is not None else None

    def _run(self):
        codec = None
        owner = None
        sequence = None
        previous = None
        decoded_until = None
        capacity = 8
        try:
            while not self.cancelled.is_set():
                if not self.wake.wait(1):
                    with self.lock:
                        if time.monotonic() - self.requested >= 1:
                            self.images.clear()
                            codec = owner = sequence = previous = decoded_until = None
                    continue
                self.wake.clear()
                if self.cancelled.is_set():
                    break
                with self.lock:
                    history, (timestamp, target) = self.history, self.target
                if owner is not history or previous is None or target < previous - .05 or target > previous + .5:
                    codec = sequence = decoded_until = None
                    with self.lock:
                        self.images.clear()
                horizon = target + max(1, capacity - 2) / 60
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
                    codec.thread_type = "SLICE"
                owner, previous = history, target
                for packet in packets:
                    if self.cancelled.is_set():
                        break
                    with self.lock:
                        if self.history is not history or abs(self.target[1] - target) > .25:
                            break
                    started = time.perf_counter()
                    frames = codec.decode(packet.decode_packet())
                    sequence = packet.sequence + 1
                    complete = False
                    for frame in frames:
                        pts = float(frame.pts * frame.time_base)
                        decoded_until = pts
                        if pts + .00001 < target:
                            continue
                        image = image_from_frame(frame)
                        key = history.origin + pts
                        with self.lock:
                            if self.history is not history or self.cancelled.is_set():
                                break
                            self.images[key] = image
                            capacity = max(1, min(8, 64 * 1024 * 1024 // image.sizeInBytes()))
                            horizon = target + max(1, capacity - 2) / 60
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
