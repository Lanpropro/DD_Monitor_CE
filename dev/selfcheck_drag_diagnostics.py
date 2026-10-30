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
        from ddm.widgets import ROOM_MIME
        from PySide6.QtCore import QMimeData, QPoint, Qt
        from PySide6.QtGui import QDrag, QDragEnterEvent

        MainNoticesTests.setUpClass()
        fixture = MainNoticesTests()
        fixture.setUp()
        try:
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                # Restore every temporary hook so this test cannot affect later checks.
                for cls, names in ((TilePlayer, ('bind', 'stop', 'release', '_destroy_core')),
                                   (diag.MainWindow, ('showEvent', '_on_layout_changed',
                                                     '_stop_tile', '_clear_tile_room'))):
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
                    self.assertEqual(drag.exec(Qt.CopyAction), Qt.IgnoreAction)
                    drag_exec.assert_called_once()
                    rows = [json.loads(line) for line in path.read_text().splitlines()]
                    phases = [row['phase'] for row in rows]
                    self.assertIn('com:baseline', phases)
                    self.assertIn('com:changed', phases)
                    self.assertIn('drag:before', phases)
                    self.assertIn('drag:after', phases)
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


if __name__ == '__main__':
    unittest.main()
