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
from ddm.stream_playback import StreamPlayback


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
        self.paused, self.muted = False, False
        self.codec_overrides, self.codec_probe_note = {}, ''
        self.stream_url, self.stream_profile, self.stream_codec = '', 'web', ''
        self.quality_options, self.stream_headers = [], {}
        self.video = QObject(self)
        self.set_status, self.set_buffering, self.set_live = Mock(), Mock(), Mock()
        self.set_actual_quality, self.set_quality_options = Mock(), Mock()
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
