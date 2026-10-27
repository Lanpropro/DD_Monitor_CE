"""Offline checks for embedded player audio teardown options."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm.player import TilePlayer


class PlayerLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_audio_output_is_not_retained_until_gui_thread_termination(self):
        for silent in (False, True):
            with self.subTest(silent=silent), patch('ddm.player.mpv.MPV') as create:
                widget = QWidget()
                player = TilePlayer(widget, silent=silent)
                try:
                    player.bind()
                    options = create.call_args.kwargs
                    self.assertIs(options.get('gapless_audio'), False)
                    self.assertEqual(options['ao'], 'null' if silent else 'wasapi')
                    self.assertEqual(options['audio'], 'no' if silent else 'auto')
                    self.assertTrue(options['idle'])
                    self.assertTrue(options['keep_open'])
                    player.bind()
                    self.assertEqual(create.call_count, 1)
                    player.release()
                    player.release()
                    create.return_value.terminate.assert_called_once_with()
                finally:
                    player.release()
                    widget.close()

    def test_rebound_core_keeps_the_audio_teardown_option(self):
        widget = Mock()
        widget.winId.side_effect = (100, 200)
        with patch('ddm.player.mpv.MPV', side_effect=(Mock(), Mock())) as create:
            player = TilePlayer(widget)
            try:
                player.bind()
                first = player.player
                player.bind()
                first.terminate.assert_called_once_with()
                self.assertEqual(create.call_count, 2)
                for call in create.call_args_list:
                    self.assertIs(call.kwargs.get('gapless_audio'), False)
            finally:
                player.release()

    def test_shared_popup_keeps_one_idle_core_but_releases_media_and_watchers(self):
        widget = QWidget()
        with patch('ddm.player.mpv.MPV') as create:
            player = TilePlayer(widget, silent=True)
            try:
                player.bind()
                core = player.player
                for _ in range(25):
                    player._media = 'local-test.mp4'
                    player._watch.start()
                    player._picture_watch.start()
                    proxy = player._hls_proxy = Mock()
                    player.stop(keep_core=True)
                    self.assertIsNone(player._media)
                    self.assertIsNone(player._hls_proxy)
                    proxy.stop.assert_called_once_with()
                    self.assertFalse(player._watch.isActive())
                    self.assertFalse(player._picture_watch.isActive())
                    core.terminate.assert_not_called()
                    player.bind()
                self.assertEqual(create.call_count, 1, 'Only the shared popup retains a core')
                self.assertEqual(core.command.call_count, 25)
                self.assertTrue(all(call.args == ('stop',) for call in core.command.call_args_list))
                player.release()
                player.release()
                core.terminate.assert_called_once_with()
            finally:
                player.release()
                widget.close()

    def test_normal_thumbnail_stop_still_destroys_its_silent_core(self):
        widget = QWidget()
        with patch('ddm.player.mpv.MPV') as create:
            player = TilePlayer(widget, silent=True)
            try:
                player.bind()
                player.stop()
                create.return_value.terminate.assert_called_once_with()
                self.assertIsNone(player.player)
            finally:
                player.release()
                widget.close()

    def test_huya_uses_same_http_relay_as_probe_and_stops_it(self):
        for profile, relayed in (('huya', True), ('youtube', True), ('twitch', True), ('web', False)):
            with self.subTest(profile=profile):
                widget = QWidget()
                relay = Mock(url='http://127.0.0.1:34567/test.m3u8')
                with patch('ddm.player.mpv.MPV'), patch('ddm.hls_proxy.HlsProxy', return_value=relay) as create, \
                        patch('ddm.global_danmaku.request_proxy', return_value=None):
                    player = TilePlayer(widget)
                    try:
                        headers = {'User-Agent': 'fixture-UA', 'Referer': 'https://www.huya.com/'}
                        player.play('https://cdn.test/live.m3u8', profile, headers)
                        self.assertEqual(create.called, relayed)
                        self.assertEqual(player._media, relay.url if relayed else 'https://cdn.test/live.m3u8')
                        if relayed:
                            self.assertEqual(create.call_args.args[1], headers)
                            self.assertEqual(create.call_args.args[2], None)
                            player.stop()
                            relay.stop.assert_called_once_with()
                    finally:
                        player.release()
                        widget.close()

    def test_error_or_connecting_cannot_trigger_frozen_picture_recovery(self):
        widget = Mock()
        widget.isVisible.return_value = True
        widget.window.return_value.isMinimized.return_value = False
        player = TilePlayer(widget)
        player._media = 'fixture'
        try:
            for state in ('error', 'connecting', 'buffering'):
                player.state = state
                with patch.object(player, '_check_picture', return_value=False) as picture:
                    player._check_picture_tick()
                    picture.assert_called_once_with(False)
            player.play_session = 'new'
            player._transport_diagnostic('old', 'huya:123', host='cdn.test', resource='media',
                status=403, elapsed=1, attempt=1, local=False, error='HTTPError')
            self.assertEqual(player.source_failure, '', 'Old relay must not reject the new source')
        finally:
            player.release()

    def test_huya_recovery_has_one_timer_and_resets_only_after_stable_generation(self):
        from ddm.app import MainWindow
        tile = Mock(room={'room_id': 'huya:123'}, paused=False)
        host = SimpleNamespace(_resolvers={tile: object()}, _retry_timers={}, _retry_count={},
            _retry_now=Mock(), start_tile=Mock(), _closing=False, players={})
        MainWindow._schedule_retry(host, tile)
        MainWindow._on_picture_frozen(host, tile)
        self.assertFalse(host._retry_timers)
        host._resolvers.clear()
        with patch('ddm.app.QTimer') as timer:
            MainWindow._schedule_retry(host, tile)
            MainWindow._schedule_retry(host, tile)
            MainWindow._on_picture_frozen(host, tile)
            timer.assert_called_once_with(host)
            self.assertEqual(host._retry_count[tile], 1)
            host.start_tile.assert_not_called()
        player = SimpleNamespace(state='playing', state_generation=4)
        host.players[tile] = player
        MainWindow._reset_stable_huya_retry(host, tile, player, 3)
        self.assertIn(tile, host._retry_count)
        MainWindow._reset_stable_huya_retry(host, tile, player, 4)
        self.assertNotIn(tile, host._retry_count)


if __name__ == '__main__':
    unittest.main()
