"""悬停格子快捷键：弹幕、声音轮询、改键、输入保护及播放器声道路由。"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QPushButton, QVBoxLayout, QWidget
from ddm.app import MainWindow
from ddm.dialogs import SHORTCUT_ACTIONS, ShortcutSettingsPage
from ddm.widgets import VolumeButton
from ddm.plugins import TileControl


def check_hover_shortcuts(app, window):
    first, second = window.wall.tiles[:2]
    window.resize(1200, 760)
    window.show()
    window.activateWindow()
    app.processEvents()
    assert window.shortcuts['video_danmaku'] == 'B'
    # 焦点留在第一格按钮，鼠标只悬停第二格；不发送鼠标点击。
    first.pause_button.setFocus()
    point = second.video.mapToGlobal(second.video.rect().center())
    with patch('ddm.app.QCursor.pos', return_value=point):
        assert window._tile_under_cursor() is second
        before = second.danmaku_button.isChecked()
        QTest.keyClick(first.pause_button, Qt.Key_B)
        assert second.danmaku_button.isChecked() != before
        assert not first.danmaku_button.isChecked()
        QTest.keyClick(first.pause_button, Qt.Key_B)
        assert second.danmaku_button.isChecked() == before
        # 下拉框平时会吞掉字母键用于查找选项，窗口快捷键仍应先命中。
        combo = QComboBox(window)
        combo.addItems(['alpha', 'beta'])
        combo.show()
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key_B)
        assert second.danmaku_button.isChecked() != before
        assert combo.currentIndex() == 0
        combo.hide()
        second.danmaku_button.setChecked(before)
        with patch.object(window, '_on_fullscreen') as fullscreen:
            QTest.keyClick(first.pause_button, Qt.Key_F)
            fullscreen.assert_called_once_with(second)
        muted = second.muted
        QTest.keyClick(first.pause_button, Qt.Key_M)
        assert second.muted != muted
        second.set_muted(muted)
        window.sidebar.search.setFocus()
        window.sidebar.search.clear()
        QTest.keyClicks(window.sidebar.search, 'bfme')
        assert window.sidebar.search.text() == 'bfme'
        assert second.danmaku_button.isChecked() == before
        assert second.muted == muted
        dialog = QDialog(window)
        dialog.setModal(True)
        edit = QLineEdit(dialog)
        QVBoxLayout(dialog).addWidget(edit)
        dialog.show()
        edit.setFocus()
        app.processEvents()
        QTest.keyClick(edit, Qt.Key_B)
        assert edit.text() == 'b'
        assert second.danmaku_button.isChecked() == before
        button = QPushButton('button', dialog)
        dialog.layout().addWidget(button)
        button.setFocus()
        QTest.keyClick(button, Qt.Key_B)
        assert second.danmaku_button.isChecked() == before
        dialog.close()
        other = QWidget()
        other.show()
        other.activateWindow()
        app.processEvents()
        QTest.keyClick(other, Qt.Key_B)
        assert second.danmaku_button.isChecked() == before
        other.close()
        window.activateWindow()
        first.pause_button.setFocus()
        app.processEvents()
        page = ShortcutSettingsPage(window.shortcuts)
        page._edits['video_danmaku'].setKeySequence(QKeySequence('R'))
        window.shortcuts = page.values()
        window._refresh_shortcuts()
        QTest.keyClick(first.pause_button, Qt.Key_B)
        assert second.danmaku_button.isChecked() == before
        QTest.keyClick(first.pause_button, Qt.Key_R)
        assert second.danmaku_button.isChecked() != before
        assert window.current_state()['ui']['shortcuts']['video_danmaku'] == 'R'
        page.reset()
        window.shortcuts = page.values()
        window._refresh_shortcuts()
        second.danmaku_button.setChecked(before)
    with patch('ddm.app.QCursor.pos', return_value=window.mapToGlobal(QPoint(-100, -100))):
        QTest.keyClick(first.pause_button, Qt.Key_B)
        assert second.danmaku_button.isChecked() == before


def check_danmaku_input(app, window):
    first, second = window.wall.tiles[:2]
    class InputControl(TileControl):
        def __init__(self, context):
            super().__init__(QLineEdit(context.parent), minimum_width=90)
        def set_room(self, room):
            self.widget.setVisible(str(room.get('room_id', '')).isdigit())
        def focus_input(self):
            self.widget.setFocus(Qt.ShortcutFocusReason)
            return True
        def interaction_active(self):
            return self.widget.hasFocus()
    window.plugins.register_tile_control('test-input', 'edit', InputControl, priority=100)
    editors = [tile._plugin_controls.entries[0].control.widget for tile in (first, second)]
    window.resize(1800, 1000)
    window.show()
    window.activateWindow()
    app.processEvents()
    point = second.video.mapToGlobal(second.video.rect().center())
    with patch('ddm.app.QCursor.pos', return_value=point):
        first.pause_button.setFocus()
        QTest.keyClick(first.pause_button, Qt.Key.Key_Return)
        assert editors[1].hasFocus()
        assert not editors[0].hasFocus()
        edit = editors[1]
        confirmed_input = []
        edit.returnPressed.connect(lambda: confirmed_input.append(edit.text()))
        edit.setText('快捷输入')
        QTest.keyClick(edit, Qt.Key.Key_Return)
        assert confirmed_input == ['快捷输入']
        edit.clear()
        edit.clearFocus()
        second.setProperty('fullscreen', True)
        window._fullscreen_tile = second
        try:
            second.set_fullscreen_controls_hidden(True)
            first.pause_button.setFocus()
            QTest.keyClick(first.pause_button, Qt.Key.Key_Return)
            assert second._bar_target == 0.0
            assert not edit.hasFocus(), 'first Enter only restores the hidden bar'
            QTest.keyClick(first.pause_button, Qt.Key.Key_Enter)
            assert edit.hasFocus()
            outside = window.mapToGlobal(QPoint(-100, -100))
            with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=outside):
                window._fullscreen_cursor.update_cursor()
                second._hide_controls_if_outside()
            assert edit.hasFocus() and second._bar_target == 0.0
        finally:
            edit.clearFocus()
            window._fullscreen_cursor.stop()
            window._fullscreen_tile = None
            second.setProperty('fullscreen', False)
            second.set_fullscreen_controls_hidden(False)
        second.set_room({'room_id': 'douyu:1', 'uname': 'unsupported'})
        first.pause_button.setFocus()
        QTest.keyClick(first.pause_button, Qt.Key.Key_Return)
        assert not edit.hasFocus()
        second.set_room(dict(first.room))
        search = window.sidebar.search
        confirmed = []
        search.returnPressed.connect(lambda: confirmed.append(True))
        search.setFocus()
        QTest.keyClick(search, Qt.Key.Key_Return)
        assert confirmed and not editors[1].hasFocus()
        dialog = QDialog(window)
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        button = QPushButton('确认', dialog)
        button.setDefault(True)
        layout.addWidget(button)
        accepted = []
        button.clicked.connect(lambda: accepted.append(True))
        dialog.show()
        dialog.activateWindow()
        app.processEvents()
        QTest.keyClick(button, Qt.Key.Key_Return)
        assert accepted and not editors[1].hasFocus()
        dialog.close()
        window.activateWindow()
        page = ShortcutSettingsPage(window.shortcuts)
        page._edits['danmaku_input'].setKeySequence(QKeySequence('T'))
        window.shortcuts = page.values()
        window._refresh_shortcuts()
        first.pause_button.setFocus()
        app.processEvents()
        QTest.keyClick(first.pause_button, Qt.Key.Key_Return)
        assert not editors[1].hasFocus()
        QTest.keyClick(first.pause_button, Qt.Key.Key_T)
        assert editors[1].hasFocus()
        assert window.current_state()['ui']['shortcuts']['danmaku_input'] == 'T'
        editors[1].clearFocus()
        page.reset()
        window.shortcuts = page.values()
        window._refresh_shortcuts()
        assert all(not shortcut.autoRepeat() for shortcut in window._window_shortcuts)
    with patch.object(window, '_tile_under_cursor', return_value=None):
        first.pause_button.setFocus()
        QTest.keyClick(first.pause_button, Qt.Key.Key_Return)
        assert not editors[1].hasFocus()

    window.plugins._remove_tile_owner('test-input')


def check_corner_empty_slots(app):
    rooms = [dict(room_id=str(2000 + i), uname=f'corner {i}', live=True) for i in range(6)]
    window = MainWindow(rooms, [dict(rooms[0])], layout_id='corner',
                        state={'plugins_enabled': []})
    window.resize(1400, 850)
    window.show()
    window.activateWindow()
    app.processEvents()
    try:
        assert len(window.wall.tiles) == 6
        window.sidebar.settings_button.setFocus()
        for index, tile in enumerate(window.wall.tiles):
            # 起初只有主画面有房间，其余五个都是空格；焦点始终留在侧栏。
            assert bool(tile.room.get('room_id')) == (index == 0)
            point = window.wall.mapToGlobal(tile.geometry().center())
            with patch('ddm.app.QCursor.pos', return_value=point):
                assert window._tile_under_cursor() is tile
                before = [(t.muted, t.danmaku_button.isChecked()) for t in window.wall.tiles]
                QTest.keyClick(window.sidebar.settings_button, Qt.Key_B)
                QTest.keyClick(window.sidebar.settings_button, Qt.Key_M)
                for i, other in enumerate(window.wall.tiles):
                    expected = tuple(not value for value in before[i]) if i == index else before[i]
                    assert (other.muted, other.danmaku_button.isChecked()) == expected, (index, i)
                selected = (tile.muted, tile.danmaku_button.isChecked())
                # 音量属于格子；新拖入房间的弹幕开关默认关闭。
                if index:
                    window._on_room_dropped(tile, rooms[index]['room_id'])
                    assert (tile.muted, tile.danmaku_button.isChecked()) == (selected[0], False)
                current = (tile.muted, tile.danmaku_button.isChecked())
                QTest.keyClick(window.sidebar.settings_button, Qt.Key_B)
                QTest.keyClick(window.sidebar.settings_button, Qt.Key_M)
                assert (tile.muted, tile.danmaku_button.isChecked()) == tuple(not value for value in current)
                tile.danmaku_button.setChecked(before[index][1])
                assert (tile.muted, tile.danmaku_button.isChecked()) == before[index]
                saved = window.current_state()['wall'][index]
                assert (saved['muted'], saved['video_danmaku_enabled']) == before[index]
    finally:
        window.close()
        app.processEvents()


def main():
    app = QApplication([])
    room = {'room_id': '1001', 'uname': '测试', 'live': True,
            'muted': True, 'volume': 42, 'audio_channel': 0}
    with ExitStack() as stack:
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method))
        check_corner_empty_slots(app)
        window = MainWindow([dict(room)], [dict(room), dict(room)], layout_id='2x2',
                            state={'plugins_enabled': [], 'ui': {'shortcuts': {'mute': 'M', 'video_danmaku': 'D'}}})
        first, second = window.wall.tiles[:2]
        first_player = Mock()
        second_player = Mock()
        second_player.needs_audio_restart.return_value = False
        window.players.update({first: first_player, second: second_player})
        try:
            check_hover_shortcuts(app, window)
            check_danmaku_input(app, window)
            window.hide()
            # 迁移仅发生一次，此后手动改回 D 或其他键，重启仍须保留。
            for sequence in ('D', 'R'):
                state = window.current_state()
                state['ui']['shortcuts']['video_danmaku'] = sequence
                restored = MainWindow([], [], layout_id='1x1', state=state)
                try:
                    assert restored.shortcuts['video_danmaku'] == sequence
                finally:
                    restored.close()
            cursor = stack.enter_context(patch.object(window, '_tile_under_cursor', return_value=second))
            assert window.shortcuts['audio_cycle'] == 'E', 'old config must inherit the new default'
            assert ('audio_cycle', '声音轮询按键', 'E') in SHORTCUT_ACTIONS
            expected = [(False, 0), (False, VolumeButton.CHANNEL_LEFT),
                        (False, VolumeButton.CHANNEL_RIGHT), (True, VolumeButton.CHANNEL_RIGHT)]
            for _ in range(2):
                for muted, channel in expected:
                    QTest.keyClick(window, Qt.Key_E)
                    assert (second.muted, second.audio_channel) == (muted, channel)
                    assert second.room['muted'] == muted and second.room['audio_channel'] == channel
                    assert (first.muted, first.audio_channel, first.volume) == (True, 0, 42)
                    assert second.volume == 42
            first_player.set_muted.assert_not_called()
            first_player.set_audio_channel.assert_not_called()
            assert second_player.set_audio_channel.call_count == 6
            assert window.current_state()['wall'][1]['audio_channel'] == VolumeButton.CHANNEL_RIGHT
            # 更改按键后 E 不触发，保存值与恢复默认沿用原快捷键界面。
            page = ShortcutSettingsPage(window.shortcuts)
            page._edits['audio_cycle'].setKeySequence(QKeySequence('R'))
            window.shortcuts = page.values()
            QTest.keyClick(window, Qt.Key_E)
            assert second.muted
            QTest.keyClick(window, Qt.Key_R)
            assert not second.muted and second.audio_channel == 0
            page.reset()
            assert page.values()['audio_cycle'] == 'E'
            window.shortcuts = page.values()
            # 空格子或鼠标离开画面墙时不改变任何格子的声音。
            for target in (None, window.wall.tiles[2]):
                cursor.return_value = target
                QTest.keyClick(window, Qt.Key_E)
                assert not second.muted and second.audio_channel == 0
            cursor.return_value = second
            window.sidebar.search.clear()
            QTest.keyClick(window.sidebar.search, Qt.Key_E)
            assert window.sidebar.search.text() == 'e'
            assert second.audio_channel == 0, 'typing into search must not trigger the shortcut'
            # libmpv 原地更新声道滤镜，保留现有播放器。
            second_player.set_audio_channel.reset_mock()
            with patch.object(window, "start_tile") as restart:
                QTest.keyClick(window, Qt.Key_E)
                restart.assert_not_called()
            assert second.audio_channel == VolumeButton.CHANNEL_LEFT
            second_player.set_audio_channel.assert_called_once_with(VolumeButton.CHANNEL_LEFT)
            second_player.release.assert_not_called()
            first_player.release.assert_not_called()
        finally:
            window.close()
            app.processEvents()
    print('PASS: hover B/F/M without clicking, combo focus, input/modal/inactive isolation, remapping and E sound cycle without playback restart')


if __name__ == '__main__':
    main()
