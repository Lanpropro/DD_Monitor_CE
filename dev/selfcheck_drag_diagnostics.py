"""Offline checks for the temporary Windows drag recorder; no real OLE drag."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@unittest.skipUnless(sys.platform == 'win32', 'Windows COM/OLE diagnostic')
class DragDiagnosticsTests(unittest.TestCase):
    def test_state_changes_drag_receipt_and_return_are_recorded_without_changing_com(self):
        from dev import diagnose_drag_windows as diag
        from dev.selfcheck_main_notices import MainNoticesTests
        from ddm.player import TilePlayer
        from ddm.widgets import ROOM_MIME, NavItem, Sidebar
        from ddm import motion
        from ddm.preview import HoverPreview
        from ddm.sidebar_drag import SidebarDrag
        from ddm import sidebar_drag as drag_module
        from PySide6.QtCore import QMimeData, QPoint, Qt
        from PySide6.QtGui import QDrag, QDragEnterEvent

        MainNoticesTests.setUpClass()
        fixture = MainNoticesTests()
        fixture.setUp()
        try:
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                # Restore every temporary hook so this test cannot affect later checks.
                stack.enter_context(patch.object(drag_module, 'widget_at', drag_module.widget_at))
                for cls, names in ((TilePlayer, ('bind', 'stop', 'release', '_destroy_core')),
                                   (NavItem, ('mousePressEvent', '_drag_pixmap')),
                                   (Sidebar, ('_prepare_drag_snapshot', 'show_drop_indicator',
                                              'finish_drag', 'reorder_items', 'refresh_strip')),
                                   (HoverPreview, ('_stop_now', '_check_hover', '_begin_resolve', '_on_resolved')),
                                   (motion, ('lifted_drag',)),
                                   (SidebarDrag, ('start', 'finish', 'cancel', '_move_ghost', '_tick')),
                                   (diag.MainWindow, ('showEvent', '_on_layout_changed',
                                                     '_stop_tile', '_clear_tile_room', '_on_room_dropped'))):
                    for name in names:
                        stack.enter_context(patch.object(cls, name, getattr(cls, name)))
                drag_exec = stack.enter_context(patch.object(QDrag, 'exec', return_value=Qt.IgnoreAction))
                stack.enter_context(patch.object(diag, 'windows', return_value=[]))
                path = Path(directory) / 'drag.jsonl'
                recorder = diag.Recorder(path)
                recorder.install()
                window = fixture.window([{'room_id': '1'}])
                window.settings['close_behavior'] = 'exit'
                state = [0, 3, 0]
                def apartment(kind, qualifier):
                    kind._obj.value, qualifier._obj.value = state[1:]
                    return state[0]
                try:
                    with patch.object(diag.ole32, 'CoGetApartmentType', side_effect=apartment):
                        recorder.com_timer.timeout.emit()
                        count = len(path.read_text().splitlines())
                        recorder.com_timer.timeout.emit()
                        self.assertEqual(len(path.read_text().splitlines()), count)
                        state[1] = 1
                        recorder.com_timer.timeout.emit()
                        core = Mock()
                        with patch('ddm.player.mpv.MPV', return_value=core):
                            player = TilePlayer(window.wall.tiles[0].video, silent=True)
                            player.bind()
                            core.terminate.side_effect = lambda: state.__setitem__(1, 3)
                            player.release()
                    mime = QMimeData()
                    mime.setData(ROOM_MIME, b'1')
                    enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime,
                                           Qt.LeftButton, Qt.NoModifier)
                    fixture.app.sendEvent(window.wall.tiles[0], enter)
                    drag = QDrag(window.sidebar._items[0])
                    drag.setMimeData(mime)
                    item = window.sidebar._items[0]
                    def delayed_drag(*args, **kwargs):
                        diag.time.sleep(.18)  # Simulate a blocked GUI callback, not user drag duration.
                        fixture.app.processEvents()
                        return Qt.IgnoreAction
                    drag_exec.side_effect = delayed_drag
                    with patch.object(diag.user32, 'GetAsyncKeyState', return_value=0x8000):
                        recorder._gesture = 1
                        recorder._press_at = diag.time.perf_counter()
                        item._drag_pixmap()
                        motion.lifted_drag(item._drag_pixmap(), QPoint(10, 10))
                        self.assertEqual(drag.exec(Qt.CopyAction), Qt.IgnoreAction)
                    drag_exec.assert_called_once()
                    drag_exec.reset_mock()
                    with patch.object(diag.user32, 'GetAsyncKeyState', return_value=0):
                        self.assertEqual(drag.exec(Qt.CopyAction), Qt.IgnoreAction)
                    drag_exec.assert_called_once()
                    from PySide6.QtCore import QPointF, QEvent
                    from PySide6.QtGui import QMouseEvent
                    from PySide6.QtTest import QTest
                    QTest.mousePress(item, Qt.LeftButton, pos=QPoint(5, 5))
                    moving = QMouseEvent(QEvent.MouseMove, QPointF(40,40),
                                        QPointF(item.mapToGlobal(QPoint(40,40))),
                                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
                    fixture.app.sendEvent(item, moving)
                    self.assertTrue(window.sidebar.drag_session.active)
                    fixture.app.sendEvent(item, moving)
                    window.sidebar.drag_session.visual_timer.timeout.emit()
                    window.sidebar.drag_session._tick()
                    window.sidebar.show_drop_indicator('1', 0)
                    window.sidebar.drag_session.cancel()
                    self.assertIsNone(window.sidebar.drag_session._diagnostic_probe)
                    rows = [json.loads(line) for line in path.read_text().splitlines()]
                    phases = [row['phase'] for row in rows]
                    self.assertIn('com:baseline', phases)
                    self.assertIn('com:changed', phases)
                    self.assertIn('drag:before', phases)
                    self.assertIn('drag:after', phases)
                    self.assertIn('internal-drag:start', phases)
                    timing = next(row['timing'] for row in rows if row['phase'] == 'internal-drag:cancel')
                    for stage in ('ghost-callback', 'target-tick', 'preview-layout', 'hit-test'):
                        self.assertGreaterEqual(timing[stage]['calls'], 1)
                        self.assertEqual(set(timing[stage]), {'calls', 'totalMs', 'maxMs', 'maxGapMs'})
                    self.assertIn('internal-drag:cancel', phases)
                    stages = [row for row in rows if row['phase'] == 'drag:stage']
                    self.assertTrue({'pixmap', 'lift'} <= {row['stage'] for row in stages})
                    self.assertTrue(all(row['elapsedMs'] >= 0 for row in stages))
                    entry = next(row for row in rows if row['phase'] == 'drag:exec-enter')
                    self.assertTrue(entry['nativeLeftDown'])
                    self.assertEqual(entry['gesture'], 1)
                    self.assertGreaterEqual(entry['sincePressMs'], 0)
                    self.assertIn('drag:exec-return', phases)
                    self.assertFalse(any(row['phase'] == 'drag:exec-skipped' for row in rows),
                                     'Diagnostics must not suppress the original drag callback')
                    delay = next(row for row in rows if row['phase'] == 'drag:ui-delay')
                    self.assertGreaterEqual(delay['gapMs'], 150)
                    self.assertTrue(all(row['snapshotMs'] >= 0 for row in rows if 'nativeWindows' in row))
                    self.assertTrue(any(row['phase'] == 'drag:event' and
                                        ROOM_MIME in row.get('formats', []) for row in rows))
                    changed = next(row for row in rows if row['phase'] == 'player:_destroy_core:com-changed')
                    self.assertTrue(changed['extra']['pythonStack'])
                finally:
                    recorder.com_timer.stop()
                    fixture.app.removeEventFilter(recorder.filter)
                    window.close()
                    recorder.handler.close()
        finally:
            fixture.doCleanups()

    def test_first_drag_profiles_are_opt_in_bounded_and_keep_returns_and_exceptions(self):
        from dev import diagnose_drag_windows as diag
        with tempfile.TemporaryDirectory() as directory:
            recorder = diag.Recorder(Path(directory) / 'drag.jsonl', profile_first_drag=True)
            private_value = 'PRIVATE_ARGUMENT_MUST_NOT_BE_CAPTURED'
            def snapshot(value):
                return value
            def fail():
                raise ValueError('fixture')
            try:
                self.assertEqual(recorder.profile_once('pixmap', snapshot, private_value), private_value)
                self.assertEqual(recorder.profile_once('pixmap', snapshot, private_value), private_value)
                self.assertEqual(recorder.profile_once('preview-prepare', snapshot, private_value), private_value)
                self.assertEqual(recorder.profile_once('preview-prepare', snapshot, private_value), private_value)
                with self.assertRaisesRegex(ValueError, 'fixture'):
                    recorder.profile_once('drag-start', fail)
                self.assertIsNone(sys.getprofile())
                rows = [json.loads(line) for line in recorder.path.read_text().splitlines()]
                self.assertEqual([row['stage'] for row in rows], ['pixmap', 'preview-prepare', 'drag-start'])
                self.assertTrue(all(len(row['functions']) <= 30 for row in rows))
                self.assertNotIn(private_value, json.dumps(rows))
                recorder.profile_first_drag = False
                with patch.object(diag.cProfile, 'Profile', side_effect=AssertionError('No ordinary profiling')):
                    self.assertEqual(recorder.profile_once('ordinary', snapshot, 42), 42)
            finally:
                recorder.handler.close()

    def test_timing_summary_counts_fast_callbacks_without_per_frame_records(self):
        from dev import diagnose_drag_windows as diag
        probe = diag.DragStallProbe()
        probe.finish()
        with patch.object(diag.time, 'perf_counter', side_effect=[1.003, 1.023]):
            probe.record_timing('ghost-callback', 1.0)
            probe.record_timing('ghost-callback', 1.02)
        self.assertEqual(probe.timing_summary(), {'ghost-callback':
            {'calls': 2, 'totalMs': 6.0, 'maxMs': 3.0, 'maxGapMs': 20.0}})
        with patch.object(diag.time, 'perf_counter', return_value=1.04):
            for _ in range(1000):
                probe.record_timing('ghost-callback', 1.039)
        self.assertEqual(probe.timing_summary()['ghost-callback']['calls'], 1002)
        self.assertEqual(len(probe.timings), 1)
        self.assertLess(len(json.dumps(probe.timing_summary())), 140)

    def test_trace_files_rotate_and_keep_only_three_backups(self):
        from dev.diagnose_drag_windows import Recorder
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'drag.jsonl'
            recorder = Recorder(path)
            try:
                recorder.handler.maxBytes = 512
                for index in range(40):
                    recorder.write({'phase': 'test', 'index': index, 'value': 'x' * 100})
                self.assertEqual(len(list(path.parent.glob('drag.jsonl*'))), 4)
                self.assertLessEqual(path.stat().st_size, 512)
                self.assertEqual(json.loads(path.read_text().splitlines()[-1])['index'], 39)
            finally:
                recorder.handler.close()

    def test_stall_probe_captures_gui_stack_without_qt_calls_or_local_values(self):
        from dev import diagnose_drag_windows as diag
        with patch.object(diag.user32, 'GetAsyncKeyState', return_value=0):
            probe = diag.DragStallProbe()
            try:
                local_value = 'synthetic-private-value'
                diag.time.sleep(.35)
            finally:
                samples = probe.finish()
            self.assertFalse(probe.thread.is_alive())
            self.assertTrue(samples)
            self.assertLessEqual(len(samples), 8)
            self.assertTrue(any(frame['function'].startswith('test_stall_probe')
                                for sample in samples for frame in sample['frames']))
            self.assertNotIn(local_value, json.dumps(samples))
            self.assertTrue(all(set(frame) == {'file', 'function', 'line'}
                                for sample in samples for frame in sample['frames']))

    def test_probe_distinguishes_normal_drag_from_delayed_return_after_release(self):
        from dev import diagnose_drag_windows as diag
        for down in (True, False):
            with self.subTest(down=down), patch.object(diag.user32, 'GetAsyncKeyState',
                                                      return_value=0x8000 if down else 0):
                probe = diag.DragStallProbe()
                try:
                    for _ in range(8):
                        probe.pulse()
                        diag.time.sleep(.04)
                finally:
                    samples = probe.finish()
                self.assertFalse(probe.thread.is_alive())
                if down:
                    self.assertFalse(samples, 'Normal held-button drag is not a stall')
                else:
                    self.assertTrue(any(row['reason'] == 'left-released' for row in samples))


if __name__ == '__main__':
    unittest.main()
