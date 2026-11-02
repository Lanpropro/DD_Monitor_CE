"""Offline recovery contracts based on captured Douyu EOF/stall; not live stability evidence."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.playback_recovery import PlaybackRecovery
from ddm import plugins as plugin_api


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_direct_eof_reports_immediately_without_waiting_for_stall_limit(self):
        props = {'time-pos': 23.876, 'eof-reached': True}
        player = SimpleNamespace(paused=False, _released=False, _media='fixture',
            _hls_proxy=None, _recover_decoder=lambda: False, _last_time=23.876,
            _prop=lambda key, default=None: props.get(key, default), stream_profile='douyu',
            source_failure='', _set_state=Mock())
        TilePlayer._check(player)
        player._set_state.assert_called_once_with('error')
        self.assertEqual(player.source_failure, 'LIVE_EOF')

    def test_error_feedback_precedes_new_source_request(self):
        tile = Mock(room={'room_id': 'douyu:123'})
        player = SimpleNamespace(stream_url='https://fixture.invalid/live', source_failure='LIVE_EOF')
        host = SimpleNamespace(players={tile: player}, plugins=Mock(), _clear_freeze_recovery=Mock(),
                               refresh_status=Mock(), _schedule_retry=Mock())
        MainWindow._on_player_state(host, tile, 'error')
        host.plugins.emit.assert_called_once_with(plugin_api.EVENT_STREAM_FAILED, tile=tile,
            room=dict(tile.room), source_url=player.stream_url, reason='LIVE_EOF')
        host._schedule_retry.assert_called_once_with(tile)

    def test_initial_idle_does_not_trigger_eof_recovery(self):
        props = {'idle-active': True}
        player = SimpleNamespace(paused=False, _released=False, _media='fixture',
            _hls_proxy=None, _recover_decoder=lambda: False, _last_time=None,
            _prop=lambda key, default=None: props.get(key, default), stream_profile='douyu',
            source_failure='', _set_state=Mock(), _stall_ticks=0, _buffer_limit=6)
        TilePlayer._check(player)
        self.assertEqual(player.source_failure, '')
        self.assertNotIn(unittest.mock.call('error'), player._set_state.call_args_list)

    def test_eof_retry_and_stable_success_use_huya_policy(self):
        host = QObject()
        tile = Mock(room={'room_id': 'douyu:123'})
        player = SimpleNamespace(source_failure='LIVE_EOF', state='playing', state_generation=2)
        host.players, host._resolvers, host._closing = {tile: player}, {}, False
        recovery = PlaybackRecovery(host)
        try:
            recovery.retry_count[tile] = 8
            recovery.schedule_retry(tile)
            self.assertEqual(recovery.retry_timers[tile].interval(), 5000)
            with patch('ddm.playback_recovery.QTimer.singleShot') as schedule:
                recovery.reset_retry_after_playing(tile)
            delay, context, callback = schedule.call_args.args
            self.assertEqual(delay, 15000)
            player.state_generation += 1
            callback()
            self.assertIn(tile, recovery.retry_count)
            player.state_generation -= 1
            callback()
            self.assertNotIn(tile, recovery.retry_count)
        finally:
            recovery.shutdown()

    def test_frozen_video_reports_source_before_refresh(self):
        tile = Mock(room={'room_id': 'douyu:123'})
        player = SimpleNamespace(stream_url='https://fixture.invalid/live')
        calls = Mock()
        host = SimpleNamespace(players={tile: player}, plugins=SimpleNamespace(emit=calls.emit),
                               _on_picture_frozen=calls.refresh)
        MainWindow._on_player_state(host, tile, 'frozen')
        self.assertEqual([call[0] for call in calls.mock_calls], ['emit', 'refresh'])
        self.assertEqual(calls.emit.call_args.kwargs['reason'], 'STALL')

    def test_audio_video_split_is_detected_even_after_buffering_state(self):
        props = {'time-pos': 12.518, 'audio-pts': 13.447, 'vo-configured': True}
        player = SimpleNamespace(_released=False, _media='fixture', state='buffering',
            stream_profile='douyu', paused=False, freeze_watch=True, _last_picture=None,
            _frozen_ticks=0, _picture_limit=2, pictureActivity=Mock(),
            _prop=lambda key, default=None: props.get(key, default),
            _recover_decoder=Mock(return_value=False), _set_state=Mock(), video_widget=Mock())
        player.video_widget.isVisible.return_value = True
        player.video_widget.window.return_value.isMinimized.return_value = False
        player._picture_signature = lambda: TilePlayer._picture_signature(player)
        player._check_picture = lambda playing: TilePlayer._check_picture(player, playing)
        for audio in (13.447, 14.448, 15.448):
            props['audio-pts'] = audio
            TilePlayer._check_picture_tick(player)
        player._set_state.assert_called_once_with('frozen')
        # Cache-driven pause must not be mistaken for audio/video separation.
        props['paused-for-cache'] = True
        player._set_state.reset_mock()
        for _ in range(4):
            TilePlayer._check_picture_tick(player)
        player._set_state.assert_not_called()
        self.assertEqual(player._frozen_ticks, 0)

    def test_normal_progress_keeps_direct_playback_and_does_not_recover(self):
        for profile, limit in (('douyu', 2), ('douyin', 8), ('web', 2)):
            with self.subTest(profile=profile), patch('ddm.hls_proxy.HlsProxy') as relay:
                widget = Mock()
                widget.isVisible.return_value = True
                widget.window.return_value.isMinimized.return_value = False
                player = TilePlayer(widget)
                props = {'vo-configured': True, 'time-pos': 1., 'audio-pts': 1.}
                changes = Mock()
                player.stateChanged.connect(changes)
                player.actual_quality = 2000015
                try:
                    with patch.object(player, 'bind'), \
                            patch.object(player, '_prop', side_effect=lambda key, default=None: props.get(key, default)):
                        player._play_media('https://fixture.invalid/live', profile, {}, ())
                        self.assertEqual(player._picture_limit, limit)
                        self.assertEqual(player._media, 'https://fixture.invalid/live')
                        self.assertEqual(player.actual_quality, 2000015)
                        relay.assert_not_called()
                        for position in range(1, 21):
                            props['time-pos'] = props['audio-pts'] = float(position)
                            player._check()
                            player._check_picture_tick()
                        self.assertEqual(player.state, 'playing')
                        self.assertEqual(player.source_failure, '')
                        self.assertNotIn(unittest.mock.call('frozen'), changes.call_args_list)
                        self.assertNotIn(unittest.mock.call('error'), changes.call_args_list)
                finally:
                    player.release()

    def test_picture_recovery_excludes_pause_cache_wait_hidden_and_missing_frames(self):
        cases = ('paused', 'cache-wait', 'hidden', 'minimized', 'no-video', 'zero-position', 'watch-disabled')
        for case in cases:
            with self.subTest(case=case):
                widget = Mock()
                widget.isVisible.return_value = case != 'hidden'
                widget.window.return_value.isMinimized.return_value = case == 'minimized'
                player = TilePlayer(widget)
                player._media, player.stream_profile, player.state = 'fixture', 'douyu', 'playing'
                player.paused = case == 'paused'
                player.freeze_watch = case != 'watch-disabled'
                props = {'time-pos': 0. if case == 'zero-position' else 1., 'audio-pts': 5.,
                         'vo-configured': case != 'no-video', 'paused-for-cache': case == 'cache-wait'}
                try:
                    with patch.object(player, '_prop', side_effect=lambda key, default=None: props.get(key, default)):
                        for _ in range(10):
                            player._check_picture_tick()
                    self.assertEqual(player.state, 'playing')
                    self.assertEqual(player._frozen_ticks, 0)
                finally:
                    player.release()

    def test_two_second_policy_can_refresh_before_a_short_video_gap_recovers(self):
        # A policy boundary, not evidence that such a gap is healthy or that it
        # caused the user's real fault. The previous 8-tick policy waits longer.
        for limit, expected in ((2, 'frozen'), (8, 'playing')):
            with self.subTest(limit=limit):
                widget = Mock()
                widget.isVisible.return_value = True
                widget.window.return_value.isMinimized.return_value = False
                player = TilePlayer(widget)
                player._media, player.stream_profile, player.state = 'fixture', 'douyu', 'playing'
                player._picture_limit = limit
                props = {'time-pos': 1., 'audio-pts': 1., 'vo-configured': True}
                try:
                    with patch.object(player, '_prop', side_effect=lambda key, default=None: props.get(key, default)):
                        for audio in (1., 2., 3.):
                            props['audio-pts'] = audio
                            player._check_picture_tick()
                    self.assertEqual(player.state, expected)
                finally:
                    player.release()

    def test_upstream_eof_does_not_discard_buffered_playback(self):
        widget = Mock()
        player = TilePlayer(widget)
        player._media, player.stream_profile, player.state = 'fixture', 'douyu', 'playing'
        props = {'time-pos': 1., 'vo-configured': True, 'eof-reached': False,
                 'demuxer-cache-state': {'eof': True}}
        try:
            with patch.object(player, '_prop', side_effect=lambda key, default=None: props.get(key, default)):
                for position in (1., 2., 3.):
                    props['time-pos'] = position
                    player._check()
                self.assertEqual(player.state, 'playing')
                self.assertEqual(player.source_failure, '')
                props['eof-reached'] = True
                player._check()
                self.assertEqual(player.state, 'error')
                self.assertEqual(player.source_failure, 'LIVE_EOF')
        finally:
            player.release()


if __name__ == '__main__':
    unittest.main()
