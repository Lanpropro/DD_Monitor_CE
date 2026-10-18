"""默认输出设备变更只刷新活动的独立 WASAPI 输出。"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DDM_NO_SAVE", "1")
from ddm.app import MainWindow

device = [b"old"]
players = {1: Mock(), 2: Mock()}
window = cast(MainWindow, SimpleNamespace(_closing=False, players=players,
    _audio_devices=SimpleNamespace(defaultAudioOutput=lambda: SimpleNamespace(id=lambda: device[0])),
    _default_audio_output_id=b"old"))
MainWindow._check_audio_output_device(window)
assert all(not player.refresh_audio_device.called for player in players.values())
device[0] = b"new"
MainWindow._check_audio_output_device(window)
assert all(player.refresh_audio_device.call_count == 1 for player in players.values())
assert window._default_audio_output_id == b"new"
MainWindow._check_audio_output_device(window)
assert all(player.refresh_audio_device.call_count == 1 for player in players.values())
device[0] = b"third"
players[1].refresh_audio_device.side_effect = [RuntimeError("busy"), None]
MainWindow._check_audio_output_device(window)
assert window._default_audio_output_id == b"new"
MainWindow._check_audio_output_device(window)
assert window._default_audio_output_id == b"third"
print("PASS: independent WASAPI reload, no repeated reload and retry on device error")
