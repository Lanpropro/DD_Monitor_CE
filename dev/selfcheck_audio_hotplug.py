"""切换默认音频设备后，已有声格子必须在新设备上继续输出。"""
import ctypes
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ddm.audio_output import StereoOutput, refresh_output_devices


class FakeStream:
    def __init__(self, device):
        self.device = device
        self.active = False
        self.closed = False
        self.writes = 0

    def start(self):
        self.active = True

    def write(self, _data):
        self.writes += 1

    def abort(self):
        self.active = False

    def close(self):
        self.closed = True


device = ["old"]
created = []


def factory():
    stream = FakeStream(device[0])
    created.append(stream)
    return stream


audible = StereoOutput(factory)
muted = StereoOutput(factory)
audible.set_enabled(True)
sample = ctypes.create_string_buffer(b"\x01\x00\x01\x00")
audible.write(ctypes.addressof(sample), 1)
muted.write(ctypes.addressof(sample), 1)
assert len(created) == 1 and created[0].device == "old"

events = []


def terminate():
    assert created[0].closed, "PortAudio 刷新前必须关闭旧设备的流"
    events.append("terminate")


def initialize():
    device[0] = "new"
    events.append("initialize")


with patch.dict(sys.modules, {"sounddevice": SimpleNamespace(
        _terminate=terminate, _initialize=initialize)}):
    refresh_output_devices([audible, muted])

assert events == ["terminate", "initialize"]
assert audible.enabled and not muted.enabled, "切设备不能改变各格静音状态"
audible.write(ctypes.addressof(sample), 1)
assert len(created) == 2 and created[1].device == "new" and created[1].writes == 1
muted.set_enabled(True)
muted.write(ctypes.addressof(sample), 1)
assert len(created) == 3 and created[2].device == "new" and created[2].writes == 1
audible.close()
muted.close()

from ddm.app import MainWindow
import ddm.app as app_module


class FakeDevices:
    def __init__(self):
        self.id = b"old"

    def defaultAudioOutput(self):
        return SimpleNamespace(id=lambda: self.id)


devices = FakeDevices()
window = SimpleNamespace(
    _closing=False,
    _audio_devices=devices,
    _default_audio_output_id=b"old",
    players={1: SimpleNamespace(_audio_output=audible),
             2: SimpleNamespace(_audio_output=muted)},
)
with patch.object(app_module, "refresh_output_devices") as refresh:
    MainWindow._check_audio_output_device(window)
    assert refresh.call_count == 0
    devices.id = b"new"
    MainWindow._check_audio_output_device(window)
    refresh.assert_called_once_with([audible, muted])
    assert window._default_audio_output_id == b"new"
    MainWindow._check_audio_output_device(window)
    assert refresh.call_count == 1, "设备不变时不能反复重建输出流"

devices.id = b"third"
with patch.object(app_module, "refresh_output_devices", side_effect=[RuntimeError("busy"), None]) as refresh:
    MainWindow._check_audio_output_device(window)
    assert window._default_audio_output_id == b"new", "刷新失败后应在下次巡检重试"
    MainWindow._check_audio_output_device(window)
    assert refresh.call_count == 2 and window._default_audio_output_id == b"third"

print("OK: 热切换输出设备后有声格子恢复，静音格子保持独立")
