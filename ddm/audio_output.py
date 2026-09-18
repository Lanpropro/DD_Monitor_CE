"""Per-player PCM routing to the Windows default stereo output."""
from __future__ import annotations

import ctypes
import sys
import threading

CHANNEL_LEFT = 3
CHANNEL_RIGHT = 4
BYTES_PER_FRAME = 4                 # stereo, signed 16-bit PCM


def route_pcm_s16_stereo(data: bytes, channel: int) -> bytes:
    """Mix stereo to mono and place it on only the requested output side."""
    if channel not in (CHANNEL_LEFT, CHANNEL_RIGHT):
        return bytes(data)
    if len(data) % BYTES_PER_FRAME:
        raise ValueError("stereo S16 PCM must contain complete frames")

    output = bytearray(len(data))
    source = memoryview(data).cast("h")
    target = memoryview(output).cast("h")
    for index in range(0, len(source), 2):
        mono = (int(source[index]) + int(source[index + 1])) // 2
        if channel == CHANNEL_LEFT:
            target[index] = mono
        else:
            target[index + 1] = mono
    return bytes(output)


def apply_volume_s16_stereo(data: bytes, volume: int) -> bytes:
    """Apply VLC's Windows volume curve to callback PCM samples."""
    if len(data) % BYTES_PER_FRAME:
        raise ValueError("stereo S16 PCM must contain complete frames")
    level = max(0, min(100, int(volume)))
    if level == 100:
        return bytes(data)
    # VLC 3 的 Windows mmdevice 输出也把 0..1 音量取三次方后交给
    # ISimpleAudioVolume。PCM 回调绕开了那层，必须在这里使用同一曲线，
    # 否则 50% 会按 0.5 而不是 0.125 输出，单独声道听起来明显更响。
    gain = (level / 100) ** 3
    output = bytearray(len(data))
    source = memoryview(data).cast("h")
    target = memoryview(output).cast("h")
    for index, sample in enumerate(source):
        target[index] = int(int(sample) * gain)
    return bytes(output)


def vlc_channel_for(channel: int) -> int:
    """Keep VLC stereo while left/right placement is handled after decoding."""
    return 1 if int(channel) in (CHANNEL_LEFT, CHANNEL_RIGHT) else int(channel)


class StereoOutput:
    """Blocking PortAudio sink owned by one video tile.

    LibVLC calls ``write`` from its audio thread.  A blocking raw stream gives
    that thread the same back-pressure as a normal audio device and keeps the
    audio clock aligned with the video.
    """

    def __init__(self, stream_factory=None):
        self.channel = 0
        self.volume = 100
        self.enabled = False
        self._stream_factory = stream_factory or self._new_stream
        self._stream = None
        self._lock = threading.RLock()
        self._reported_error = False

    @staticmethod
    def _new_stream():
        import sounddevice

        return sounddevice.RawOutputStream(
            samplerate=48_000,
            channels=2,
            dtype="int16",
            blocksize=0,
            latency="low",
        )

    def set_channel(self, channel: int) -> None:
        self.channel = int(channel)

    def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, int(volume)))

    def set_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self.enabled == enabled:
            return
        self.enabled = enabled
        if not enabled:
            self.flush()

    def write(self, samples, count: int) -> None:
        if not self.enabled or not samples or count <= 0:
            return
        try:
            pcm = ctypes.string_at(samples, int(count) * BYTES_PER_FRAME)
            pcm = route_pcm_s16_stereo(pcm, self.channel)
            pcm = apply_volume_s16_stereo(pcm, self.volume)
            with self._lock:
                if not self.enabled:
                    return
                if self._stream is None:
                    self._stream = self._stream_factory()
                if not self._stream.active:
                    self._stream.start()
                self._stream.write(pcm)
            self._reported_error = False
        except Exception as exc:  # noqa: BLE001 - never escape a C callback
            if not self._reported_error:
                print(f"[音频输出] {exc}", file=sys.stderr, flush=True)
                self._reported_error = True
            self.close()

    def pause(self) -> None:
        with self._lock:
            if self._stream is not None and self._stream.active:
                try:
                    self._stream.stop()
                except Exception:  # noqa: BLE001
                    self.close()

    def resume(self) -> None:
        with self._lock:
            if self.enabled and self._stream is not None and not self._stream.active:
                try:
                    self._stream.start()
                except Exception:  # noqa: BLE001
                    self.close()

    def flush(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.abort()
                except Exception:  # noqa: BLE001
                    pass

    def drain(self) -> None:
        with self._lock:
            if self._stream is not None and self._stream.active:
                try:
                    self._stream.stop()
                except Exception:  # noqa: BLE001
                    pass

    def close(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            if stream is None:
                return
            try:
                stream.abort()
            except Exception:  # noqa: BLE001
                pass
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
