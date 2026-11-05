"""真实 libmpv 控制接口的音频巡检，替换外部设备与播放器内核。"""
import os
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget

from ddm.audio_output import linear_volume
from ddm.player import TilePlayer

app = QApplication([])
widget = QWidget()
player = TilePlayer(widget)
core = Mock(volume=linear_volume(60), mute=True)
player.player = core
player.set_volume(60)
player.set_muted(True)
player.set_audio_channel(3)
try:
    for _ in range(10):
        player.sync_audio(60, True, 3)
    assert core.mute and abs(core.volume - linear_volume(60)) < 0.01
    core.mute = False
    core.volume = 5
    player.sync_audio(60, True, 3)
    assert core.mute is True and core.volume == linear_volume(60)
    player.sync_audio(0, False, 4)
    assert core.mute is False and core.volume == 0 and player.audio_channel == 4
    player.set_volume_normalization(True)
    assert 'dynaudnorm' in core.af and 'pan=' in core.af
    player.set_audio_channel(3)
    assert 'dynaudnorm' in core.af and 'c1=0*c1' in core.af
    player.reapply_audio_channel()
    assert core.af.count('dynaudnorm') == 1
    player.set_volume_normalization(False)
    assert 'dynaudnorm' not in core.af and 'pan=' in core.af
    player.release()
    calls = list(core.mock_calls)
    player.sync_audio(100, False, 0)
    assert core.mock_calls == calls
finally:
    player.release()
preview = TilePlayer(widget, silent=True)
preview.player = Mock()
preview.set_volume_normalization(True)
assert preview.volume_normalization is False
preview.release()
print("PASS: libmpv audio drift repair, zero volume and released-player guard")
