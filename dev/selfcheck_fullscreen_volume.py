"""Offline fullscreen volume checks; --native-wheel exercises the Windows video HWND."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if '--native-wheel' in sys.argv else 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMenu, QPushButton, QVBoxLayout
from ddm.app import MainWindow


def wheel(target, y=120, *, x=0, pixels=0, modifiers=Qt.NoModifier, buttons=Qt.NoButton,
          point=None, phase=Qt.NoScrollPhase):
    if point is None:
        point = target.mapToGlobal(target.rect().center())
    event = QWheelEvent(QPointF(target.mapFromGlobal(point)), QPointF(point), QPoint(0, pixels),
                        QPoint(x, y), buttons, modifiers, phase, False)
    QApplication.sendEvent(target, event)


def check_wheel(window, first, tile, player):
    with patch.object(window, '_tile_under_cursor', return_value=first):
        player.set_volume.reset_mock()
        wheel(tile.video)
        player.set_volume.assert_called_once_with(52)
        assert first.volume == 42 and tile.volume == tile.room['volume'] == 52
        assert not tile.muted and not tile.volume_button.muted
        assert tile.volume_label.text() == '52'
        assert tile.volume_slider.value() == tile.vertical_volume.value() == 52
        assert window.current_state()['wall'][1]['volume'] == 52
        wheel(tile, -240, point=tile.video.mapToGlobal(tile.video.rect().center()))
        assert tile.volume == 32
        wheel(tile.video, 60)
        assert tile.volume == 32
        wheel(tile.video, 60, phase=Qt.ScrollEnd)
        assert tile.volume == 42
        wheel(tile.video, 0, pixels=-40)
        assert tile.volume == 32
        wheel(tile.video, 0, x=120)
        wheel(tile.video, 0, phase=Qt.ScrollEnd)
        wheel(tile.video, modifiers=Qt.ControlModifier)
        wheel(tile.video, buttons=Qt.LeftButton)
        wheel(tile.video, point=tile.mapToGlobal(QPoint(-1, -1)))
        wheel(first.video)
        assert tile.volume == 32 and first.volume == 42
        tile.set_volume(99)
        wheel(tile.video)
        assert tile.volume == 100
        tile.set_volume(3)
        wheel(tile.video, -120)
        assert tile.volume == 0
        tile.set_volume(42)
        wheel(tile.volume_button)
        assert tile.volume == 47, 'volume button keeps its own five-point step'
        tile.set_volume(42)
        with patch.object(tile, 'plugin_interaction_active', return_value=True):
            wheel(tile.video)
            assert tile.volume == 42
        menu = QMenu(tile)
        menu.addAction('fixture')
        menu.popup(tile.video.mapToGlobal(tile.video.rect().center()))
        try:
            assert QApplication.activePopupWidget() is menu
            wheel(tile.video)
            assert tile.volume == 42
        finally:
            menu.close()


def check_native_wheel(app, window):
    import ctypes
    from ctypes import wintypes
    from PySide6.QtCore import QRect
    from ddm.player import TilePlayer
    from selfcheck_mpv import ready

    assert app.platformName() == 'windows'
    window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    bounds = QRect(-9000, -9000, 800, 500)
    window.setGeometry(bounds)
    window.show()
    first, tile = window.wall.tiles[:2]
    presentation = window._fullscreen_presentation
    enter = presentation.enter
    with patch.object(presentation, 'enter', side_effect=lambda pane: enter(pane, bounds)):
        window._on_fullscreen(first)
        wheel(first.video, 60)
        assert first.volume == 42
        window._exit_fullscreen()
        window._on_fullscreen(tile)
    window._fullscreen_cursor.stop()
    wheel(tile.video, 60)
    assert tile.volume == 42, 'partial notch leaked from the previous fullscreen tile'
    wheel(tile.video, 60)
    assert tile.volume == 52 and first.volume == 42
    tile.set_volume(42)
    player = TilePlayer(tile.video, silent=True)
    window.players[tile] = player
    try:
        player.play('av://lavfi:color=c=blue:s=160x90:r=10')
        ready(app, player)
        assert tile.video._clip_native_video(), 'fixture requires a real embedded mpv child'
        user32 = ctypes.windll.user32
        user32.ChildWindowFromPointEx.argtypes = (wintypes.HWND, wintypes.POINT, wintypes.UINT)
        user32.ChildWindowFromPointEx.restype = wintypes.HWND
        user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        root = int(tile.video.winId())
        center = tile.video.rect().center()
        scale = tile.video.devicePixelRatioF()
        point = wintypes.POINT(round(center.x() * scale), round(center.y() * scale))
        # Host clipping disables the mpv child; the video surface receives mouse input.
        hit = user32.ChildWindowFromPointEx(root, point, 7)  # skip invisible/disabled/transparent
        assert hit == root, 'native wheel hit must reach the Qt video surface'
        assert user32.ClientToScreen(root, ctypes.byref(point))
        packed = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
        changes = []
        tile.volumeChanged.connect(lambda _room, value: changes.append(value))
        for hwnd, delta in ((hit, 120), (int(tile.winId()), -120)):
            user32.SendMessageW(hwnd, 0x020A, (delta & 0xffff) << 16, packed)
            app.processEvents()
        assert changes == [52, 42] and player.volume == 42, changes
    finally:
        window.players.pop(tile)
        player.release()
        window._exit_fullscreen()
    print('PASS: Windows WM_MOUSEWHEEL over embedded libmpv, surface and fullscreen owner')


def main():
    app = QApplication([])
    with ExitStack() as stack:
        for method in ('_start_startup_tiles', '_check_startup_update', '_check_startup_plugins',
                       'start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method, return_value=None))
        rooms = [dict(room_id=str(1001 + i), uname='test', live=False,
                      volume=42, muted=True) for i in range(2)]
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='2x2',
                            state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
        try:
            if '--native-wheel' in sys.argv:
                check_native_wheel(app, window)
                return
            window.resize(1000, 700)
            window.show()
            window.activateWindow()
            app.processEvents()
            first, second = window.wall.tiles[:2]
            player = Mock()
            window.players[second] = player
            first.pause_button.setFocus()
            wheel(first.video)
            QTest.keyClick(first.pause_button, Qt.Key_Up)
            assert second.volume == first.volume == 42, 'windowed plain wheel and arrows must not adjust volume'
            with patch.object(window, '_tile_under_cursor', return_value=first):
                wheel(first.video, modifiers=Qt.ShiftModifier)
                assert first.volume == 52 and second.volume == 42
                wheel(first.video, -120, modifiers=Qt.ShiftModifier)
                assert first.volume == 42
            window._on_fullscreen(second)
            app.processEvents()
            second.set_muted(True)
            second.pause_button.setFocus()
            check_wheel(window, first, second, player)
            second.set_muted(True)
            with patch.object(window, '_tile_under_cursor', return_value=first):
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 52, 'Up must target the fullscreen tile, independent of cursor'
                assert first.volume == 42
                player.set_volume.assert_called_with(52)
                QTest.keyClick(second.pause_button, Qt.Key_Down)
                assert second.volume == 42
                assert second.volume_slider.value() == second.vertical_volume.value() == 42
                assert second.volume_label.text() == '42'
                assert window.current_state()['wall'][1]['volume'] == 42
                assert not second.muted and not second.room['muted'], 'volume keys must unmute'
                assert not second.volume_button.muted
                player.set_muted.assert_called_with(False)
                second.set_volume(96)
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 100
                second.set_volume(4)
                QTest.keyClick(second.pause_button, Qt.Key_Down)
                assert second.volume == 0
                second.set_volume(42)
                with patch.object(window, '_tile_under_cursor', return_value=second):
                    wheel(second.pause_button, modifiers=Qt.ShiftModifier)
                    assert second.volume == 52, 'Shift+滚轮每次应调整 10 音量'
                    second.set_volume(42)
                for modifiers in (Qt.ControlModifier, Qt.ShiftModifier, Qt.AltModifier):
                    QTest.keyClick(second.pause_button, Qt.Key_Up, modifiers)
                    assert second.volume == 42
                edit = QLineEdit(second)
                edit.show()
                edit.setFocus()
                wheel(edit)
                wheel(second.video)
                QTest.keyClick(edit, Qt.Key_Up)
                QTest.keyClick(edit, Qt.Key_Down)
                assert second.volume == 42, 'input arrows must stay available for editing'
                edit.close()
                dialog = QDialog(window)
                button = QPushButton('test', dialog)
                QVBoxLayout(dialog).addWidget(button)
                dialog.setModal(True)
                dialog.show()
                dialog.activateWindow()
                button.setFocus()
                app.processEvents()
                wheel(button)
                wheel(second.video)
                QTest.keyClick(button, Qt.Key_Up)
                assert second.volume == 42, 'modal dialog must not control the player'
                dialog.close()
                second.window().activateWindow()
                second.pause_button.setFocus()
                app.processEvents()
                window._refresh_shortcuts()
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 52, 'refresh must not duplicate or lose fixed shortcuts'
                window._exit_fullscreen()
                app.processEvents()
                second.pause_button.setFocus()
                wheel(second.video)
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 52
                assert not window._handle_shortcut('Down')
            player.release.assert_not_called()
        finally:
            window.close()
            app.processEvents()
            window.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print('PASS: fullscreen wheel and Up/Down, bounds, UI/player/persistence and input isolation')


class FullscreenVolumeTests(unittest.TestCase):
    def test_fullscreen_wheel_and_keyboard(self):
        main()


if __name__ == '__main__':
    if '--native-wheel' in sys.argv:
        main()
    else:
        unittest.main()
