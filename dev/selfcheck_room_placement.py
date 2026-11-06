"""Room placement and audio ownership with local fakes; no Qt, media or network."""
from pathlib import Path
from contextlib import redirect_stderr
import io
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.room_placement import RoomPlacement


class Tile:
    def __init__(self, room_id='', *, volume=40, muted=False, audio_channel=0, **room):
        self.volume, self.muted, self.audio_channel = volume, muted, audio_channel
        self.room = dict(room_id=room_id, uname=room_id, live=True, **room)
        self.sync_audio_ui = Mock()
        self.raise_overlays = Mock()
        self._refresh_moved_overlays = Mock()
        self.bottom = Mock()
        self.bottom.updatesEnabled.return_value = True

    def set_room(self, room):
        self.room = dict(room or {})
        self.room.update(volume=self.volume, muted=self.muted, audio_channel=self.audio_channel)


class Host:
    def __init__(self, *tiles):
        self.wall = SimpleNamespace(tiles=list(tiles), relayout=Mock(), pane_danmaku=Mock())
        self.players = {}
        self.rooms = {tile.room['room_id']: dict(tile.room) for tile in tiles if tile.room['room_id']}
        self.sidebar = SimpleNamespace(watch_history=Mock())
        self.recorder = SimpleNamespace(stop=Mock())
        self._room_dict = Mock(side_effect=lambda rid: self.rooms.get(str(rid)))
        self._tile_of = lambda rid: next((tile for tile in self.wall.tiles
                                         if str(tile.room.get('room_id') or '') == str(rid)), None)
        self._prepare_room = Mock()
        self._stop_tile = Mock()
        self.start_tile = Mock()
        self.apply_quality_policy = Mock(return_value=[])
        self._refresh_meta = Mock()
        self.placement = RoomPlacement(self)
        self._hot_swap = self.placement.hot_swap


