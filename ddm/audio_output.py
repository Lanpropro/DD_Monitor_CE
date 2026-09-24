"""Per-player PCM routing to the Windows default stereo output."""
from __future__ import annotations

import ctypes
import sys
import threading

try:
    # audioop 是 C 实现的，混音和缩放都是一次调用搞定；纯 Python 逐样本处理
    # 48kHz 立体声太慢（每格每秒近十万次循环）。3.13 起它被移出标准库，
    # 所以留了纯 Python 回退。
    import audioop
except ImportError:  # pragma: no cover
    audioop = None

CHANNEL_LEFT = 3
CHANNEL_RIGHT = 4
BYTES_PER_FRAME = 4                 # stereo, signed 16-bit PCM


def route_pcm_s16_stereo(data: bytes, channel: int) -> bytes:
    """把立体声混成单声道，只放到指定的物理输出侧。"""
    if channel not in (CHANNEL_LEFT, CHANNEL_RIGHT):
        return data                     # 不路由就原样返回，一个字节都不用动
    if len(data) % BYTES_PER_FRAME:
        raise ValueError("stereo S16 PCM must contain complete frames")

    if audioop is not None:
        mono = audioop.tomono(data, 2, 0.5, 0.5)          # 左右各半 → 单声道
        return audioop.tostereo(mono, 2,
                                1.0 if channel == CHANNEL_LEFT else 0.0,
                                1.0 if channel == CHANNEL_RIGHT else 0.0)

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


def linear_to_vlc_volume(volume: int) -> int:
    """把「滑块 0..100」折算成传给 libvlc_audio_set_volume 的值，让最终增益 = v/100。

    VLC 3 的 ``libvlc_audio_set_volume`` 内部对 0..1 取**三次方**（mmdevice 输出在
    交给 ISimpleAudioVolume 之前会 ``powf(vol, 3)``）。三次方曲线「前面拖了没反应、
    后面突然响」，用户要求线性 —— 所以这里先取立方根，抵消掉 VLC 那层三次方。
    """
    level = max(0, min(100, int(volume)))
    if level <= 0:
        return 0
    return int(round(100 * (level / 100) ** (1.0 / 3.0)))


def apply_volume_s16_stereo(data: bytes, volume: int) -> bytes:
    """对回调 PCM 样本套**线性**音量：就是滑块值本身（``v/100``）。

    PCM 回调绕开了 VLC 的音量（实测 ``libvlc_audio_set_volume`` 对回调样本完全
    不生效），所以这里自己乘。音量曲线用户要求线性，直接 ``v/100``。
    """
    if len(data) % BYTES_PER_FRAME:
        raise ValueError("stereo S16 PCM must contain complete frames")
    level = max(0, min(100, int(volume)))
    if level >= 100:
        return data                     # 满音量：原样放行，零开销
    if level <= 0:
        return bytes(len(data))         # 全零比逐样本乘快得多
    if audioop is not None:
        return audioop.mul(data, 2, level / 100)

    gain = level / 100
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
            if self.volume < 100:
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
