"""Room-preset coordination with isolated host state; no window, media or accounts."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.room_preset_control import RoomPresetController


def host_fixture():
    # Tiles are dictionary keys in the real window.
    class Tile:
        def __init__(self):
            self.room = dict(room_id='one', uname='One')
            self.volume, self.muted, self.audio_channel = 40, False, 0
            self.blockSignals = Mock(return_value=False)
            self.set_volume = lambda value: setattr(self, 'volume', value)
            self.set_muted = lambda value: setattr(self, 'muted', value)
            self.set_audio_channel = lambda value: setattr(self, 'audio_channel', value)

    tile = Tile()
    wall = SimpleNamespace(layout_id='1x1', tiles=[tile], _layout_ratios={},
        _preset_dividers={}, _danmaku_cell=None,
        pane_danmaku=SimpleNamespace(custom=False, settings={}),
        _cancel_border_drag=Mock(), set_layout=Mock(), relayout=Mock())
    host = SimpleNamespace(wall=wall, room_presets={'version': 1, 'items': []},
        _fullscreen_tile=None, _room_preset_fullscreen_layout=None,
        _fullscreen_audio_saved={}, _active_room_preset_id='', _save_timer=Mock(),
        picture_in_picture=Mock(), _closing=False, recorder=SimpleNamespace(sessions={}),
        _pending_capture={}, _preset_retired_tiles=set(), _applying_room_preset=False,
        _cancel_interactive_resize=Mock(), hover_preview=Mock(), _clear_tile_room=Mock(),
        players={}, orientation='landscape', _layout_by_orientation={}, state={},
        sidebar=Mock(), _build_arrangement=Mock(), _refresh_meta=Mock(), refresh_status=Mock())
    host.room_preset_control = RoomPresetController(host)
    host.room_preset_snapshot = host.room_preset_control.snapshot
    return host, tile


class RoomPresetControlTests(unittest.TestCase):
    def test_import_does_not_load_window_widgets_or_player(self):
        subprocess.run([sys.executable, '-c',
            "import sys; import ddm.room_preset_control; "
            "assert not {'ddm.app','ddm.widgets','ddm.player','mpv'}.intersection(sys.modules)"],
            cwd=ROOT, check=True, timeout=15)

    def test_crud_uses_the_current_host_collection_and_preserves_snapshot(self):
        host, tile = host_fixture()
        control = host.room_preset_control
        key = control.save('  Match  ')
        self.assertEqual(host.room_presets['items'][0]['name'], 'Match')
        tile.volume = 90
        self.assertEqual(host.room_presets['items'][0]['slots'][0]['volume'], 40)
        control.save('Match', key)
        self.assertEqual(len(host.room_presets['items']), 1)
        self.assertEqual(host.room_presets['items'][0]['slots'][0]['volume'], 90)
        # Replacing restored configuration must not leave a stale controller-owned copy.
        host.room_presets = deepcopy(host.room_presets)
        control.rename(key, 'Renamed')
        self.assertEqual(host.room_presets['items'][0]['name'], 'Renamed')
        control.delete(key)
        self.assertEqual(host.room_presets['items'], [])
        self.assertEqual(host._active_room_preset_id, '')
        self.assertEqual(vars(control), {'host': host})

    def test_invalid_edits_do_not_write_or_mutate_the_collection(self):
        host, _ = host_fixture()
        control = host.room_preset_control
        key = control.save('Match')
        before = deepcopy(host.room_presets)
        host._save_timer.reset_mock()
        for edit in (lambda: control.save(''), lambda: control.save('Match'),
                     lambda: control.save('Other', 'missing'),
                     lambda: control.rename(key, ''), lambda: control.rename('missing', 'Other')):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                edit()
            self.assertEqual(host.room_presets, before)
        host._save_timer.start.assert_not_called()

    def test_fullscreen_snapshot_uses_saved_layout_and_original_sound(self):
        host, tile = host_fixture()
        before = host.room_preset_control.snapshot()
        host._fullscreen_tile = tile
        host._room_preset_fullscreen_layout = deepcopy(before['layout'])
        host._fullscreen_audio_saved = {tile: False}
        tile.muted = True
        snapshot = host.room_preset_control.snapshot()
        self.assertEqual(snapshot, before)
        snapshot['slots'][0]['volume'] = 5
        self.assertEqual(tile.volume, 40)
        snapshot['layout']['ratios']['probe'] = [1]
        self.assertNotIn('probe', host._room_preset_fullscreen_layout['ratios'])

    def test_same_combination_is_idempotent_and_only_updates_selection_once(self):
        host, _ = host_fixture()
        key = host.room_preset_control.save('Match')
        host._save_timer.reset_mock()
        self.assertTrue(host.room_preset_control.apply(key))
        host._save_timer.start.assert_not_called()
        host._active_room_preset_id = ''
        self.assertTrue(host.room_preset_control.apply(key))
        host._save_timer.start.assert_called_once_with()
        host._clear_tile_room.assert_not_called()
        host.wall.set_layout.assert_not_called()
        host.refresh_status.assert_not_called()

    def test_closing_or_invalid_restore_does_not_change_tiles(self):
        host, _ = host_fixture()
        control = host.room_preset_control
        host._closing = True
        self.assertFalse(control.apply('missing'))
        host._closing = False
        with self.assertRaises(ValueError):
            control.apply('missing')
        host._clear_tile_room.assert_not_called()
        host._cancel_interactive_resize.assert_not_called()

    def test_refusing_recording_or_pending_capture_replacement_keeps_all_state(self):
        from PySide6.QtWidgets import QMessageBox
        for pending in (False, True):
            with self.subTest(pending=pending):
                host, tile = host_fixture()
                target = host.room_preset_control.snapshot()
                target['slots'][0]['room_id'] = 'other'
                host.room_presets['items'] = [dict(target, id='target')]
                if pending:
                    host._pending_capture[tile] = True
                else:
                    host.recorder.sessions[tile] = SimpleNamespace(recording=True, stopping=False)
                before = list(host.wall.tiles)
                with patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as question:
                    self.assertFalse(host.room_preset_control.apply('target'))
                question.assert_called_once()
                self.assertEqual(host.wall.tiles, before)
                host._clear_tile_room.assert_not_called()
                host.hover_preview.cancel.assert_not_called()
                self.assertFalse(host._applying_room_preset)

    def test_application_failure_clears_transaction_flag_and_does_not_report_success(self):
        host, _ = host_fixture()
        target = host.room_preset_control.snapshot()
        target['slots'][0]['room_id'] = 'other'
        host.room_presets['items'] = [dict(target, id='target')]
        host._clear_tile_room.side_effect = RuntimeError('fixture stop failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture stop failure'):
            host.room_preset_control.apply('target')
        self.assertFalse(host._applying_room_preset)
        self.assertEqual(host._active_room_preset_id, '')
        host._save_timer.start.assert_not_called()
        host.refresh_status.assert_not_called()

    def test_sound_restore_keeps_existing_player_and_commits_after_layout(self):
        host, tile = host_fixture()
        key = host.room_preset_control.save('Match')
        tile.volume, tile.audio_channel, tile.muted = 90, 3, True
        player = Mock()
        host.players[tile] = player
        order = []
        host.wall.relayout.side_effect = lambda **_: order.append('layout')
        host._refresh_meta.side_effect = lambda: order.append('meta')
        host.refresh_status.side_effect = lambda **_: order.append('status')
        self.assertTrue(host.room_preset_control.apply(key))
        self.assertIs(host.players[tile], player)
        player.release.assert_not_called()
        player.set_volume.assert_called_once_with(40)
        player.set_audio_channel.assert_called_once_with(0)
        player.set_muted.assert_called_once_with(False)
        self.assertEqual(order, ['layout', 'meta', 'status'])
        self.assertEqual(tile.blockSignals.call_args_list[0].args, (True,))
        self.assertEqual(tile.blockSignals.call_args_list[-1].args, (False,))
        self.assertFalse(host._applying_room_preset)


if __name__ == '__main__':
    unittest.main()
