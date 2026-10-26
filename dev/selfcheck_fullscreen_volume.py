"""Offline fullscreen Up/Down volume routing and input isolation checks."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QVBoxLayout
from ddm.app import MainWindow


def main():
    app = QApplication([])
    with ExitStack() as stack:
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', '_grab_fullscreen_frame'):
            stack.enter_context(patch.object(MainWindow, method, return_value=None))
        rooms = [dict(room_id=str(1001 + i), uname='test', live=False,
                      volume=42, muted=True) for i in range(2)]
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='2x2',
                            state={'plugins_enabled': []})
        try:
            window.resize(1000, 700)
            window.show()
            window.activateWindow()
            app.processEvents()
            first, second = window.wall.tiles[:2]
            player = Mock()
            window.players[second] = player
            first.pause_button.setFocus()
            QTest.keyClick(first.pause_button, Qt.Key_Up)
            assert second.volume == first.volume == 42, 'windowed arrows must not adjust volume'
            window._on_fullscreen(second)
            app.processEvents()
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
                assert second.muted, 'volume keys must preserve the mute choice'
                second.set_volume(96)
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 100
                second.set_volume(4)
                QTest.keyClick(second.pause_button, Qt.Key_Down)
                assert second.volume == 0
                second.set_volume(42)
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
                window.activateWindow()
                second.pause_button.setFocus()
                app.processEvents()
                window._refresh_shortcuts()
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 52, 'refresh must not duplicate or lose fixed shortcuts'
                window._exit_fullscreen()
                app.processEvents()
                second.pause_button.setFocus()
                QTest.keyClick(second.pause_button, Qt.Key_Up)
                assert second.volume == 52
                assert not window._handle_shortcut('Down')
            player.release.assert_not_called()
        finally:
            window.close()
            app.processEvents()
    print('PASS: fullscreen Up/Down +/-10, bounds, UI/player/persistence and input isolation')


if __name__ == '__main__':
    main()
