"""Isolated collector checks; never substitute for real startup/scroll evidence."""
from contextlib import ExitStack
import itertools
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from ddm.responsiveness import Probe
from ddm.startup_scroll_diagnostics import ScrollCapture, install


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
            for owner, names in ((TilePlayer, ('bind', '_destroy_core')),
                    (VideoSurface, ('_clip_native_video',)),
                    (HoverPreview, ('_begin_resolve', '_on_resolved', '_update_popup_position')),
                    (Sidebar, ('_prepare_drag_snapshot', '_refresh_visible_covers', '_sync_pointer_hover')),
                    (MainWindow, ('__init__', 'start_all', '_play_on')), (QWidget, ('winId',))):
                for name in names:
                    stack.enter_context(patch.object(owner, name, getattr(owner, name)))
            stack.enter_context(patch.object(mpv, 'MPV', Core))
            stack.enter_context(patch('cProfile.Profile', side_effect=AssertionError('No cross-thread profiling')))
            install(self.probe)
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
        from ddm.app import MainWindow
        from ddm.player import TilePlayer, mpv
        from ddm.preview import HoverPreview
        from ddm.video_surface import VideoSurface
        from ddm.widgets import Sidebar

        with ExitStack() as stack:
            for owner, names in ((TilePlayer, ('bind', '_destroy_core')),
                    (VideoSurface, ('_clip_native_video',)),
                    (HoverPreview, ('_begin_resolve', '_on_resolved', '_update_popup_position')),
                    (Sidebar, ('_prepare_drag_snapshot', '_refresh_visible_covers', '_sync_pointer_hover')),
                    (MainWindow, ('__init__', 'start_all', '_start_startup_tiles', 'start_tile', '_play_on')),
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
