"""Offline fullscreen Up/Down volume routing and input isolation checks."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QVBoxLayout
from ddm.app import MainWindow
from ddm.settings_general import GeneralSettingsPage
from ddm.settings_shortcuts import ShortcutSettingsPage


def wheel_over(widget, *, delta=120, modifiers=Qt.NoModifier):
    window = widget.window()
    point = widget.mapTo(window, widget.rect().center())
    QTest.wheelEvent(window.windowHandle(), point, QPoint(0, delta), stateKey=modifiers)


def main():
    app = QApplication([])
    with ExitStack() as stack:
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method, return_value=None))
        rooms = [dict(room_id=str(1001 + i), uname='test', live=False,
                      volume=42, muted=True) for i in range(2)]
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='2x2',
                            state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
        try:
            window.resize(1000, 700)
            window.show()
            window.activateWindow()
            app.processEvents()
            first, second = window.wall.tiles[:2]
            empty = window.wall.tiles[2]
            page = GeneralSettingsPage(window.settings)
            shortcuts = ShortcutSettingsPage(window.shortcuts, settings=window.settings)
            assert not page.values()['audio_follows_room']
            assert not shortcuts.settings_values()['hover_wheel_volume']
            page._checks['audio_follows_room'].setChecked(True)
            shortcuts.hover_wheel_volume.setChecked(True)
            wheel_over(first.video)
            assert first.volume == 42
            window.settings.update(page.values())
            window.settings.update(shortcuts.settings_values())
            assert window.current_state()['settings']['hover_wheel_volume']
            assert window.current_state()['settings']['audio_follows_room']
            wheel_over(first.video)
            assert first.volume == 45 and second.volume == 42
            wheel_over(first.video, delta=-120)
            assert first.volume == 42
            empty_volume = empty.volume
            wheel_over(empty.video)
            assert empty.volume == empty_volume and first.volume == 42, 'empty tiles must ignore the wheel'
            wheel_over(window.sidebar)
            assert first.volume == 42 and second.volume == 42, 'the sidebar must not adjust playback volume'
            page.reset()
            assert not page.values()['audio_follows_room']
            player = Mock()
            window.players[second] = player
            first.pause_button.setFocus()
            QTest.keyClick(first.pause_button, Qt.Key_Up)
            assert second.volume == first.volume == 42, 'windowed arrows must not adjust volume'
            window._on_fullscreen(second)
            app.processEvents()
            wheel_over(second.video)
            assert second.volume == 45 and first.volume == 42
            wheel_over(second.video, delta=-120)
            second.set_muted(True)
            second.pause_button.setFocus()
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
                    wheel_over(second.video, modifiers=Qt.ShiftModifier)
                    assert second.volume == 52, 'Shift+滚轮每次应调整 10 音量'
                    wheel_over(second.video, modifiers=Qt.ShiftModifier, delta=-120)
                    assert second.volume == 42
                    second.set_volume(42)
                    window.settings['wheel_volume_step'] = 7
                    window.settings['hover_wheel_volume_step'] = 4
                    window.shortcuts['volume_up'] = 'Alt+WheelUp'
                    wheel_over(second.video, modifiers=Qt.AltModifier)
                    assert second.volume == 49
                    wheel_over(second.video, modifiers=Qt.ShiftModifier, delta=-120)
                    assert second.volume == 42
                    wheel_over(second.video, delta=240)
                    assert second.volume == 50
                    wheel_over(second.video, delta=-120)
                    wheel_over(second.video, delta=-120)
                    assert second.volume == 42
                for modifiers in (Qt.ControlModifier, Qt.ShiftModifier, Qt.AltModifier):
                    QTest.keyClick(second.pause_button, Qt.Key_Up, modifiers)
                    assert second.volume == 42
                edit = QLineEdit(second)
                edit.show()
                edit.setFocus()
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
                QTest.keyClick(button, Qt.Key_Up)
                assert second.volume == 42, 'modal dialog must not control the player'
                dialog.close()
                second.window().activateWindow()
                second.pause_button.setFocus()
                app.processEvents()
                window._refresh_shortcuts()
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 52, 'refresh must not duplicate or lose fixed shortcuts'
                window.shortcuts.update(fullscreen_volume_up='Ctrl+U', pip_volume_up='Ctrl+P')
                window._refresh_shortcuts()
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                QTest.keyClick(second.pause_button, Qt.Key_P, Qt.ControlModifier)
                assert second.volume == 52
                QTest.keyClick(second.pause_button, Qt.Key_U, Qt.ControlModifier)
                assert second.volume == 62
                window._exit_fullscreen()
                app.processEvents()
                second.pause_button.setFocus()
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 62
                assert not window._handle_shortcut('Down')
            player.release.assert_not_called()
        finally:
            window.close()
            app.processEvents()
    print('PASS: fullscreen Up/Down +/-10, bounds, UI/player/persistence and input isolation')


if __name__ == '__main__':
    main()
