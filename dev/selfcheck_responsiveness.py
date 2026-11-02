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

    def test_snapshot_has_counts_without_account_or_room_payloads(self):
        window = SimpleNamespace(wall=SimpleNamespace(tiles=[1, 2]), players={1: object()},
            sidebar=SimpleNamespace(_items=[1, 2, 3]), layout_id='2x2',
            _danmaku_clients={'private-room': object()}, _danmaku_retired=[], _super_chat_snapshots={})
        self.probe.pulse(window)
        self.assertEqual(self.probe.state['tiles'], 2)
        self.assertEqual(self.probe.state['danmaku_clients'], 1)
        self.assertNotIn('private-room', json.dumps(self.probe.state))

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
