"""Stream coordination with Qt signals and fake media; no threads, network or accounts."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from ddm import app as app_module
from ddm.auto_quality import AUTO_QUALITY
from ddm.codec_control import CodecControl
from ddm.bili_workers import StreamResolver
from ddm.stream_playback import StreamPlayback
from ddm.wall_quality import WallQualityRequest, allows_wall_quality, wall_quality_request


class Resolver(QObject):
    resolved = Signal(str, str, int, str, list)
    failed = Signal(str, str)
    finished = Signal()

    def __init__(self, room_id, quality, parent, **options):
        super().__init__(parent)
        self.room_id, self.quality, self.options = room_id, quality, options
        self.headers = {'X-Fixture': 'stream'}
        self.cancelled = False
        self.login_required = self.codec_unavailable = False
        self.start = Mock()

    def cancel(self):
        self.cancelled = True

    def is_cancelled(self):
        return self.cancelled


class Player(QObject):
    stateChanged = Signal(str)
    pictureActivity = Signal()
    videoResolutionChanged = Signal(str)
    autoQualityRequested = Signal(int)
    decoderFallback = Signal(str)
    PROFILE_HEADERS = {'web': {'Referer': 'fixture'}}

    def __init__(self, video, parent):
        super().__init__(parent)
        self.video, self.stream_codec = video, ''
        self.auto_quality, self._decode_key = None, None
        self.paused = False
        for name in ('set_volume_normalization', 'set_volume', 'set_audio_channel', 'set_muted',
                     'set_paused', 'configure_auto_quality', 'play'):
            setattr(self, name, Mock())


class Tile(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.room = {'room_id': '1001', 'live': True, 'uname': 'fixture'}
        self.quality, self.volume, self.audio_channel = 250, 31, -1
        self.actual_quality, self._player_active = 0, False
        self.paused, self.muted = False, False
        self.codec_overrides, self.codec_probe_note = {}, ''
        self.stream_url, self.stream_profile, self.stream_codec = '', 'web', ''
        self.quality_options, self.stream_headers = [], {}
        self.video = QObject(self)
        self.set_status, self.set_buffering, self.set_live = Mock(), Mock(), Mock()
        self.set_actual_quality, self.set_quality_options = Mock(), Mock()
        self.reload_button, self.quality_button = Mock(), Mock()
        self._quality_text = Mock(return_value='自动 · 720p')
        self._layout_controls = Mock()
        self.isHidden = Mock(return_value=False)

    def set_paused(self, value):
        self.paused = value

    def set_quality(self, value):
        self.quality = value


class Host(QObject):
    def __init__(self):
        super().__init__()
        self.tile = Tile(self)
        self.wall = SimpleNamespace(tiles=[self.tile], main_index=lambda: 0)
        self.players, self._resolvers, self._stream_attempts = {}, {}, {}
        self._resolvers_running, self._freeze_refreshed = set(), set()
        self._capture_quality, self._pending_capture, self._codec_dialogs = {}, {}, {}
        self._accounts, self._match_sync_saved = {}, {}
        self.settings = {'bili_codec': 'avc', 'decode_mode': 'auto', 'auto_quality': True}
        self._closing, self._fullscreen_tile = False, None
        self.plugins = SimpleNamespace(platform_for=Mock(return_value=None), emit=Mock())
        self.playback_recovery, self.recorder = Mock(), Mock()
        self._save_timer, self._stats_refresh_timer = Mock(), Mock()
        for name in ('_offline_tile', '_sync_replay_scope', '_finish_pending_capture',
                     '_on_player_state', '_on_picture_activity', '_on_decoder_fallback',
                     '_on_picture_frozen', '_stop_tile', '_render_account', '_show_notice',
                     'refresh_status', '_schedule_retry', '_restore_capture_quality', '_record_notice'):
            setattr(self, name, Mock())
        self._match_sync_holds = Mock(return_value=False)
        self.stream_playback = StreamPlayback(self)
        self.codec_control = CodecControl(self)

    def _tile_of_player(self, player):
        return next((tile for tile, current in self.players.items() if current is player), None)


for name in ('_start_startup_tiles', 'start_all', 'apply_quality_policy', 'start_tile',
             '_on_resolver_finished', '_play_on', '_on_auto_quality', '_emit_stream_resolved',
             '_on_resolve_failed', '_codec_settings', '_is_bili_tile', '_keep_tile_codec', 'media_options'):
    setattr(Host, name, getattr(app_module.MainWindow, name))


class StreamPlaybackTests(unittest.TestCase):
    def test_source_resolution_is_reported_only_to_the_active_tile(self):
        self.tile.room['room_id'] = 'm3u:preset:fixture'
        self.tile.quality_options = [{'qn': 0, 'desc': '源自适应'}]
        self.tile.state_control = Mock()
        self.host._play_on(self.tile, 'https://cdn.test/live.m3u8', 0, 'm3u')
        player = self.host.players[self.tile]
        self.assertTrue(player.report_video_resolution)
        self.tile.state_control.set_source_resolution.assert_called_once_with('')
        player.videoResolutionChanged.emit('1920×1080')
        self.tile.state_control.set_source_resolution.assert_called_with('1920×1080')
        self.host.players.pop(self.tile)
        player.videoResolutionChanged.emit('1280×720')
        self.tile.state_control.set_source_resolution.assert_called_with('1920×1080')

    def test_chzzk_uses_overseas_proxy_and_stops_relay(self):
        from ddm.player import TilePlayer
        from ddm.follow_folders import PLATFORM_NAMES
        from ddm.auto_quality import OVERSEAS_PLATFORMS
        self.assertIn('chzzk', OVERSEAS_PLATFORMS)
        self.assertEqual(PLATFORM_NAMES['chzzk'], 'CHZZK')
        player = Mock(decode_mode='auto', silent=False, diagnostic_room='chzzk:' + 'a' * 32)
        relay = Mock(url='http://127.0.0.1:12345/fixture.m3u8')
        headers = {'User-Agent': 'fixture', 'Referer': 'https://chzzk.naver.com/'}
        with patch('ddm.hls_proxy.HlsProxy', return_value=relay) as factory, \
                patch('ddm.global_danmaku.request_proxy', return_value='http://127.0.0.1:7890'):
            TilePlayer._play_media(player, 'https://cdn.test/live.m3u8', 'chzzk', headers, [])
        self.assertEqual(factory.call_args.args[:3],
                         ('https://cdn.test/live.m3u8', headers, 'http://127.0.0.1:7890'))
        self.assertEqual(player._media, relay.url)
        self.assertEqual((player._buffer_limit, player._picture_limit), (20, 20))
        TilePlayer._stop_media(player)
        relay.stop.assert_called_once()
        self.assertIsNone(player._hls_proxy)

    def test_qie_hls_uses_relay_that_can_request_a_fresh_source(self):
        from ddm.player import TilePlayer
        player = Mock(decode_mode='auto', silent=False, diagnostic_room='qie:10210732')
        relay = Mock(url='http://127.0.0.1:12345/live.m3u8')
        url = 'https://cdn.test/live/10210732Mobile.m3u8?fixture=issued'
        headers = {'User-Agent': 'fixture', 'Referer': 'https://m.qie.tv/10210732'}
        with patch('ddm.hls_proxy.HlsProxy', return_value=relay) as factory, \
                patch('ddm.global_danmaku.request_proxy', return_value=None):
            TilePlayer._play_media(player, url, 'qie', headers, [])
        self.assertEqual(factory.call_args.args[:3], (url, headers, None))
        self.assertIs(player._hls_proxy, relay)
        self.assertEqual(player._media, relay.url)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = Host()
        self.tile = self.host.tile
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(app_module, 'StreamResolver', Resolver))
        self.stack.enter_context(patch.object(app_module, 'TilePlayer', Player))
        self.stack.enter_context(patch('builtins.print'))

    def tearDown(self):
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def test_first_stream_uses_selected_resolution_and_manual_change_removes_pending(self):
        self.tile.room.update(_streamer_playback=True, _streamer_pending_height=1440)
        self.assertEqual(self.host.apply_quality_policy(), [])
        self.host.start_tile(self.tile)
        resolver = self.host._resolvers[self.tile]
        self.assertEqual(resolver.streamer_height, 1440)
        resolver.applied_streamer_quality = True
        resolver.resolved.emit('1001', 'preferred', 15000, 'web', [])
        self.assertEqual(self.tile.quality, 15000)
        self.assertNotIn('_streamer_pending_height', self.tile.room)
        self.tile.room['_streamer_pending_height'] = 1440
        self.host._sender_tile = lambda: self.tile
        self.host.stream_playback.on_quality_changed(self.tile.room, 250)
        self.assertIsNone(self.host._resolvers[self.tile].streamer_height)
        self.assertEqual(self.tile.quality, 250)

    def test_pending_recording_cannot_follow_a_replaced_room(self):
        self.host._capture_quality[self.tile] = ('previous', 250)
        self.host._pending_capture[self.tile] = True
        self.host._restore_capture_quality.side_effect = self.host._capture_quality.pop
        self.tile.room.update(_streamer_playback=True, _streamer_pending_height=1440)
        self.host.start_tile(self.tile)
        self.host._restore_capture_quality.assert_called_once_with(self.tile)
        self.assertNotIn(self.tile, self.host._pending_capture)
        self.assertEqual(self.host._resolvers[self.tile].streamer_height, 1440)

    def test_resolver_tries_configured_resolution_then_lower_if_unavailable(self):
        resolver = StreamResolver('test:1001', 1, self.host, platform=object())
        resolver.streamer_height = 2160
        tiers = [{'desc': '3840x2160', 'qn': 4}, {'desc': '2560x1440', 'qn': 3},
                 {'desc': '1920x1080', 'qn': 1}]
        attempted = []
        def play():
            attempted.append(resolver.quality)
            if resolver.quality == 4:
                raise ValueError('4K unavailable')
            return 'preferred', 3, 'test', {}
        with patch.object(resolver, '_platform_play_url', side_effect=play):
            actual = resolver._prefer_streamer_resolution(('fallback', 1, 'test', {}), tiers)
        self.assertEqual(attempted, [4, 3])
        self.assertEqual(actual[:2], ('preferred', 3))
        self.assertTrue(resolver.applied_streamer_quality)

    def test_wall_quality_command_supersedes_first_streamer_request(self):
        self.tile.room.update(_streamer_playback=True, _streamer_pending_height=1440)
        self.host.start_tile(self.tile)
        previous = self.host._resolvers[self.tile]
        self.host.start_tile(self.tile, wall_quality=WallQualityRequest(720, (250, 80)))
        self.assertTrue(previous.cancelled)
        self.assertNotIn('_streamer_pending_height', self.tile.room)
        self.assertIsNone(getattr(self.host._resolvers[self.tile], 'streamer_height', None))

    def test_module_import_does_not_load_host_widgets_or_player(self):
        result = subprocess.run([sys.executable, '-c', "import sys; import ddm.stream_playback; "
            "assert not {'ddm.app','ddm.widgets','ddm.player','mpv'}.intersection(sys.modules)"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(vars(self.host.stream_playback), {'host': self.host})

    def test_request_gates_and_platform_offline_handling(self):
        for state in ('closing', 'empty', 'offline', 'missing-plugin', 'tray', 'sync'):
            with self.subTest(state=state):
                self.host._closing = state == 'closing'
                self.tile.room = {'room_id': '' if state == 'empty' else '1001', 'live': state != 'offline'}
                if state == 'missing-plugin':
                    self.tile.room['room_id'] = 'fixture:1'
                self.host._tray = SimpleNamespace(hold_playback=lambda tile: state == 'tray')
                self.host._match_sync_holds.return_value = state == 'sync'
                self.host.start_tile(self.tile)
                self.assertEqual(self.host._resolvers, {})
        self.assertIn(self.tile, self.host._match_sync_saved)
        self.host._offline_tile.assert_called_once_with(self.tile)

    def test_replacement_and_finished_preserve_request_identity_and_parent(self):
        self.host.start_tile(self.tile)
        first = self.host._resolvers[self.tile]
        self.host.start_tile(self.tile, stream_quality=80)
        second = self.host._resolvers[self.tile]
        self.assertTrue(first.is_cancelled())
        self.assertIs(first.parent(), self.host)
        self.assertIs(second.parent(), self.host)
        self.assertEqual((first.options['source_offset'], second.options['source_offset']), (0, 1))
        self.assertEqual(second.quality, 80)
        self.assertEqual(second.options['codec'], 'avc')
        first.finished.emit()
        self.assertIs(self.host._resolvers[self.tile], second)
        self.assertNotIn(first, self.host._resolvers_running)
        second.finished.emit()
        self.assertEqual(self.host._resolvers, {})
        self.assertEqual(self.host._resolvers_running, set())
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(first))
        self.assertFalse(isValid(second))

    def test_wall_resolution_candidates_use_only_the_requested_size_or_lower(self):
        self.tile.quality_options = [
            {'qn': 400, 'desc': '1080P'}, {'qn': 20000, 'desc': '4K'},
            {'qn': 15000, 'desc': '2K'}, {'qn': 250, 'desc': '超清'}]
        self.assertEqual(wall_quality_request(self.tile, 2160).tiers, (20000, 15000, 400, 250))
        self.assertFalse(allows_wall_quality(self.tile, wall_quality_request(self.tile, 2160), 250, []))
        self.assertTrue(allows_wall_quality(self.tile, WallQualityRequest(2160, (400, 250)), 250, []))
        self.assertEqual(wall_quality_request(self.tile, 1440).tiers, (15000, 400, 250))
        self.assertEqual(wall_quality_request(self.tile, 480).tiers, ())
        self.tile.room['room_id'] = 'fixture:1'
        self.tile.quality_options = [
            {'qn': 23, 'desc': '1080x1920'}, {'qn': 9, 'desc': '720x1280'},
            {'qn': 70, 'desc': '960x1706'}]
        self.assertEqual(wall_quality_request(self.tile, 1020).tiers, (70, 9))

    def test_wall_resolution_retries_lower_and_rejects_a_higher_returned_stream(self):
        self.host._play_on = Mock()
        self.tile.quality = self.tile.actual_quality = self.tile.room['quality'] = 80
        self.tile._player_active = True
        self.host.players[self.tile] = Player(self.tile.video, self.host)
        request = WallQualityRequest(2160, (20000, 15000, 250))
        self.host.start_tile(self.tile, wall_quality=request)
        first = self.host._resolvers[self.tile]
        self.assertEqual(first.quality, 20000)
        first.login_required = True
        first.failed.emit('1001', '4K requires login')
        second = self.host._resolvers[self.tile]
        self.assertEqual(second.quality, 15000)
        with patch('ddm.media_sources.discard') as discard:
            second.resolved.emit('1001', 'fixture:rejected', 20000, 'web', [])
            discard.assert_called_once_with('fixture:rejected')
        third = self.host._resolvers[self.tile]
        self.assertEqual(third.quality, 250)
        self.assertEqual(self.tile.room['quality'], 80)
        self.host._play_on.assert_not_called()
        third.resolved.emit('1001', 'fixture:720p', 250, 'web', [])
        self.assertEqual(self.tile.room['quality'], 250)
        self.assertEqual(self.host._play_on.call_args.args[1:3], ('fixture:720p', 250))
        self.assertEqual(self.host._play_on.call_args.kwargs['requested_quality'], 250)

    def test_wall_resolution_exhaustion_keeps_a_playing_picture(self):
        self.host._play_on = Mock()
        self.tile.quality = self.tile.actual_quality = self.tile.room['quality'] = 400
        self.tile._player_active = True
        self.tile.paused = True
        player = self.host.players[self.tile] = Player(self.tile.video, self.host)
        self.host.start_tile(self.tile, wall_quality=WallQualityRequest(720, (250, 80)))
        for quality in (250, 80):
            resolver = self.host._resolvers[self.tile]
            self.assertEqual(resolver.quality, quality)
            resolver.failed.emit('1001', 'fixture unavailable')
        self.assertFalse(self.host._resolvers)
        self.assertEqual((self.tile.quality, self.tile.actual_quality, self.tile.room['quality']), (400, 400, 400))
        self.assertIs(self.host.players[self.tile], player)
        self.assertTrue(self.tile.paused)
        self.assertIn('继续播放原画面', self.tile.codec_probe_note)
        self.tile.set_status.assert_not_called()
        self.host._play_on.assert_not_called()
        self.host._schedule_retry.assert_not_called()

    def test_wall_resolution_exhaustion_without_a_picture_reports_failure(self):
        for login_required in (False, True):
            with self.subTest(login_required=login_required):
                self.host.start_tile(self.tile, wall_quality=WallQualityRequest(720, (250, 80)))
                for quality in (250, 80):
                    resolver = self.host._resolvers[self.tile]
                    self.assertEqual(resolver.quality, quality)
                    resolver.login_required = login_required and quality == 80
                    resolver.failed.emit('1001', 'fixture unavailable')
                self.assertFalse(self.host._resolvers)
                detail = {'detail': 'fixture unavailable'} if login_required else {}
                self.tile.set_status.assert_called_with('连接失败', **detail)
        self.host._schedule_retry.assert_not_called()

    def test_wall_resolution_respects_a_recording_lock_set_during_the_request(self):
        self.host._play_on = Mock()
        self.host.start_tile(self.tile, wall_quality=WallQualityRequest(2160, (20000, 15000)))
        resolver = self.host._resolvers[self.tile]
        self.host._capture_quality[self.tile] = 250
        with patch('ddm.media_sources.discard') as discard:
            resolver.resolved.emit('1001', 'fixture:late', 20000, 'web', [])
            discard.assert_called_once_with('fixture:late')
        resolver.finished.emit()
        self.assertFalse(self.host._resolvers)
        self.assertEqual(self.tile.quality, 250)
        self.host._play_on.assert_not_called()

    def test_late_results_reject_changed_room_quality_codec_cancel_close_and_removal(self):
        self.host._play_on = Mock()
        for change in ('room', 'quality', 'codec', 'cancel', 'close', 'removed', 'superseded'):
            with self.subTest(change=change):
                self.tile.room['room_id'], self.tile.quality = '1001', 250
                self.host.settings['bili_codec'], self.host._closing = 'avc', False
                self.host.wall.tiles = [self.tile]
                self.host.start_tile(self.tile)
                pending = self.host._resolvers[self.tile]
                if change == 'room': self.tile.room['room_id'] = '1002'
                elif change == 'quality': self.tile.quality = 80
                elif change == 'codec': self.host.settings['bili_codec'] = 'av1'
                elif change == 'cancel': pending.cancel()
                elif change == 'close': self.host._closing = True
                elif change == 'removed': self.host.wall.tiles = []
                else: self.host.start_tile(self.tile)
                pending.resolved.emit('1001', 'fixture:stream', 250, 'web', [])
                pending.failed.emit('1001', 'fixture failure')
        self.host._play_on.assert_not_called()
        self.host.refresh_status.assert_not_called()

    def test_resolving_feedback_stays_until_current_request_finishes(self):
        self.host._play_on = Mock()
        self.host.start_tile(self.tile)
        first = self.host._resolvers[self.tile]
        self.tile.reload_button.set_refreshing.assert_called_with(True)
        self.tile.reload_button.setEnabled.assert_called_with(False)
        self.tile.quality_button.setText.assert_called_with('获取画质…')
        self.host.start_tile(self.tile)
        second = self.host._resolvers[self.tile]
        first.finished.emit()
        self.tile.reload_button.set_refreshing.assert_called_with(True)
        self.tile.reload_button.setEnabled.assert_called_with(False)
        second.resolved.emit('1001', 'fixture:stream', 250, 'web', [])
        self.tile.reload_button.set_refreshing.assert_called_with(False)
        self.tile.reload_button.setEnabled.assert_called_with(True)
        self.tile.quality_button.setText.assert_called_with('自动 · 720p')

    def test_resolving_failure_and_unexpected_finish_clear_feedback(self):
        self.host.start_tile(self.tile)
        current = self.host._resolvers[self.tile]
        current.failed.emit('1001', 'fixture failure')
        self.tile.reload_button.set_refreshing.assert_called_with(False)
        self.tile.reload_button.setEnabled.assert_called_with(True)
        self.host.start_tile(self.tile)
        self.host._resolvers[self.tile].finished.emit()
        self.tile.reload_button.set_refreshing.assert_called_with(False)
        self.tile.reload_button.setEnabled.assert_called_with(True)

    def test_resolved_pause_then_normal_result_uses_old_factory_and_headers(self):
        self.host._play_on = Mock()
        self.host.start_tile(self.tile)
        pending = self.host._resolvers[self.tile]
        self.tile.paused = True
        pending.resolved.emit('1001', 'fixture:stream', 250, 'web', [])
        self.assertTrue(self.tile.codec_reconnect_pending)
        self.host._play_on.assert_not_called()
        self.host.start_tile(self.tile)
        pending = self.host._resolvers[self.tile]
        pending.resolved.emit('1001', 'fixture:stream', 250, 'web', [])
        self.assertNotIn(self.tile, self.host._resolvers)
        self.assertIs(self.host._play_on.call_args.kwargs['headers'], pending.headers)
        self.assertEqual(self.host._play_on.call_args.kwargs['room_id'], '1001')

    def test_play_creates_owned_player_once_and_routes_callbacks_after_move(self):
        self.host._play_on(self.tile, 'fixture:first', 250, headers={'X-Fixture': 'copy'})
        player = self.host.players[self.tile]
        self.assertIs(player.parent(), self.host)
        self.assertIs(player.video, self.tile.video)
        self.assertEqual(player.stream_headers, {'X-Fixture': 'copy'})
        self.assertIsNot(player.stream_headers, self.tile.stream_headers)
        player.set_muted.assert_called_with(False)
        player.set_volume.assert_called_with(31)
        self.host.recorder.on_resolved.assert_called_once_with(self.tile)
        self.host.plugins.emit.assert_called_once()
        self.host._play_on(self.tile, 'fixture:second')
        self.assertIs(self.host.players[self.tile], player)
        replacement = Tile(self.host)
        self.host.players = {replacement: player}
        player.stateChanged.emit('playing')
        player.pictureActivity.emit()
        self.host._on_player_state.assert_called_once_with(replacement, 'playing')
        self.host._on_picture_activity.assert_called_once_with(replacement)
        player.decoderFallback.emit('none')
        self.host._on_decoder_fallback.assert_called_once_with(player, 'none')

    def test_play_rejects_stale_callbacks_and_does_not_emit_after_failure(self):
        self.host._play_on(self.tile, 'fixture:ignored', room_id='1002')
        self.host._play_on(self.tile, 'fixture:ignored', requested_quality=80)
        self.assertEqual(self.host.players, {})
        self.host._play_on(self.tile, 'fixture:first')
        player = self.host.players[self.tile]
        self.host.recorder.reset_mock()
        self.host.plugins.emit.reset_mock()
        player.play.side_effect = RuntimeError('fixture media failure')
        self.host._play_on(self.tile, 'fixture:failed')
        self.tile.set_status.assert_called_with('fixture media failure')
        self.host.recorder.on_resolved.assert_not_called()
        self.host.plugins.emit.assert_not_called()

    def test_auto_quality_uses_current_player_tile_and_pending_request_guard(self):
        player = Player(self.tile.video, self.host)
        self.host.players[self.tile] = player
        self.tile.quality = AUTO_QUALITY
        player.auto_quality = SimpleNamespace(room_id='1001')
        self.host.start_tile = Mock()
        self.host._on_auto_quality(player, 80)
        self.host.start_tile.assert_called_once_with(self.tile, stream_quality=80)
        self.host._resolvers[self.tile] = object()
        self.host._on_auto_quality(player, 250)
        self.host.start_tile.assert_called_once()

    def test_quality_policy_preserves_signal_block_and_manual_platform_capture_values(self):
        self.host.wall.tiles += [Tile(self.host), Tile(self.host)]
        self.host.wall.tiles[1].room['room_id'] = 'fixture:2'
        self.host._capture_quality[self.host.wall.tiles[2]] = 10000
        self.tile.blockSignals(True)
        self.assertEqual(self.host.apply_quality_policy(restart=False), [self.tile])
        self.assertTrue(self.tile.signalsBlocked())
        self.assertEqual([t.quality for t in self.host.wall.tiles], [10000, 250, 250])
        self.assertEqual(self.host._resolvers, {})

    def test_login_failure_and_capture_cleanup_keep_existing_decisions(self):
        self.tile.room['room_id'] = 'fixture:1'
        self.host._accounts['fixture'] = {}
        self.host._pending_capture[self.tile] = object()
        self.host._on_resolve_failed(self.tile, 'login fixture', login_required=True)
        self.assertNotIn(self.tile, self.host._pending_capture)
        self.host._restore_capture_quality.assert_called_once_with(self.tile)
        self.assertTrue(self.host._accounts['fixture']['_login_expired'])
        self.host._on_resolve_failed(self.tile, 'login fixture', login_required=True)
        self.host._show_notice.assert_called_once_with('login fixture', kind='warning')
        self.host._schedule_retry.assert_not_called()
        self.host.refresh_status.assert_not_called()

    def test_window_deletion_owns_requests_and_players_without_extra_qobjects(self):
        self.host.start_tile(self.tile)
        request = self.host._resolvers[self.tile]
        self.host._play_on(self.tile, 'fixture:first')
        player = self.host.players[self.tile]
        self.assertEqual(vars(self.host.stream_playback), {'host': self.host})
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(request))
        self.assertFalse(isValid(player))
        # tearDown must not queue deletion on an already deleted Qt object.
        self.host = QObject()


if __name__ == '__main__':
    unittest.main()