class RoomPlacementTests(unittest.TestCase):
    def test_controller_import_does_not_load_ui_or_player(self):
        subprocess.run([sys.executable, '-c',
            'import sys; import ddm.room_placement; '
            'assert not {"PySide6", "mpv", "ddm.app", "ddm.widgets", "ddm.player"}.intersection(sys.modules)'],
            cwd=ROOT, check=True, timeout=15)

    def test_new_room_stops_old_room_before_assignment_and_starts_once(self):
        target = Tile('old')
        host = Host(target)
        host.rooms['new'] = dict(room_id='new', uname='New', live=True)
        observed = []
        host._stop_tile.side_effect = lambda tile: observed.append(('stop', tile.room['room_id']))
        host.start_tile.side_effect = lambda tile: observed.append(('start', tile.room['room_id']))
        host.placement.drop_room(target, 'new')
        self.assertEqual(observed, [('stop', 'old'), ('start', 'new')])
        host.recorder.stop.assert_called_once_with(target)
        host.sidebar.watch_history.select.assert_called_once_with('new')
        host._refresh_meta.assert_called_once_with()

    def test_missing_room_and_same_room_do_not_restart(self):
        target = Tile('same')
        host = Host(target)
        host.placement.drop_room(target, 'missing')
        host.placement.drop_room(target, 'same')
        self.assertEqual(target.room['room_id'], 'same')
        host.recorder.stop.assert_not_called()
        host._stop_tile.assert_not_called()
        host.start_tile.assert_not_called()
        host._refresh_meta.assert_not_called()

    def test_existing_room_fallback_copies_room_switches_and_avoids_double_start(self):
        source, target = Tile('first', video_danmaku_enabled=True), Tile('second')
        host = Host(source, target)
        host._hot_swap = Mock(return_value=False)
        original = source.room
        def quality_policy():
            host.start_tile(source)
            return [source]
        host.apply_quality_policy.side_effect = quality_policy
        host.placement.drop_room(target, 'first')
        self.assertEqual([source.room['room_id'], target.room['room_id']], ['second', 'first'])
        self.assertTrue(target.room['video_danmaku_enabled'])
        self.assertIsNot(target.room, original)
        self.assertNotIn('video_danmaku_enabled', host.rooms['second'])
        self.assertEqual([call.args[0] for call in host.start_tile.call_args_list], [source, target])
        self.assertEqual([call.args[0] for call in host.recorder.stop.call_args_list], [source, target])
        host._hot_swap.assert_called_once_with(source, target)

    def test_drop_of_playing_room_swaps_tiles_without_recreating_players(self):
        source = Tile('first', volume=20, muted=True, audio_channel=1)
        target = Tile('second', volume=70, audio_channel=4)
        host = Host(source, target)
        first_player, second_player = Mock(), Mock()
        host.players.update({source: first_player, target: second_player})
        host.placement.drop_room(target, 'first')
        self.assertEqual(host.wall.tiles, [target, source])
        self.assertEqual([(t.volume, t.muted, t.audio_channel) for t in host.wall.tiles],
                         [(20, True, 1), (70, False, 4)])
        self.assertEqual(host.players, {source: first_player, target: second_player})
        first_player.set_volume.assert_called_once_with(70)
        second_player.set_muted.assert_called_once_with(True)
        first_player.set_audio_channel.assert_called_once_with(4)
        first_player.reapply_audio_channel.assert_called_once_with()
        source.sync_audio_ui.assert_called_once_with()
        host.recorder.stop.assert_not_called()
        host._stop_tile.assert_not_called()
        host.start_tile.assert_not_called()
        first_player.release.assert_not_called()
        second_player.release.assert_not_called()
        host.wall.relayout.assert_called_once_with(force=True)

    def test_drop_keeps_destination_position_when_swap_refresh_replaces_target(self):
        source, target, replacement = Tile('first'), Tile('second'), Tile('replacement')
        host = Host(source, target)
        first_player, second_player = Mock(), Mock()
        host.players.update({source: first_player, target: second_player})
        host._refresh_meta.side_effect = lambda: host.wall.tiles.__setitem__(0, replacement)
        output = io.StringIO()
        with redirect_stderr(output):
            host.placement.drop_room(target, 'first')
        self.assertEqual(host.wall.tiles, [replacement, source])
        self.assertIn('第 2 个格子', output.getvalue())
        self.assertEqual(host.players, {source: first_player, target: second_player})
        host.recorder.stop.assert_not_called()
        host._stop_tile.assert_not_called()
        host.start_tile.assert_not_called()
        first_player.release.assert_not_called()
        second_player.release.assert_not_called()

    def test_drop_ignores_a_target_removed_before_delivery(self):
        source, removed = Tile('first'), Tile('old')
        host = Host(source)
        host.placement.drop_room(removed, 'first')
        host._room_dict.assert_not_called()
        host._prepare_room.assert_not_called()
        host.sidebar.watch_history.select.assert_not_called()
        host.recorder.stop.assert_not_called()
        host._stop_tile.assert_not_called()
        host.start_tile.assert_not_called()
        host._refresh_meta.assert_not_called()

    def test_live_tile_swapped_with_empty_slot_preserves_position_audio(self):
        source = Tile('first', volume=10, muted=True, audio_channel=2)
        empty = Tile(volume=80, audio_channel=3)
        host = Host(source, empty)
        player = host.players[source] = Mock()
        self.assertTrue(host.placement.hot_swap(source, empty))
        self.assertEqual(host.wall.tiles, [empty, source])
        self.assertEqual([(t.volume, t.muted, t.audio_channel) for t in host.wall.tiles],
                         [(10, True, 2), (80, False, 3)])
        self.assertIs(host.players[source], player)
        host.start_tile.assert_not_called()

    def test_hot_swap_rejects_unready_offline_or_removed_tiles(self):
        for reason in ('unready', 'offline', 'removed'):
            with self.subTest(reason=reason):
                first, second = Tile('first'), Tile('second')
                host = Host(first, second)
                if reason == 'offline':
                    first.room['live'] = second.room['live'] = False
                elif reason == 'removed':
                    host.players.update({first: Mock(), second: Mock()})
                    host.wall.tiles.remove(second)
                before = list(host.wall.tiles)
                self.assertFalse(host.placement.hot_swap(first, second))
                self.assertEqual(host.wall.tiles, before)
                host.wall.relayout.assert_not_called()

    def test_swap_to_empty_slot_fallback_starts_only_the_filled_slot(self):
        source, empty = Tile('first'), Tile()
        host = Host(source, empty)
        host._hot_swap = Mock(return_value=False)
        host.placement.swap_tiles('first', empty)
        self.assertFalse(source.room.get('room_id'))
        self.assertEqual(empty.room['room_id'], 'first')
        host.start_tile.assert_called_once_with(empty)
        self.assertIsNot(empty.room, host.rooms['first'])

    def test_swap_of_missing_or_same_source_is_noop(self):
        target = Tile('first')
        host = Host(target)
        host.placement.swap_tiles('missing', target)
        host.placement.swap_tiles('first', target)
        host.recorder.stop.assert_not_called()
        host.start_tile.assert_not_called()


if __name__ == '__main__':
    unittest.main()
