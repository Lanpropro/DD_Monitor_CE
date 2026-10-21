"""Offline room audio identity across replacement, swaps, layout and restart."""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from ddm import config
from ddm.app import MainWindow
from ddm.player import TilePlayer

APP = QApplication.instance() or QApplication([])
ROOMS = [dict(room_id='1001', uname='A', live=False, volume=17, muted=False),
         dict(room_id='1002', uname='B', live=False, volume=83, muted=True),
         dict(room_id='1003', uname='C', live=False)]


class RoomAudioTests(unittest.TestCase):
    all_windows = []

    @classmethod
    def tearDownClass(cls):
        for window in cls.all_windows:
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.processEvents()
        cls.all_windows.clear()

    def setUp(self):
        self.stack = ExitStack()
        self.windows = []
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', '_check_startup_plugins'):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.window = self.make_window()

    def tearDown(self):
        for window in reversed(self.windows):
            window.close()
        APP.processEvents()
        self.stack.close()

    def make_window(self, state=None):
        state = deepcopy(state) if state is not None else {
            'plugins_enabled': [], 'settings': {'auto_update': False,
            'default_volume': 37, 'default_muted': True}}
        if 'wall' in state:
            rooms, wall = config.build_rooms(state)
        else:
            rooms, wall = deepcopy(ROOMS), deepcopy(ROOMS[:2])
        with patch('ddm.app.QTimer.singleShot'):
            window = MainWindow(rooms, wall, layout_id='1x2', state=state)
        window._poll_timer.stop()
        window._stats_timer.stop()
        self.windows.append(window)
        self.all_windows.append(window)
        return window

    def assert_sound(self, tile, level, muted):
        self.assertEqual((tile.volume, tile.muted), (level, muted))
        self.assertEqual((tile.room['volume'], tile.room['muted']), (level, muted))
        self.assertEqual((tile.volume_slider.value(), tile.vertical_volume.value()), (level, level))
        self.assertEqual((tile.volume_label.text(), tile.vertical_volume_label.text()),
                         (str(level), str(level)))
        self.assertEqual(tile.volume_button.muted, muted)

    def test_replacement_restores_incoming_room_audio_without_unmuting(self):
        tile = self.window.wall.tiles[0]
        tile.set_room(dict(room_id='2001', volume=0, muted=True))
        self.assert_sound(tile, 0, True)

    def test_cold_swap_moves_audio_with_each_room(self):
        first, second = self.window.wall.tiles
        self.window._on_tile_swapped('1001', second)
        self.assertEqual([tile.room['room_id'] for tile in self.window.wall.tiles], ['1002', '1001'])
        self.assert_sound(first, 83, True)
        self.assert_sound(second, 17, False)

    def test_hot_swap_keeps_room_audio_and_updates_its_existing_player(self):
        first, second = self.window.wall.tiles
        for tile in (first, second):
            tile.room['live'] = True
            self.window.players[tile] = Mock(spec=TilePlayer)
        self.assertTrue(self.window._hot_swap(first, second))
        self.assertEqual(self.window.wall.tiles, [second, first])
        self.assert_sound(first, 17, False)
        self.assert_sound(second, 83, True)
        self.window.players[first].set_volume.assert_called_with(17)
        self.window.players[first].set_muted.assert_called_with(False)
        self.window.players[second].set_volume.assert_called_with(83)
        self.window.players[second].set_muted.assert_called_with(True)

    def test_layout_priority_keeps_promoted_rooms_audio(self):
        first, second = self.window.wall.tiles
        second.room['live'] = True
        self.window.players[second] = Mock(spec=TilePlayer)
        self.window._prioritize_live_tiles('1x1')
        self.assertIs(self.window.wall.tiles[0], second)
        self.assert_sound(second, 83, True)
        self.assert_sound(first, 17, False)

    def test_new_room_uses_defaults_instead_of_replaced_rooms_audio(self):
        tile = self.window.wall.tiles[0]
        self.window._on_room_dropped(tile, '1003')
        self.assert_sound(tile, 37, True)

    def test_removed_room_restores_audio_after_readd_and_restart(self):
        tile = self.window.wall.tiles[0]
        tile.set_volume(29)
        tile.set_muted(False)
        self.window._on_room_dropped(tile, '1003')
        self.window._on_room_dropped(tile, '1001')
        self.assert_sound(tile, 29, False)
        self.window._clear_tile_room(tile)
        state = self.window.current_state()
        self.assertEqual(state['room_audio']['1001'], {'volume': 29, 'muted': False})
        restored = self.make_window(state)
        restored._on_room_dropped(restored.wall.tiles[0], '1001')
        self.assert_sound(restored.wall.tiles[0], 29, False)

    def test_legacy_wall_only_audio_survives_moving_rooms(self):
        window = self.make_window({'plugins_enabled': [], 'rooms': ['1001', '1002'],
            'settings': {'auto_update': False}, 'wall': [
                {'room_id': '1001', 'volume': 0, 'muted': False},
                {'room_id': '1002', 'volume': 69, 'muted': True}]})
        window._on_tile_swapped('1001', window.wall.tiles[1])
        self.assert_sound(window.wall.tiles[0], 69, True)
        self.assert_sound(window.wall.tiles[1], 0, False)

    def test_fullscreen_temporary_mute_does_not_replace_saved_room_mute(self):
        tile = self.window.wall.tiles[0]
        self.window._fullscreen_audio_saved[tile] = False
        tile.set_muted(True)
        state = self.window.current_state()
        self.assertEqual(state['room_audio']['1001'], {'volume': 17, 'muted': False})


if __name__ == '__main__':
    unittest.main()
