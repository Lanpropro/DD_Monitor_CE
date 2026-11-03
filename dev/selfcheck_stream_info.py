"""Offline stream properties, menu dispatch, per-tile refresh and dialog cleanup."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.stream_info import StreamInfoDialog, format_stream_info
from ddm.widgets import Tile

APP = QApplication.instance() or QApplication([])
theme.danmaku_font_family()
APP.setStyleSheet(theme.qss())


class StreamInfoTests(unittest.TestCase):
    def player(self):
        widget = QWidget()
        player = TilePlayer(widget)
        self.addCleanup(widget.close)
        self.addCleanup(player.release)
        player.player = Mock()
        player._media = 'fixture'
        player.url = 'https://user:private@cdn.example.test/live.flv?token=secret'
        player.state = 'playing'
        return player

    def test_properties_units_and_source_host(self):
        player = self.player()
        props = {'video-params': {'w': 1920, 'h': 1080}, 'container-fps': 59.94,
                 'video-format': 'hevc', 'hwdec-current': 'd3d11va', 'file-format': 'flv',
                 'audio-params': {'samplerate': 44100, 'channels': 'stereo'},
                 'audio-codec-name': 'aac', 'audio-bitrate': 320000, 'video-bitrate': 2_000_000,
                 'metadata': {'ENCODER': 'obs-output'}, 'demuxer-cache-duration': 3.631,
                 'demuxer-cache-state': {'fw-bytes': 1048576}, 'demuxer-via-network': True,
                 'cache-speed': 256250, 'estimated-vf-fps': 59.91,
                 'decoder-frame-drop-count': 0, 'frame-drop-count': 2}
        player._prop = lambda key, default=None: props.get(key, default)
        info = player.stream_info()
        shown = format_stream_info(info)
        self.assertEqual(info['host'], 'cdn.example.test')
        self.assertNotIn('private', repr(info))
        self.assertNotIn('secret', repr(info))
        self.assertEqual(shown['download'], '2.05 Mbps')
        self.assertEqual(shown['video_bitrate'], '2 Mbps')
        self.assertIn('1920×1080', shown['video'])
        self.assertIn('59.94 FPS', shown['video'])
        self.assertIn('d3d11va', shown['video'])
        self.assertEqual(shown['audio'], 'aac · 44.1 kHz · 立体声 · 320 kbps')
        self.assertEqual(shown['buffer'], '3.63 秒 · 1 MiB')
        self.assertEqual(shown['encoder'], 'obs-output')
        self.assertIn('丢帧 0 / 2', shown['decode'])
        player.player.command.assert_not_called()

    def test_relay_speed_is_upstream_bits_and_marked_estimated(self):
        player = self.player()
        player._prop = lambda key, default=None: default
        player._hls_proxy = Mock()
        player._hls_proxy.network_speed.return_value = (2_500_000, 4)
        self.assertEqual(format_stream_info(player.stream_info())['download'], '2.5 Mbps（分片估算）')
        player._hls_proxy.network_speed.return_value = (0, 0)
        self.assertEqual(format_stream_info(player.stream_info())['download'], '未知')

    def test_absent_stopped_and_reconnecting_do_not_show_old_properties(self):
        player = self.player()
        player._prop = Mock(return_value=None)
        self.assertEqual(format_stream_info(player.stream_info())['video'], '未知')
        for state in ('connecting', 'error'):
            player.state = state
            player._prop.reset_mock()
            self.assertNotIn('video', player.stream_info())
            player._prop.assert_not_called()
        player._media = None
        self.assertEqual(player.stream_info(), {'state': 'idle'})
        player._released = True
        self.assertEqual(player.stream_info(), {'state': 'idle'})

    def test_local_media_has_no_network_download_rate(self):
        player = self.player()
        player.url = 'F:/fixtures/local.mp4'
        player._prop = lambda key, default=None: default
        info = player.stream_info()
        self.assertEqual(info['host'], '本地文件')
        self.assertEqual(format_stream_info(info)['download'], '未知')
        player.paused = True
        self.assertEqual(format_stream_info(player.stream_info())['state'], '已暂停')

    def test_menu_action_dispatches_after_menu_callback(self):
        tile = Tile({'room_id': '101', 'uname': 'Fixture'})
        self.addCleanup(tile.close)
        received = []
        tile.streamInfoRequested.connect(lambda: received.append(True))
        menu = tile.build_menu()
        action = next(action for action in menu.actions() if action.text() == '直播流信息…')
        action.trigger()
        self.assertEqual(received, [])
        APP.processEvents()
        self.assertEqual(received, [True])
        empty = Tile({})
        self.addCleanup(empty.close)
        self.assertFalse(next(action for action in empty.build_menu().actions()
                              if action.text() == '直播流信息…').isEnabled())

    def test_dialog_timer_updates_plain_text_and_stops_when_hidden(self):
        source = {'state': 'playing', 'host': '<b>plain.test</b>', 'room': 'Fixture'}
        dialog = StreamInfoDialog(lambda: dict(source))
        self.addCleanup(dialog.close)
        dialog.show()
        self.assertTrue(dialog.timer.isActive())
        self.assertEqual(dialog.values['host'].textFormat(), Qt.PlainText)
        self.assertEqual(dialog.values['host'].text(), '<b>plain.test</b>')
        source['host'] = 'changed.test'
        QTest.qWait(1200)
        self.assertEqual(dialog.values['host'].text(), 'changed.test')
        dialog.hide()
        self.assertFalse(dialog.timer.isActive())

    def test_main_window_menu_is_wired_to_its_own_player(self):
        with ExitStack() as stack:
            for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                           'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                           'load_cached_covers', 'load_cached_avatars', '_start_avatar_loader'):
                stack.enter_context(patch.object(MainWindow, method))
            stack.enter_context(patch('ddm.images.load_room_avatar', return_value=None))
            stack.enter_context(patch('ddm.images.load_cached_avatar', return_value=None))
            rooms = [{'room_id': '314', 'uname': 'Wired fixture', 'live': False}]
            window = MainWindow(rooms, rooms, layout_id='2x2', state={'plugins_enabled': []})
            try:
                tile = window.wall.tiles[0]
                player = Mock()
                player.stream_info.return_value = {'host': 'wired.test', 'state': 'playing'}
                window.players[tile] = player
                menu = tile.build_menu()
                next(action for action in menu.actions() if action.text() == '直播流信息…').trigger()
                APP.processEvents()
                self.assertEqual(window._stream_info_dialogs[tile].values['host'].text(), 'wired.test')
            finally:
                window.close()
            self.assertFalse(window._stream_info_dialogs)

    def test_reopen_is_singleton_and_refresh_follows_current_tile_player(self):
        window = QWidget()
        self.addCleanup(window.close)
        first = Tile({'room_id': '101', 'uname': 'First'})
        second = Tile({'room_id': '202', 'uname': 'Second'})
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        window._closing = False
        window.wall = SimpleNamespace(tiles=[first, second])
        window._stream_info_dialogs = {}
        window.players = {first: Mock(), second: Mock()}
        window.players[first].stream_info.return_value = {'host': 'first.test'}
        window.players[second].stream_info.return_value = {'host': 'second.test'}
        window._stream_info_snapshot = lambda tile: MainWindow._stream_info_snapshot(window, tile)
        MainWindow._open_tile_stream_info(window, first)
        MainWindow._open_tile_stream_info(window, second)
        dialog = window._stream_info_dialogs[first]
        self.addCleanup(dialog.close)
        self.addCleanup(window._stream_info_dialogs[second].close)
        MainWindow._open_tile_stream_info(window, first)
        self.assertEqual(len(window._stream_info_dialogs), 2)
        self.assertIs(window._stream_info_dialogs[first], dialog)
        first.room = {'room_id': '303', 'uname': 'Replacement'}
        replacement = Mock()
        replacement.stream_info.return_value = {'host': 'replacement.test'}
        window.players[first] = replacement
        dialog.refresh()
        self.assertIn('Replacement', dialog.room.text())
        self.assertEqual(dialog.values['host'].text(), 'replacement.test')
        del window.players[first]
        dialog.refresh()
        self.assertEqual(dialog.values['host'].text(), '未知')
        first.room = {}
        dialog.refresh()
        self.assertNotIn(first, window._stream_info_dialogs)
        self.assertFalse(dialog.timer.isActive())
        window.wall.tiles.remove(second)
        window._stream_info_dialogs[second].refresh()
        self.assertFalse(window._stream_info_dialogs)

    def test_stream_dialog_follows_independent_fullscreen_owner_and_survives_exit(self):
        with ExitStack() as stack:
            for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                           'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                           'load_cached_covers', 'load_cached_avatars', '_start_avatar_loader',
                           '_check_startup_update', '_check_startup_plugins'):
                stack.enter_context(patch.object(MainWindow, method))
            rooms = [{'room_id': '315', 'uname': 'Owner fixture', 'live': False}]
            window = MainWindow(rooms, rooms, layout_id='2x2', state={
                'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.setGeometry(-12000, -12000, 1000, 700)
            window.show()
            APP.processEvents()
            try:
                tile = window.wall.tiles[0]
                for _ in range(3):
                    window._fullscreen_presentation.enter(tile, QRect(-12000, -12000, 1200, 800))
                    window._open_tile_stream_info(tile)
                    dialog = window._stream_info_dialogs[tile]
                    APP.processEvents()
                    self.assertTrue(dialog.isVisible())
                    self.assertIs(dialog.windowHandle().transientParent(), tile.windowHandle())
                    dialog.hide()
                    window._open_tile_stream_info(tile)
                    self.assertIs(window._stream_info_dialogs[tile], dialog)
                    self.assertTrue(dialog.isVisible())
                    window._fullscreen_presentation.leave()
                    APP.processEvents()
                    self.assertTrue(dialog.isVisible())
                    self.assertTrue(dialog.timer.isActive())
                    self.assertIs(dialog.windowHandle().transientParent(), window.windowHandle())
            finally:
                window._fullscreen_presentation.leave()
                window.close()


if __name__ == '__main__':
    unittest.main()
