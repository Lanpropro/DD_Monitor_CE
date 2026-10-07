"""Qt 未同步 VLC 原生焦点时仍能闲置隐藏；切出本窗口必须恢复。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from ddm import fullscreen_cursor as module
from ddm.widgets import Tile


def main():
    app = QApplication([])
    owner = QWidget()
    owner.resize(800, 600)
    tile = Tile({'room_id': 'douyu:123', 'platform': 'douyu', 'uname': 'Fixture'}, owner)
    tile.resize(800, 600)
    owner._fullscreen_tile = tile
    owner.isActiveWindow = lambda: False
    owner.show()
    app.processEvents()
    hwnd = int(owner.winId())
    user32 = Mock()
    user32.GetForegroundWindow.return_value = 456
    user32.GetAncestor.return_value = hwnd
    user32.LoadCursorW.return_value = 1
    cursor = module.FullscreenCursor(owner)
    now = [100.0]
    point = tile.video.mapToGlobal(tile.video.rect().center())
    geometry = tile.video.geometry()
    with patch.object(tile.video, '_clip_native_video', return_value=True), patch.object(
            tile, '_apply_native_controls_mask', return_value=False), patch.object(
            module.sys, 'platform', 'win32'), patch.object(
            module.QApplication, 'platformName', return_value='windows'), patch.object(
            module.ctypes, 'windll', SimpleNamespace(user32=user32)), patch.object(
            module.QCursor, 'pos', return_value=point), patch.object(
            module.time, 'monotonic', side_effect=lambda: now[0]):
        cursor.start()
        now[0] += 4
        cursor.update_cursor()
        assert cursor.hidden and not tile.bottom.isVisible()
        assert tile.video.geometry() == geometry
        user32.GetAncestor.assert_called_with(456, 2)
        # 外部应用处于前台时，不能继续隐藏光标或保留隐藏的控件。
        user32.GetAncestor.return_value = hwnd + 1
        cursor.update_cursor()
        assert not cursor.hidden and tile.bottom.isVisible()
        assert QApplication.overrideCursor() is None and tile.video.geometry() == geometry
        now[0] += 4
        cursor.update_cursor()
        assert not cursor.hidden
        cursor.stop()
    owner.close()
    app.processEvents()
    print('PASS: Douyu native focus; idle/wake geometry; foreground ownership; focus loss restores controls/cursor')


if __name__ == '__main__':
    main()
