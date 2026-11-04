"""Numeric motion capture must not touch render-thread nodes or message data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from ddm.video_danmaku_quick import QuickDanmakuLayer
from dev.diagnose_danmaku_motion import MotionTrace


class MotionDiagnosticsTests(unittest.TestCase):
    def test_live_layer_sampling_is_bounded_and_preserves_items(self):
        app = QApplication.instance() or QApplication([])
        if app.platformName() != 'windows':
            self.skipTest('Native Quick window requires Windows')
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
