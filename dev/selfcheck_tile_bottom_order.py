"""Tile bottom controls: left volume, right recording, working signals."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme
from ddm.widgets import DanmakuToggleButton, ElidedLabel, Tile


def check_restored_styles(app, tile):
    button = tile.danmaku_button
    assert isinstance(button, DanmakuToggleButton) and button.objectName() == 'TileToggle'
    for mode in ('dark', 'light', 'dark'):
        theme.apply(mode)
        tile.resize(900, 500)
        app.processEvents()
        assert button.text() == '弹' and button.width() == 34
        button.setChecked(False)
        app.processEvents()
        unchecked = button.grab().toImage()
        assert '开启' in button.toolTip()
        button.setChecked(True)
        app.processEvents()
        checked = button.grab().toImage()
        assert '关闭' in button.toolTip() and tile.video_danmaku.enabled
        changed = [(x, y) for y in range(checked.height()) for x in range(checked.width())
                   if checked.pixelColor(x, y) != unchecked.pixelColor(x, y)]
        assert changed, '开启后必须绘制勾选标记'
        scale = checked.devicePixelRatio()
        assert all(x >= (button.width() - 13) * scale and
                   y >= (button.height() - 14) * scale for x, y in changed), '开关只改变右下角标记'
    button.setChecked(False)
    label = ElidedLabel('状态文字不能因隐藏而丢失')
    for width in (0, 1, 200):
        label.resize(width, 26)
        label._apply_elide()
        assert label.text(), '零宽或窄状态文字应保留内容，交由窗口裁剪'
    label.close()


def main():
    app = QApplication(sys.argv)
    tile = Tile({"room_id": "1000", "uname": "Test", "live": False})
    assert hasattr(tile, "composer"), "发送输入区应已恢复"
    events = []
    tile.recordingRequested.connect(lambda: events.append("record"))
    tile.muteToggled.connect(lambda room, muted: events.append("mute"))
    tile.volumeChanged.connect(lambda room, volume: events.append(volume))
    tile.show()
    try:
        check_restored_styles(app, tile)
        for width, height in ((900, 500), (360, 210), (300, 500)):
            tile.resize(width, height)
            app.processEvents()
            controls = [tile.pause_button, tile.volume_button, tile.volume_slider,
                        tile.volume_label, tile.status_label, tile.danmaku_button,
                        tile.danmaku_settings_button, tile.recording_button,
                        tile.fullscreen_button]
            visible = [widget for widget in controls if widget.isVisible()]
            assert [widget.x() for widget in visible] == sorted(widget.x() for widget in visible)
            assert tile.danmaku_settings_button.isVisible()
            assert tile.fullscreen_button.geometry().right() < tile.bottom.width()
            tile.set_recording_state("record")
            tile.set_recording_elapsed("0:00:10")
            app.processEvents()
            if tile.recording_time.isVisible():
                assert tile.recording_button.x() < tile.recording_time.x() < tile.fullscreen_button.x()
            tile.set_recording_state("")
            tile.set_recording_elapsed("")
            tile.set_recording_available(False)
            app.processEvents()
            assert not tile.recording_button.isVisible()
            assert tile.volume_button.isVisible()
            assert tile.volume_slider.isVisible() == (width >= 600)
            tile.set_recording_available(True)
        tile.resize(900, 500)
        app.processEvents()
        QTest.mouseClick(tile.recording_button, Qt.LeftButton)
        QTest.mouseClick(tile.volume_button, Qt.LeftButton)
        tile.volume_slider.setValue(55)
        assert "record" in events and "mute" in events and 55 in events
    finally:
        tile.close()
    print("Tile bottom: wide/narrow/portrait, recording time, disabled recording and signals passed")


if __name__ == "__main__":
    main()
