"""Numeric motion capture must not touch render-thread nodes or message data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from ddm.danmaku_float_window import DanmakuFloatWindow
from ddm.video_danmaku_quick import QuickDanmakuLayer
from dev.diagnose_danmaku_motion import MotionTrace


class MotionDiagnosticsTests(unittest.TestCase):
    def test_float_group_emits_one_summary_per_drag(self):
        emit = Mock()
        trace = MotionTrace('unused.jsonl', emit=emit)
        floating = Mock(_move_followers={object(): QPoint()}, property=Mock(return_value=True))
        with patch.object(QuickDanmakuLayer, '__init__'), patch.object(QuickDanmakuLayer, 'move'), \
                patch.object(DanmakuFloatWindow, '_move_group') as move, \
                patch.object(DanmakuFloatWindow, '_finish_move') as finish:
            trace.install()
            DanmakuFloatWindow._move_group(floating, QPoint(10, 2))
            DanmakuFloatWindow._move_group(floating, QPoint(11, 3))
            emit.assert_not_called()
            DanmakuFloatWindow._finish_move(floating)
            self.assertEqual(move.call_count, 2)
            finish.assert_called_once_with(floating)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.args, ('float-group-move',))
        row = emit.call_args.kwargs
        self.assertEqual((row['windows'], row['pointerUpdates'], row['glass']), (2, 2, True))
        self.assertGreaterEqual(row['maxMoveMs'], 0)

    def test_live_layer_sampling_is_bounded_and_preserves_items(self):
        app = QApplication.instance() or QApplication([])
        if app.platformName() != 'windows':
            self.skipTest('Native Quick window requires Windows')
        import ctypes
        import PySide6
        qt_dir = Path(PySide6.__file__).parent
        with os.add_dll_directory(str(qt_dir)):
            ctypes.WinDLL(str(qt_dir / 'Qt6QuickEffects.dll'))
        with tempfile.TemporaryDirectory() as directory:
            parent = QWidget()
            parent.setAttribute(Qt.WA_ShowWithoutActivating)
            parent.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
            parent.setGeometry(-14000, -14000, 800, 500)
            parent.show()
            parent.winId()
            layer = QuickDanmakuLayer(parent)
            trace = MotionTrace(Path(directory) / 'motion.jsonl')
            trace.LIMIT = 10
            group = layer.create_group(0, 0, 800, 500)
            image = QImage(100, 30, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.white)
            identifier = layer.add(group, image, 600, 30, 100, 30, 80)
            item = layer.items[identifier]['item']
            children = list(item.childItems())
            trace.attach(layer)
            try:
                QTest.qWait(150)
                layer.set_group_active(group, False)
                layer.window.hide()
                QTest.qWait(150)
                layer.set_group_active(group, True)
                layer.show()
                QTest.qWait(150)
                self.assertEqual(item.childItems(), children, 'No render-thread probes may be attached')
                self.assertEqual(set(layer.items), {identifier})
                self.assertIs(layer.items[identifier]['item'], item)
                timer = layer.findChildren(QTimer)[-1]
                for _ in range(30):
                    timer.timeout.emit()
                rows = [json.loads(line) for line in trace.path.read_text().splitlines()]
                self.assertEqual(len(rows), trace.LIMIT)
                self.assertTrue(any(row['stage'] == 'sample' for row in rows))
                self.assertTrue(all(row['session'] == trace.session for row in rows))
                self.assertFalse(timer.isActive())
                for row in rows:
                    self.assertFalse({'text', 'message', 'cookie', 'frames'} & row.keys())
                trace.arm()
                self.assertTrue(timer.isActive(), 'A later user marker must restart bounded sampling')
                for _ in range(30):
                    timer.timeout.emit()
                self.assertFalse(timer.isActive())
                self.assertEqual(len(trace.path.read_text().splitlines()), trace.LIMIT * 2)
            finally:
                layer.remove_group(group)
                layer.window.hide()
                parent.close()
                layer.window.destroy()
                app.processEvents()


if __name__ == '__main__':
    unittest.main()
