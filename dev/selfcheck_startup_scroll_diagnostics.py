"""Isolated collector checks; never substitute for real startup/scroll evidence."""
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from ddm.responsiveness import Probe
from ddm.startup_scroll_diagnostics import ScrollCapture, StartupEvents, install


class StartupScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / 'responsiveness.jsonl'
        self.probe = Probe(self.path)
        self.addCleanup(self.probe.stop)

    def records(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_qt_dispatch_preserves_results_errors_and_only_counts_outer_delivery(self):
        capture = StartupEvents(self.probe)
        receiver = QWidget()
        capture.start(receiver)
        event = QEvent(QEvent.User)
        token = object()
        def nested(widget, delivered):
            self.assertIs(widget, receiver)
            self.assertIs(delivered, event)
            return capture.dispatch(lambda *_: token, widget, delivered)
        try:
            with patch('ddm.startup_scroll_diagnostics.time.perf_counter', side_effect=[0, .02]):
                self.assertIs(capture.dispatch(nested, receiver, event), token)
            with patch('ddm.startup_scroll_diagnostics.time.perf_counter', side_effect=[0, .03]):
                with self.assertRaisesRegex(ValueError, 'fixture'):
                    capture.dispatch(lambda *_: (_ for _ in ()).throw(ValueError('fixture')), receiver, event)
            self.assertEqual(self.probe.active, [])
            capture.finish()
            rows = self.records()
            self.assertEqual([r['phase'] for r in rows],
                ['startup-qt-event', 'startup-qt-event', 'startup-qt-summary'])
            record = rows[-1]['events'][0]
            self.assertEqual(record['count'], 2)
            self.assertAlmostEqual(record['total_ms'], 50)
            self.assertEqual(record['receiver_class'], 'QWidget')
            self.assertEqual(record['event_type'], 'User')
            self.assertIs(capture.dispatch(lambda *_: token, receiver, event), token)
            self.assertEqual(len(self.records()), 3, 'Capture must stop after the bounded startup period')
        finally:
            receiver.deleteLater()

    def test_installed_application_receives_real_qt_dispatch_in_fresh_process(self):
        code = '''
import json, tempfile
from pathlib import Path
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QWidget
from ddm import app as host
from ddm.responsiveness import Probe
from ddm.startup_scroll_diagnostics import install
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'events.jsonl'
    probe = Probe(path)
    install(probe)
    app = host.QApplication([])
    widget = QWidget()
    capture = app._startup_event_capture
    capture.start(widget)
    app.sendEvent(widget, QEvent(QEvent.User))
    capture.finish()
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert any(item['event_type'] == 'User' for item in rows[-1]['events']), rows
    probe.stop()
    widget.deleteLater()
    app.shutdown()
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_wheel_dispatch_is_preserved_and_written_once_per_scroll(self):
        sidebar = QWidget()
        sidebar.scroll = QScrollArea(sidebar)
        sidebar.scroll.setGeometry(0, 0, 240, 200)
        sidebar.drag_session = SimpleNamespace(active=False)
        content = QWidget()
        content.resize(200, 2000)
        sidebar.scroll.setWidget(content)
        capture = ScrollCapture(sidebar, self.probe)
        try:
            sidebar.show()
            self.app.processEvents()
            viewport = sidebar.scroll.viewport()
            bar = sidebar.scroll.verticalScrollBar()
            before = bar.value()
            for _ in range(2):
                point = viewport.rect().center()
                wheel = QWheelEvent(QPointF(point), QPointF(viewport.mapToGlobal(point)),
                    QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                QApplication.sendEvent(viewport, wheel)
            self.assertGreater(bar.value(), before)
            self.assertEqual([r['phase'] for r in self.records()], ['sidebar-scroll-start'])
            capture.finish()
            end = self.records()[-1]
            self.assertEqual(end['phase'], 'sidebar-scroll-end')
            self.assertEqual(end['changes'], 2)
            self.assertEqual(end['wheel_events'], 2)
            self.assertEqual(end['last_value'], bar.value())
            self.assertFalse(end['dragging'])
            capture.finish()
            self.assertEqual(len(self.records()), 2)
            self.probe.stop()
            capture.changed('vertical', 10)
            capture.finish()
            self.assertEqual(len(self.records()), 3)  # Only the collector's stop record.
        finally:
            sidebar.close()

    def test_player_native_and_core_phases_keep_results_errors_and_thread_scope(self):
        from ddm import app as app_module
        from ddm.app import MainWindow
        from ddm.player import TilePlayer, mpv
        from ddm.preview import HoverPreview
        from ddm.video_surface import VideoSurface
        from ddm.widgets import Sidebar

        class Core:
            fail = False
            def __init__(self, **kwargs):
                if self.fail:
                    raise RuntimeError('fixture')
                self.options = kwargs

        with ExitStack() as stack:
            stack.enter_context(patch.object(app_module, 'QApplication', app_module.QApplication))
            for owner, names in ((TilePlayer, ('bind', '_destroy_core')),
                    (VideoSurface, ('_clip_native_video',)),
                    (HoverPreview, ('_begin_resolve', '_on_resolved', '_update_popup_position')),
                    (Sidebar, ('_prepare_drag_snapshot', '_refresh_visible_covers', '_sync_pointer_hover')),
                    (MainWindow, ('__init__', 'start_all', '_start_startup_tiles', 'start_tile', '_play_on',
                                  'load_room_avatars', '_on_player_state')),
                    (QWidget, ('winId',))):
                for name in names:
                    stack.enter_context(patch.object(owner, name, getattr(owner, name)))
            stack.enter_context(patch.object(mpv, 'MPV', Core))
            stack.enter_context(patch('cProfile.Profile', side_effect=AssertionError('No cross-thread profiling')))
            states = []
            token = object()
            def receive_state(window, tile, state):
                states.append(state)
                return token
            stack.enter_context(patch.object(MainWindow, '_on_player_state', receive_state))
            install(self.probe)
            tile = object()
            window = SimpleNamespace(wall=SimpleNamespace(tiles=[tile]))
            for state in ('connecting', 'buffering', 'playing', 'error'):
                self.assertIs(MainWindow._on_player_state(window, tile, state), token)
            self.assertIs(MainWindow._on_player_state(window, None, 'stopped'), token)
            state_rows = [r for r in self.records() if r['phase'] == 'startup-player-state']
            self.assertEqual([r['state'] for r in state_rows], states[:4])
            self.assertTrue(all(r['tile_index'] == 0 for r in state_rows))
            self.assertTrue(all(set(r) == {'time', 'session', 'elapsed_s', 'phase', 'tile_index', 'state'}
                                for r in state_rows), 'Playback capture must not record room IDs or stream URLs')
            video = QWidget()
            player = TilePlayer(video)
            clock = itertools.count(0, .02)
            with patch('ddm.responsiveness.time.perf_counter', side_effect=lambda: next(clock)):
                player.bind()
                self.assertIsInstance(player.player, Core)
                self.assertEqual(player.player.options['wid'], str(int(video.winId())))
                self.assertEqual(self.probe.active, [])
                player.player = None
                Core.fail = True
                with self.assertRaisesRegex(RuntimeError, 'fixture'):
                    player.bind()
                self.assertEqual(self.probe.active, [])
                Core.fail = False
                self.probe.active.append('player.bind')
                count = len(self.records())
                worker = threading.Thread(target=Core)
                worker.start()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(self.records()), count, 'Background constructors must not be GUI timings')
                self.assertEqual(self.probe.active.pop(), 'player.bind')
            labels = {r['function'] for r in self.records() if r['phase'] == 'slow-call'}
            self.assertTrue({'player.bind', 'player.native-window', 'player.core-init'} <= labels)
            self.assertNotIn('options', json.dumps(self.records()))
            video.close()

    def test_installed_capture_preserves_qt_zero_argument_slots_during_scrolling(self):
        from ddm import app as app_module
        from ddm.app import MainWindow
        from ddm.player import TilePlayer, mpv
        from ddm.preview import HoverPreview
        from ddm.video_surface import VideoSurface
        from ddm.widgets import Sidebar

        with ExitStack() as stack:
            stack.enter_context(patch.object(app_module, 'QApplication', app_module.QApplication))
            for owner, names in ((TilePlayer, ('bind', '_destroy_core')),
                    (VideoSurface, ('_clip_native_video',)),
                    (HoverPreview, ('_begin_resolve', '_on_resolved', '_update_popup_position')),
                    (Sidebar, ('_prepare_drag_snapshot', '_refresh_visible_covers', '_sync_pointer_hover')),
                    (MainWindow, ('__init__', 'start_all', '_start_startup_tiles', 'start_tile', '_play_on',
                                  'load_room_avatars', '_on_player_state')),
                    (QWidget, ('winId',)), (mpv.MPV, ('__init__',))):
                for name in names:
                    if hasattr(owner, name):
                        stack.enter_context(patch.object(owner, name, getattr(owner, name)))
            errors = []
            stack.enter_context(patch.object(sys, 'excepthook', side_effect=lambda *args: errors.append(args[1])))
            install(self.probe)
            window = QWidget()
            window.setGeometry(-10000, -10000, 500, 600)
            sidebar = Sidebar([dict(room_id=str(i), uname=f'Fixture {i}') for i in range(24)], window)
            sidebar.setGeometry(0, 0, 248, 550)
            preview = HoverPreview(sidebar, window)
            try:
                window.show()
                self.app.processEvents()
                viewport = sidebar.scroll.viewport()
                point = viewport.rect().center()
                for _ in range(3):
                    wheel = QWheelEvent(QPointF(point), QPointF(viewport.mapToGlobal(point)),
                        QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                    QApplication.sendEvent(viewport, wheel)
                self.app.processEvents()
                self.assertGreater(sidebar.scroll.verticalScrollBar().value(), 0)
                self.assertEqual(errors, [], 'Timed slots must retain Qt signal argument truncation')
                self.assertGreater(self.probe.calls['Sidebar._sync_pointer_hover']['count'], 0)
                self.assertGreater(self.probe.calls['HoverPreview._update_popup_position']['count'], 0)
            finally:
                preview.stop()
                window.close()
                window.deleteLater()
                self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
