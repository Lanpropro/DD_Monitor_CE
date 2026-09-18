"""声道路由自检：验证完整混音只进入指定的物理输出侧。"""
import ctypes
import os
import struct
import sys
import tempfile
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddm.audio_output import (
    CHANNEL_LEFT, CHANNEL_RIGHT, StereoOutput, apply_volume_s16_stereo,
    route_pcm_s16_stereo,
    vlc_channel_for,
)


def samples(data):
    return struct.unpack("<" + "h" * (len(data) // 2), data)


source = struct.pack("<hhhhhh", 1000, 3000, -3000, 1000, 32767, 32767)
assert route_pcm_s16_stereo(source, 0) == source
assert samples(route_pcm_s16_stereo(source, CHANNEL_LEFT)) == (
    2000, 0, -1000, 0, 32767, 0,
)
assert samples(route_pcm_s16_stereo(source, CHANNEL_RIGHT)) == (
    0, 2000, 0, -1000, 0, 32767,
)
assert samples(apply_volume_s16_stereo(source, 50)) == (
    125, 375, -375, 125, 4095, 4095,
)
assert apply_volume_s16_stereo(source, 100) == source
assert samples(apply_volume_s16_stereo(source, 0)) == (0, 0, 0, 0, 0, 0)
assert vlc_channel_for(CHANNEL_LEFT) == 1
assert vlc_channel_for(CHANNEL_RIGHT) == 1
assert vlc_channel_for(2) == 2

try:
    route_pcm_s16_stereo(b"\0", CHANNEL_LEFT)
except ValueError:
    pass
else:
    raise AssertionError("不完整 PCM 帧应被拒绝")


class FakeStream:
    def __init__(self):
        self.active = False
        self.writes = []
        self.starts = 0
        self.aborts = 0
        self.closed = False

    def start(self):
        self.active = True
        self.starts += 1

    def write(self, data):
        self.writes.append(bytes(data))

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False
        self.aborts += 1

    def close(self):
        self.closed = True


created = []


def factory():
    stream = FakeStream()
    created.append(stream)
    return stream


output = StereoOutput(factory)
buffer = ctypes.create_string_buffer(source)
output.write(ctypes.addressof(buffer), 3)
assert created == [], "静音状态不应打开音频设备"

output.set_channel(CHANNEL_LEFT)
output.set_enabled(True)
output.write(ctypes.addressof(buffer), 3)
assert len(created) == 1 and created[0].active
assert samples(created[0].writes[-1]) == (2000, 0, -1000, 0, 32767, 0)

output.set_channel(CHANNEL_RIGHT)
output.write(ctypes.addressof(buffer), 3)
assert samples(created[0].writes[-1]) == (0, 2000, 0, -1000, 0, 32767)

output.set_volume(50)
output.write(ctypes.addressof(buffer), 3)
assert samples(created[0].writes[-1]) == (0, 250, 0, -125, 0, 4095), \
    "PCM 路由必须使用 VLC Windows 输出相同的三次方音量曲线"

output.set_enabled(False)
assert created[0].aborts == 1
output.close()
assert created[0].closed


# 再经过一次真实 libVLC 解码，防止只测到纯函数、却接错 C 回调签名。
class CallbackOutput:
    def __init__(self):
        self.channel = 0
        self.enabled = False
        self.counts = []

    def set_channel(self, channel):
        self.channel = channel

    def set_enabled(self, enabled):
        self.enabled = enabled

    def set_volume(self, volume):
        self.volume = volume

    def write(self, _samples, count):
        if self.enabled:
            self.counts.append(count)

    def pause(self):
        pass

    def resume(self):
        pass

    def flush(self):
        pass

    def drain(self):
        pass

    def close(self):
        pass


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget
import ddm.player as player_module

original_output = player_module.StereoOutput
callback_output = CallbackOutput()
player_module.StereoOutput = lambda: callback_output
audio_path = os.path.join(tempfile.gettempdir(), "ddm_audio_callback_test.wav")
try:
    with wave.open(audio_path, "wb") as audio:
        audio.setparams((2, 2, 48_000, 0, "NONE", "not compressed"))
        audio.writeframes(struct.pack("<hh", 1200, -1200) * 4_800)
    app = QApplication.instance() or QApplication([])
    player = player_module.TilePlayer(QWidget())
    assert not player.uses_pcm_routing, "默认声道必须继续走 VLC 原生音频输出"
    player.set_audio_channel(CHANNEL_LEFT)
    assert player.uses_pcm_routing, "只有只播左/右时才启用 PCM 路由"
    player.set_volume(40)
    player.set_muted(False)
    player.player.set_media(player._instance.media_new_path(audio_path))
    player.player.play()
    deadline = time.time() + 3
    while not callback_output.counts and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert callback_output.counts, "libVLC 没有把解码后的 PCM 送进格子输出"
    assert callback_output.channel == CHANNEL_LEFT and callback_output.enabled
    assert callback_output.volume == 40
    player.release()
finally:
    player_module.StereoOutput = original_output
    try:
        os.remove(audio_path)
    except OSError:
        pass

print("OK: 每格音频可将完整立体声混音独立定位到左输出或右输出")
