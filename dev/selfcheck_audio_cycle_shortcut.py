"""声音轮询快捷键：循环、格子隔离、改键和播放器声道路由。"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
from ddm.dialogs import SHORTCUT_ACTIONS, ShortcutSettingsPage
from ddm.widgets import VolumeButton


def main():
    app = QApplication([])
    room = {'room_id': '1001', 'uname': '测试', 'live': True,
            'muted': True, 'volume': 42, 'audio_channel': 0}
    with ExitStack() as stack:
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method))
        window = MainWindow([dict(room)], [dict(room), dict(room)], layout_id='2x2',
                            state={'plugins_enabled': [], 'ui': {'shortcuts': {'mute': 'M'}}})
        first, second = window.wall.tiles[:2]
        first_player = Mock()
        second_player = Mock()
        second_player.needs_audio_restart.return_value = False
        window.players.update({first: first_player, second: second_player})
        cursor = stack.enter_context(patch.object(window, '_tile_under_cursor', return_value=second))
        try:
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
            # 切换到单声道需要重建音频路由时，沿用原播放器重启路径。
            second_player.needs_audio_restart.return_value = True
            window.start_tile.reset_mock()
            QTest.keyClick(window, Qt.Key_E)
            assert second.audio_channel == VolumeButton.CHANNEL_LEFT
            window.start_tile.assert_called_once_with(second)
            second_player.release.assert_called_once()
            first_player.release.assert_not_called()
        finally:
            window.close()
            app.processEvents()
    print('PASS: E sound cycle, duplicate-room isolation, shortcut migration/remapping, input safety and audio restart')


if __name__ == '__main__':
    main()
