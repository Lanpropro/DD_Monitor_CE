"""Tile bottom controls: left volume, right recording, working signals."""
import os
from pathlib import Path
import sys

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme
from ddm.widgets import DanmakuToggleButton, ElidedLabel, Tile, VolumeButton


def check_volume_icon_alignment(app):
    # Offscreen Windows has no system fonts. Load the UI font explicitly and
    # keep the bundled font as a fallback on other platforms.
    theme.danmaku_font_family()
    fonts = Path(os.environ.get('WINDIR', '')) / 'Fonts'
    for name in ('msyh.ttc', 'msyhbd.ttc'):
        if (fonts / name).is_file():
            QFontDatabase.addApplicationFont(str(fonts / name))
    for size in (26, 30, 36):
        button = VolumeButton(size=size)
        button.setStyleSheet('background: black; border: none;')
        button.show()
        try:
            for muted, channel in ((False, 0), (False, 3), (False, 4), (True, 0)):
                button.set_state(muted, 42, channel)
                app.processEvents()
                image = button.grab().toImage()
                scale = image.devicePixelRatio()
                pixels = [(x, y) for y in range(image.height()) for x in range(image.width())
                          if image.pixelColor(x, y).lightness() > 40]
                assert pixels
                left, right = min(x for x, y in pixels), max(x for x, y in pixels)
                assert abs((left + right + 1) / (2 * scale) - button.width() / 2) <= 1, \
                    f'speaker and indicator must be centered together: {size}, {muted}, {channel}'
                indicator = [(x, y) for x, y in pixels if x >= image.width() / 2]
                top, bottom = min(y for x, y in indicator), max(y for x, y in indicator)
                target_y = size / 2 if muted else size / 2 - 1
                assert abs((top + bottom + 1) / (2 * scale) - target_y) <= 1, \
                    f'L/R must sit one pixel above the mute cross: {size}, {muted}, {channel}'
                assert left > 0 and right < image.width() - 1, 'icon must not clip'
        finally:
            button.close()


def check_volume_unmutes(app, tile):
    changes = []
    tile.volumeChanged.connect(lambda room, value: changes.append(('volume', value)))
    tile.muteToggled.connect(lambda room, muted: changes.append(('mute', muted)))
    for control in ('horizontal', 'vertical', 'wheel-up', 'wheel-down', 'direct'):
        tile.set_volume(42)
        tile.set_muted(True)
        changes.clear()
        if control == 'horizontal':
            tile.volume_slider.setValue(55)
            expected = 55
        elif control == 'vertical':
            tile.vertical_volume.setValue(31)
            expected = 31
        elif control.startswith('wheel'):
            delta = 120 if control == 'wheel-up' else -120
            event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, delta),
                                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            QApplication.sendEvent(tile.volume_button, event)
            expected = 47 if delta > 0 else 37
        else:
            tile.set_volume(60)
            expected = 60
        assert not tile.muted and not tile.room['muted'] and not tile.volume_button.muted, control
        assert tile.volume == tile.room['volume'] == tile.volume_button.level == expected, control
        assert tile.volume_slider.value() == tile.vertical_volume.value() == expected, control
        assert changes == [('volume', expected), ('mute', False)], (control, changes)
    tile.set_muted(True)
    changes.clear()
    tile.set_volume(0)
    assert tile.muted and tile.room['muted'] and tile.volume_button.muted
    assert changes == [('volume', 0)], changes
    tile.set_volume(42)
    tile.set_muted(True)
    changes.clear()
    tile.sync_audio_ui()
    assert tile.muted and tile.volume_button.muted and not changes, 'UI refresh must preserve mute'
    tile.set_muted(False)
    changes.clear()
    tile.set_volume(43)
    assert changes == [('volume', 43)], 'audible adjustments must not repeat mute signals'


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
    events = []
    tile.recordingRequested.connect(lambda: events.append("record"))
    tile.muteToggled.connect(lambda room, muted: events.append("mute"))
    tile.volumeChanged.connect(lambda room, volume: events.append(volume))
    tile.show()
    try:
        check_volume_unmutes(app, tile)
        check_volume_icon_alignment(app)
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
    print("Tile bottom: volume unmute, centered icons, wide/narrow/portrait, recording and signals passed")


if __name__ == "__main__":
    main()
