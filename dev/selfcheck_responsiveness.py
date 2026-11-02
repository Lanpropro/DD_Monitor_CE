"""Probe mechanics with fake time and local files; not evidence of real UI performance."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import responsiveness as diag


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'capture.jsonl'
        self.probe = diag.Probe(self.path)
        self.addCleanup(self.probe.stop)

    def records(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_return_exception_and_nested_calls_are_preserved(self):
        token = object()
        inner = self.probe.timed(lambda value: value, 'inner')
        outer = self.probe.timed(inner, 'outer')
        self.assertIs(outer(token), token)
        def fail():
            raise ValueError('fixture')
        wrapped = self.probe.timed(fail, 'fail')
        with self.assertRaisesRegex(ValueError, 'fixture'):
            wrapped()
        self.assertEqual(self.probe.active, [])
        self.assertEqual({key: item['count'] for key, item in self.probe.calls.items()},
                         {'inner': 1, 'outer': 1, 'fail': 1})

    def test_stall_rate_limit_and_periodic_summary(self):
        self.probe.last_tick = 100
        self.probe.timed(lambda: None, 'fixture')()
        with patch.object(diag, 'process_counters', return_value={'cpu_seconds': 2}):
            report, stack = self.probe.sample(100.1, 100, 0)
            self.assertFalse(self.records())
            report, stack = self.probe.sample(100.3, report, stack)
            report, stack = self.probe.sample(100.5, report, stack)
            self.assertEqual(len(self.records()), 1)
            self.probe.last_tick = 110
            self.probe.sample(110, report, stack)
        records = self.records()
        self.assertEqual([row['phase'] for row in records], ['ui-stall', 'sample'])
        self.assertEqual(records[1]['calls']['fixture']['count'], 1)
        self.assertEqual(self.probe.calls, {})
        for frame in records[0]['stack']:
            self.assertEqual(set(frame), {'file', 'function', 'line'})
            self.assertFalse(Path(frame['file']).is_absolute())

    def test_sidebar_profile_records_nested_costs_and_preserves_exceptions(self):
        token = object()
        def inner(value):
            return value
        def outer(value):
            for _ in range(5):
                inner(value)
            return value
        wrapped = self.probe.timed(outer, 'sidebar', profile_sidebar=True)
        self.assertIs(wrapped(token), token)
        rows = [r for r in self.records() if r['phase'] == 'sidebar-profile']
        self.assertEqual(len(rows), 1)
        functions = rows[0]['functions']
        self.assertLessEqual(len(functions), 30)
        nested = next(row for row in functions if row['function'] == 'inner')
        self.assertEqual(nested['calls'], 5)
        self.assertGreaterEqual(nested['total_ms'], nested['self_ms'])
        self.assertTrue(all(not Path(row['file']).is_absolute() for row in functions))
        self.assertNotIn(str(token), json.dumps(rows))
        def fail():
            raise ValueError('private fixture')
        with self.assertRaisesRegex(ValueError, 'private fixture'):
            self.probe.timed(fail, 'sidebar', profile_sidebar=True)()
        self.assertEqual(self.probe.active, [])
        self.assertIsNone(sys.getprofile())
        self.assertEqual(len([r for r in self.records() if r['phase'] == 'sidebar-profile']), 2)
        self.assertNotIn('private fixture', self.path.read_text(encoding='utf-8'))
        self.probe.stop()
        self.assertIs(wrapped(token), token)
        self.assertEqual(len([r for r in self.records() if r['phase'] == 'sidebar-profile']), 2)

    def test_snapshot_has_counts_without_account_or_room_payloads(self):
        window = SimpleNamespace(wall=SimpleNamespace(tiles=[1, 2]), players={1: object()},
            sidebar=SimpleNamespace(_items=[1, 2, 3]), layout_id='2x2',
            _danmaku_clients={'private-room': object()}, _danmaku_retired=[], _super_chat_snapshots={})
        self.probe.pulse(window)
        self.assertEqual(self.probe.state['tiles'], 2)
        self.assertEqual(self.probe.state['danmaku_clients'], 1)
        self.assertNotIn('private-room', json.dumps(self.probe.state))

    @patch('ddm.motion.enabled', lambda: True)
    def test_folder_capture_records_bounded_positions_and_layout_interruptions(self):
        from PySide6.QtWidgets import QApplication
        from ddm.widgets import Sidebar
        app = QApplication.instance() or QApplication([])
        sidebar = Sidebar([{'room_id': 'private-room', 'uname': 'private-name'}], auto_compact=False)
        self.addCleanup(sidebar.deleteLater)
        sidebar.set_folders([{'id': 'private-folder', 'name': 'private-title', 'type': 'normal',
                             'rooms': ['private-room'], 'collapsed': True}])
        sidebar.resize(248, 700)
        sidebar.show()
        app.processEvents()
        capture = diag.FolderMotionCapture(self.probe, sidebar)
        self.addCleanup(capture.finish)
        sidebar.toggle_folder('private-folder', animate=True)
        self.assertFalse(sidebar.get_folder('private-folder')['collapsed'])
        self.assertGreater(capture.running_animations(), 0)
        capture.frame()
        active_rows = capture.record['frames'][-1]['rows']
        self.assertTrue(any(row['animation_ms'] is not None for row in active_rows))
        for item in active_rows:
            entry = capture.entries[item['row']]
            self.assertEqual(item['stack'], sidebar.list_box.children().index(entry))
            animation = sidebar.list_box._animations.get(entry)
            target = animation.endValue() if animation is not None else entry.pos()
            self.assertEqual(item['target'], [target.x(), target.y()])
        sidebar.list_box.relayout(animate=False)
        for _ in range(45):
            capture.frame()
        row = next(r for r in self.records() if r['phase'] == 'folder-motion')
        self.assertEqual(row['reason'], 'complete')
        self.assertTrue(row['opening'] and row['animate_requested'])
        self.assertLessEqual(len(row['frames']), 40)
        self.assertTrue(any(layout['running_before'] and not layout['animate'] for layout in row['layouts']))
        self.assertTrue(all(len(frame['rows']) <= 16 for frame in row['frames']))
        self.assertFalse(capture.timer.isActive())
        self.assertNotIn('private-', json.dumps(row))
        sidebar.toggle_folder('private-folder', animate=True)
        sidebar.toggle_folder('private-folder', animate=True)
        self.assertEqual(self.records()[-1]['reason'], 'superseded')
        capture.finish()
        with patch.object(capture, 'toggle', side_effect=ValueError('private-error')):
            with self.assertRaises(ValueError):
                sidebar.toggle_folder('private-folder')
        self.assertEqual(self.records()[-1]['reason'], 'error')
        self.assertIsNone(capture.record)
        self.assertFalse(capture.timer.isActive())
        self.assertNotIn('private-error', json.dumps(self.records()))
        from PySide6.QtCore import QEvent, QPropertyAnimation, QPoint
        from PySide6.QtWidgets import QWidget
        target = QWidget(sidebar.list_box)
        animation = QPropertyAnimation(target, b'pos', target)
        animation.setEndValue(QPoint(0, 30))
        sidebar.list_box._animations[target] = animation
        target.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertIsInstance(capture.running_animations(), int)
        sidebar.close()

    def test_thread_stop_is_idempotent_and_wrappers_stop_recording(self):
        self.probe.start()
        self.assertTrue(self.probe.thread.is_alive())
        self.probe.stop()
        self.probe.stop()
        self.assertFalse(self.probe.thread.is_alive())
        self.assertEqual(self.probe.timed(lambda: 42, 'after-stop')(), 42)
        self.assertNotIn('after-stop', self.probe.calls)
        self.assertEqual([row['phase'] for row in self.records()], ['start', 'stop'])

    def test_log_rotation_is_bounded(self):
        self.probe.handler.maxBytes = 300
        for index in range(30):
            self.probe.write('fixture', index=index)
        self.assertLessEqual(len(list(Path(self.directory.name).iterdir())), 3)
        self.assertEqual(self.records()[-1]['index'], 29)

    def test_install_records_start_before_constructor_and_wraps_connected_slots(self):
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QApplication
        from ddm import app as app_module, preview, widgets

        app = QApplication.instance() or QApplication([])

        class Window(QObject):
            changed = Signal(str)

            def __init__(self):
                super().__init__()
                self.wall = SimpleNamespace(tiles=[])
                self.players = {}
                self.sidebar = SimpleNamespace(_items=[])
                self._danmaku_clients, self._super_chat_snapshots = {}, {}
                self._danmaku_retired = []
                self.changed.connect(self._on_layout_changed)
                self._on_layout_changed('initial')

            def _on_layout_changed(self, value):
                self.layout_id = value

            def sync_danmaku(self):
                pass

            def _on_status_updated(self):
                pass

        class Component:
            def method(self):
                pass

        for name in ('set_collapsed', 'set_card_mode', 'refresh_strip', 'reorder_items',
                     'relayout', '_check_hover', '_stop_now'):
            setattr(Component, name, Component.method)
        path = Path(self.directory.name) / 'installed.jsonl'
        with patch.object(app_module, 'MainWindow', Window), \
                patch.object(widgets, 'Sidebar', Component), patch.object(widgets, 'WallGrid', Component), \
                patch.object(preview, 'HoverPreview', Component), \
                patch.object(diag, 'FolderMotionCapture'), \
                patch.object(diag.time, 'perf_counter', side_effect=[0, .02, .03, .05]):
            diag.install(path)
            window = Window()
            probe = window._responsiveness_probe
            try:
                window.changed.emit('2x2')
                self.assertEqual(window.layout_id, '2x2')
                key = next(key for key in probe.calls if key.endswith('._on_layout_changed'))
                self.assertEqual(probe.calls[key]['count'], 2)
                records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
                self.assertEqual(records[0]['phase'], 'start')
                self.assertIn('window-ready', [row['phase'] for row in records])
            finally:
                probe.stop()
                window.deleteLater()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
