"""Per-tile codec decisions and old dialog factory; fake Qt children, no media or accounts."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from ddm import app as app_module
from ddm.codec_control import CodecControl
from dev.selfcheck_stream_playback import Host, Player, Resolver, Tile


class Controls(QObject):
    changed = Signal(dict)

    def __init__(self, parent):
        super().__init__(parent)
        self.set_values = Mock()


class Dialog(QObject):
    finished = Signal(int)

    def __init__(self, values, parent, **options):
        super().__init__(parent)
        self.values, self.options = values, options
        self.controls = Controls(self)
        for name in ('show', 'raise_', 'activateWindow', 'setAttribute'):
            setattr(self, name, Mock())


for name in ('_restart_codec_tile', '_tile_codecs_changed', '_set_tile_codecs',
             '_codec_status', '_open_tile_codecs'):
    setattr(Host, name, getattr(app_module.MainWindow, name))


class CodecControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = Host()
        self.tile = self.host.tile
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(app_module, 'CodecSettingsDialog', Dialog))
        self.stack.enter_context(patch('builtins.print'))
        self.host.start_tile = Mock()

    def tearDown(self):
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def test_import_and_single_state_owner(self):
        code = "import sys; import ddm.codec_control; assert not {'ddm.app','ddm.widgets','ddm.dialogs'}.intersection(sys.modules)"
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(vars(self.host.codec_control), {'host': self.host})

    def test_inherited_and_per_tile_values_apply_without_mutating_global_settings(self):
        self.host.settings.update(bili_codec='hevc', decode_mode='none')
        other = Tile(self.host)
        self.tile.codec_overrides = {'bili_codec': 'av1'}
        self.assertEqual(self.host._codec_settings(self.tile), {'bili_codec': 'av1', 'decode_mode': 'none'})
        self.assertEqual(self.host._codec_settings(other)['bili_codec'], 'hevc')
        self.assertEqual(self.host.media_options(self.tile), ('hwdec=no',))
        self.host._set_tile_codecs(self.tile, {'bili_codec': 'avc', 'invalid': 'fixture'})
        self.assertEqual(self.tile.codec_overrides, {'bili_codec': 'avc'})
        self.assertEqual(self.host.settings['bili_codec'], 'hevc')
        self.host.start_tile.assert_called_once_with(self.tile)
        self.host._save_timer.start.assert_called_once()

    def test_restart_cancels_pending_and_defers_for_paused_hidden_offline_or_empty(self):
        for state in ('paused', 'hidden', 'offline', 'empty'):
            with self.subTest(state=state):
                pending = Resolver('1001', 250, self.host)
                self.host._resolvers[self.tile] = pending
                self.tile.paused = state == 'paused'
                self.tile.isHidden.return_value = state == 'hidden'
                self.tile.room = {'room_id': '' if state == 'empty' else '1001', 'live': state != 'offline'}
                self.host._restart_codec_tile(self.tile)
                self.assertTrue(pending.is_cancelled())
                self.assertTrue(self.tile.codec_reconnect_pending)
                self.assertNotIn(self.tile, self.host._resolvers)
        self.host.start_tile.assert_not_called()

    def test_unchanged_closed_or_removed_updates_do_not_restart_or_save(self):
        self.host._set_tile_codecs(self.tile, {})
        self.host.start_tile.assert_not_called()
        self.host._save_timer.start.reset_mock()
        self.host._closing = True
        self.host._set_tile_codecs(self.tile, {'bili_codec': 'av1'})
        self.host._closing = False
        self.host.wall.tiles = []
        self.host._set_tile_codecs(self.tile, {'bili_codec': 'av1'})
        self.assertEqual(self.tile.codec_overrides, {})
        self.host._save_timer.start.assert_not_called()

    def test_retained_codec_updates_original_dialog_and_reapplies_only_decoder(self):
        self.host._open_tile_codecs(self.tile)
        dialog = self.host._codec_dialogs[self.tile]
        player = Player(self.tile.video, self.host)
        player._decode_key = ('fixture', 'auto')
        player.stream_url, player.stream_profile, player.stream_headers = 'fixture:old', 'web', {}
        self.host.players[self.tile] = player
        self.tile.codec_overrides = {'bili_codec': 'av1', 'decode_mode': 'none'}
        self.host._keep_tile_codec(self.tile, 'av1', 'avc', unavailable=True)
        self.assertEqual(self.tile.codec_overrides, {'bili_codec': 'avc', 'decode_mode': 'none'})
        dialog.controls.set_values.assert_called_once_with(self.tile.codec_overrides)
        player.play.assert_called_once_with('fixture:old', 'web', {}, options=('hwdec=no',))
        self.host.start_tile.assert_not_called()
        self.host._save_timer.start.assert_called_once()

    def test_old_dialog_factory_parent_reuse_change_and_finish_contract(self):
        self.host._open_tile_codecs(self.tile)
        dialog = self.host._codec_dialogs[self.tile]
        self.assertIs(dialog.parent(), self.host)
        self.assertIs(dialog.values, self.tile.codec_overrides)
        self.assertTrue(dialog.options['bili_enabled'])
        dialog.setAttribute.assert_called_once_with(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.host._open_tile_codecs(self.tile)
        self.assertIs(self.host._codec_dialogs[self.tile], dialog)
        self.assertEqual(dialog.show.call_count, 2)
        dialog.raise_.assert_called_once()
        dialog.controls.changed.emit({'decode_mode': 'none'})
        self.assertEqual(self.tile.codec_overrides, {'decode_mode': 'none'})
        self.host.start_tile.assert_called_once_with(self.tile)
        dialog.finished.emit(0)
        self.assertNotIn(self.tile, self.host._codec_dialogs)

    def test_status_is_live_and_reports_pending_actual_source_and_decoder_fallback(self):
        self.host._open_tile_codecs(self.tile)
        status = self.host._codec_dialogs[self.tile].options['status']
        self.assertIn('没有播放', status())
        self.host._resolvers[self.tile] = Resolver('1001', 250, self.host)
        self.assertIn('正在连接', status())
        self.host._resolvers.clear()
        player = Player(self.tile.video, self.host)
        player.actual_codec, player.stream_codec = 'avc', 'avc'
        player.decode_mode, player.actual_decoder = 'auto', 'no'
        player._prop = lambda key: {'w': 1920, 'h': 1080}
        self.host.players[self.tile] = player
        self.tile.codec_overrides = {'bili_codec': 'av1'}
        self.assertIn('首选 AV1', status())
        self.assertIn('故障回退', status())
        self.assertIn('1920×1080', status())
        self.host._closing = True
        self.assertEqual(status(), '该窗口已关闭。')

    def test_decoder_callback_tracks_moved_player_and_ignores_detached_player(self):
        player = Player(self.tile.video, self.host)
        other = Tile(self.host)
        self.host.players[other] = player
        self.host.codec_control.decoder_fallback(player, 'none')
        other.set_status.assert_called_once()
        self.tile.set_status.assert_not_called()
        self.host.players.clear()
        self.host.codec_control.decoder_fallback(player, 'none')
        other.set_status.assert_called_once()

    def test_dialog_and_controls_are_destroyed_with_window(self):
        self.host._open_tile_codecs(self.tile)
        dialog = self.host._codec_dialogs[self.tile]
        controls = dialog.controls
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(dialog))
        self.assertFalse(isValid(controls))
        self.host = QObject()


if __name__ == '__main__':
    unittest.main()
