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
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
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

    def _sync_danmaku_controls(self):
        return None


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
        self.wall._sync_danmaku_controls()
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
        self.addCleanup(self.capture.finish_idle)

    def rows(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_explicit_capture_records_only_fullscreen_shortcut_edges(self):
        self.window.shortcuts = {'focus': 'F', 'restore': 'Esc'}
        self.window.winId()
        receiver = self.window.windowHandle()
        with patch.object(diag, '_key_queue_ms', return_value=160):
            for enabled, key, repeat, event_type in (
                    (False, Qt.Key_F, False, QEvent.ShortcutOverride),
                    (True, Qt.Key_A, False, QEvent.ShortcutOverride),
                    (True, Qt.Key_F, True, QEvent.ShortcutOverride),
                    (True, Qt.Key_F, False, QEvent.ShortcutOverride),
                    (True, Qt.Key_F, False, QEvent.KeyRelease),
                    (True, Qt.Key_Escape, False, QEvent.ShortcutOverride)):
                self.capture.native_windows = enabled
                event = QKeyEvent(event_type, key, Qt.NoModifier, 'private-text', repeat)
                event.setTimestamp(1234)
                self.assertFalse(self.capture.eventFilter(receiver, event))
        rows = self.rows()
        self.assertEqual([(row['action'], row['edge']) for row in rows],
                         [('focus', 'press'), ('focus', 'release'), ('restore', 'press')])
        self.assertTrue(all(row['phase'] == 'fullscreen-key' and row['queue_ms'] == 160 for row in rows))
        self.assertNotIn('private-text', self.path.read_text(encoding='utf-8'))

    def test_bar_and_sidebar_first_paint_are_part_of_handoff_evidence(self):
        tile = self.window.wall.tiles[0]
        tile.bottom = QWidget(self.window)
        tile.bottom.resize(300, 36)
        sidebar = self.window.sidebar = QWidget(self.window)
        sidebar.scroll = QScrollArea(sidebar)
        self.capture.begin('enter', tile)
        for widget in (tile.bottom, sidebar, sidebar.scroll.viewport()):
            self.capture.eventFilter(widget, diag.QEvent(diag.QEvent.Paint))
        self.capture.finish()
        events = self.rows()[-1]['geometry']
        self.assertEqual({e['role'] for e in events if e['event'] == 'Paint'}, {'bar', 'sidebar', 'sidebar-cards'})
        self.assertNotIn('private-', self.path.read_text(encoding='utf-8'))

    def test_explicit_capture_records_known_bars_and_visible_native_windows(self):
        tile = self.window.wall.tiles[0]
        tile.bottom = QWidget(self.window)
        self.capture.native_windows = True
        snapshot = {'available': True, 'truncated': False, 'cursor': [100, 200], 'windows': [
            dict(hwnd='0x123', parent='0x0', cls='Qt', rect=[1, 2, 3, 4], visible=False),
            dict(hwnd='0x456', parent='0x0', cls='Qt', rect=[10, 20, 30, 40], visible=True),
            dict(hwnd='0x789', parent='0x0', cls='Qt', visible=False),
        ]}
        with patch('ddm.on_demand_diagnostics.native_snapshot', return_value=snapshot), \
                patch.object(tile.bottom, 'internalWinId', return_value=0x123):
            self.capture.begin('enter', tile)
            self.capture.capture_native_windows(self.capture.record, 'returned')
            self.capture.finish('interrupted')
        entries = self.rows()[-1]['native_windows']
        self.assertEqual([entry['stage'] for entry in entries], ['before', 'returned', 'interrupted'])
        self.assertEqual(entries[-1]['bars'], {'0x123': 0})
        self.assertEqual([row['hwnd'] for row in entries[-1]['windows']], ['0x123', '0x456'])
        self.assertNotIn('cursor', entries[-1])

    def test_idle_capture_records_animation_without_content_and_stops(self):
        from ddm.widgets import Tile as RuntimeTile
        from ddm.fullscreen_cursor import FullscreenCursor
        tile = RuntimeTile({'room_id': 'private-room', 'uname': 'private-name'}, self.window)
        self.window.settings = {'fullscreen_auto_hide_controls': True}
        self.window._fullscreen_cursor = FullscreenCursor(self.window)
        self.window._fullscreen_tile = tile
        self.capture.start_idle(tile)
        self.assertTrue(self.capture.idle_timer.isActive())
        with patch.object(diag.time, 'monotonic', return_value=self.capture.idle_started+8.1):
            self.capture.idle_frame()
        self.assertFalse(self.capture.idle_timer.isActive())
        row = self.rows()[-1]
        self.assertEqual(row['phase'], 'fullscreen-idle')
        self.assertEqual(len(row['samples']), 2)
        self.assertIn('bar_progress', row['samples'][0])
        self.assertTrue(row['samples'][0]['hide_bar'])
        self.assertFalse(self.capture.idle_samples)
        self.assertNotIn('private-', self.path.read_text(encoding='utf-8'))
        self.capture.start_idle(tile)
        self.capture.begin('exit', self.window.wall.tiles[0])
        self.assertFalse(self.capture.idle_timer.isActive())
        self.assertEqual(self.rows()[-1]['reason'], 'transition')

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
        from ddm import app, fullscreen_bar, fullscreen_presentation, tile_widgets, wall_widgets, window_fullscreen, video_danmaku
        for detailed in (False, True):
            captured_wall = type('CapturedWall', (Wall,), {})
            captured_window = type('CapturedWindow', (Window,), {'wall_type': captured_wall})
            captured_video = type('CapturedVideo', (video_danmaku.VideoDanmaku,), {})
            captured_bar = type('CapturedBar', (fullscreen_bar.FullscreenBar,), {})
            captured_presentation = type('CapturedPresentation', (fullscreen_presentation.FullscreenPresentation,), {})
            captured_tile = type('CapturedTile', (tile_widgets.Tile,), {})
            with patch.object(app, 'MainWindow', captured_window), patch.object(wall_widgets, 'WallGrid', captured_wall), \
                    patch.object(video_danmaku, 'VideoDanmaku', captured_video), \
                    patch.object(fullscreen_bar, 'FullscreenBar', captured_bar), \
                    patch.object(fullscreen_presentation, 'FullscreenPresentation', captured_presentation), \
                    patch.object(tile_widgets, 'Tile', captured_tile), \
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
                    self.assertEqual(row['stages']['CapturedWall._sync_danmaku_controls']['calls'], 1)
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
                    APP.aboutToQuit.disconnect(capture.finish_idle)
                    APP.aboutToQuit.disconnect(probe.stop)
                    probe.stop()
                    window.close()
        self.assertNotIn('private-', self.path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
