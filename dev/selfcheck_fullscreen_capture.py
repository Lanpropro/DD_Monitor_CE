"""Offline capture mechanics, not evidence of fullscreen playback performance."""
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget
from ddm import fullscreen_diagnostics as diag

APP = QApplication.instance() or QApplication([])
TOKEN = object()


class Core:
    def __init__(self):
        self.handlers = defaultdict(list)

    def observe_property(self, name, handler):
        self.handlers[name].append(handler)
        handler(name, None)

    def unobserve_property(self, name, handler):
        self.handlers[name].remove(handler)

    def emit(self, name, value):
        for handler in tuple(self.handlers[name]):
            handler(name, value)


class Tile:
    room = {'room_id': 'private-room', 'uname': 'private-name'}


class Wall(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.tiles = [Tile(), Tile(), Tile()]
        self._pending_reveal = []

    def set_fullscreen_tile(self, tile):
        return TOKEN

    relayout = reveal_tiles_staggered = set_fullscreen_tile


class Window(QWidget):
    wall_type = Wall

    def __init__(self):
        super().__init__()
        self.wall = self.wall_type(self)
        self.players = {tile: SimpleNamespace(player=Core(), play_session='private-session',
            url='private-url', _released=False) for tile in self.wall.tiles}
        self._fullscreen_tile = None
        self._resize_idle_timer = QTimer(self)
        self.fail = False

    def _on_fullscreen(self, tile):
        if self._fullscreen_tile is tile:
            return self._exit_fullscreen()
        self._fullscreen_tile = tile
        self.wall.set_fullscreen_tile(tile)
        if self.fail:
            raise ValueError('private-error')
        return TOKEN

    def _exit_fullscreen(self):
        self._fullscreen_tile = None
        return self.wall.set_fullscreen_tile(None)

    def noop(self, *args):
        return None

    sync_danmaku = noop
    refresh_theme = _refresh_meta = _upgrade_fullscreen_quality = noop


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name)/'capture.jsonl'
        self.probe = diag.Probe(self.path)
        self.window = Window()
        self.capture = diag.FullscreenCapture(self.probe, self.window)
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.probe.stop)
        self.addCleanup(self.window.close)
        self.addCleanup(self.capture.finish)

    def rows(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_bounds_privacy_async_callbacks_and_cleanup(self):
        capture = self.capture
        capture.begin('enter', self.window.wall.tiles[0])
        core = self.window.players[self.window.wall.tiles[0]].player
        late = core.handlers['time-pos'][0]
        def updates():
            for index in range(1000):
                with patch.object(diag.time, 'perf_counter', return_value=capture.started+index*.05):
                    core.emit('time-pos', index*.05)
                    core.emit('audio-pts', index*.05+.01)
        worker = threading.Thread(target=updates)
        worker.start()
        worker.join()
        with patch.object(diag.time, 'perf_counter', return_value=capture.started+.1):
            for _ in range(1000):
                capture.frame()
                capture.stage('WallGrid.relayout', capture.started)
                capture.eventFilter(self.window.wall, diag.QEvent(diag.QEvent.Resize))
        capture.finish()
        row = self.rows()[-1]
        self.assertEqual(len(row['frames']), 80)
        self.assertEqual(len(row['players']), 2)
        self.assertEqual(len(row['players'][0]['samples']), 120)
        self.assertEqual(len(row['events']), 64)
        self.assertEqual(len(row['geometry']), 96)
        self.assertEqual({entry['role'] for entry in row['geometry']}, {'wall'})
        self.assertTrue(all(len(entry['rect']) == 4 for entry in row['geometry']))
        self.assertFalse(capture.geometry_widgets)
        self.assertEqual(row['stages']['WallGrid.relayout']['calls'], 1000)
        self.assertTrue(all(not handlers for player in self.window.players.values() for handlers in player.player.handlers.values()))
        late('time-pos', 9000)
        self.assertEqual(len(self.rows()), 1)
        self.assertNotIn('private-', self.path.read_text(encoding='utf-8'))

    def test_settle_limit_and_changed_core_are_explicit(self):
        capture = self.capture
        capture.begin('exit', self.window.wall.tiles[0])
        player = self.window.players[self.window.wall.tiles[0]]
        player.player = Core()
        player.play_session = 'new-private-session'
        capture.returned = capture.started
        with patch.object(diag.time, 'perf_counter', return_value=capture.started+.6):
            capture.frame()
        row = self.rows()[-1]
        self.assertEqual(row['reason'], 'settled')
        self.assertTrue(row['players'][0]['core_changed'] and row['players'][0]['session_changed'])
        capture.begin('enter', self.window.wall.tiles[0])
        with patch.object(diag.time, 'perf_counter', return_value=capture.started+9):
            capture.frame()
        self.assertEqual(self.rows()[-1]['reason'], 'limit')

    def test_install_preserves_return_errors_and_nested_exit(self):
        from ddm import app, widgets, window_fullscreen, video_danmaku
        for detailed in (False, True):
            captured_wall = type('CapturedWall', (Wall,), {})
            captured_window = type('CapturedWindow', (Window,), {'wall_type': captured_wall})
            captured_video = type('CapturedVideo', (video_danmaku.VideoDanmaku,), {})
            with patch.object(app, 'MainWindow', captured_window), patch.object(widgets, 'WallGrid', captured_wall), \
                    patch.object(video_danmaku, 'VideoDanmaku', captured_video), \
                    patch.object(window_fullscreen, 'enter'), patch.object(window_fullscreen, 'exit'):
                probe = diag.install(self.path, profile_calls=detailed)
                window = captured_window()
                capture = window._fullscreen_probe
                try:
                    before = len([r for r in self.rows() if r['phase'] == 'fullscreen'])
                    tile = window.wall.tiles[0]
                    self.assertIs(window._on_fullscreen(tile), TOKEN)
                    capture.finish()
                    row = self.rows()[-1]
                    self.assertEqual(row['action'], 'enter')
                    self.assertEqual(bool(row['functions']), detailed)
                    self.assertIs(window._on_fullscreen(tile), TOKEN)
                    capture.finish()
                    self.assertEqual(self.rows()[-1]['action'], 'exit')
                    self.assertEqual(len([r for r in self.rows() if r['phase'] == 'fullscreen']), before+2)
                    window.fail = True
                    with self.assertRaisesRegex(ValueError, 'private-error'):
                        window._on_fullscreen(tile)
                    self.assertIsNone(capture.record)
                    self.assertEqual(self.rows()[-1]['reason'], 'exception')
                    self.assertEqual(capture.depth, 0)
                finally:
                    capture.finish()
                    APP.aboutToQuit.disconnect(capture.finish)
                    APP.aboutToQuit.disconnect(probe.stop)
                    probe.stop()
                    window.close()
        self.assertNotIn('private-', self.path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
