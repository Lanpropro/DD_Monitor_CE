"""Windows move completion regression; isolated transparent fixture, no live accounts."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap, QScreen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm.window_move import MovePreview, WindowMove


@unittest.skipUnless(sys.platform == 'win32', 'Windows native window state')
class MoveRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.user32 = ctypes.windll.user32
        cls.user32.IsZoomed.argtypes = (wintypes.HWND,)

    def setUp(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Requires native Windows Qt backend')
        self.window = QWidget()
        self.window.setWindowOpacity(0)
        self.window._fullscreen_tile = None
        self.window._finish_interactive_resize = lambda: None
        self.controller = WindowMove(self.window, int(self.window.winId()))
        self.addCleanup(self.close)
        original = MovePreview.__init__
        def transparent(preview, *args):
            original(preview, *args)
            preview.setWindowOpacity(0)
        self.preview_patch = patch.object(MovePreview, '__init__', transparent)
        self.preview_patch.start()
        self.addCleanup(self.preview_patch.stop)
        self.frame_patch = patch.object(QScreen, 'grabWindow', return_value=QPixmap(100, 70))
        self.frame_patch.start()
        self.addCleanup(self.frame_patch.stop)

    def close(self):
        self.controller.cancel(restore=False)
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def maximize_with_full_work_area_restore_geometry(self):
        # The startup pre-layout leaves normalGeometry at the maximized client size.
        # This equal-size native transition is missing from the older move tests.
        area = self.window.screen().availableGeometry()
        scale = self.window.screen().devicePixelRatio()
        caption = round(self.user32.GetSystemMetricsForDpi(4, round(96 * scale)) / scale)
        self.window.setGeometry(area.adjusted(0, caption, 0, 0))
        self.window.showMaximized()
        QTest.qWait(80)
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.user32.IsZoomed(int(self.window.winId())))

    def begin(self):
        area = self.window.screen().availableGeometry()
        point = area.topLeft() + QPoint(600, 220)
        with patch('ddm.window_move.QCursor.pos', return_value=point):
            preview = self.controller.begin()
        self.assertIsNotNone(preview)
        return preview

    def test_drop_from_maximized_restores_both_qt_and_native_state(self):
        self.maximize_with_full_work_area_restore_geometry()
        restore_size = self.window.normalGeometry().size()
        self.begin()
        self.controller.finish()
        QTest.qWait(300)
        self.assertFalse(self.user32.IsZoomed(int(self.window.winId())),
                         'Native HWND returned to maximized after ordinary drop')
        self.assertFalse(self.window.isMaximized())
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window.size(), restore_size)
        self.assertIsNone(self.controller.preview)

    def test_cancel_retains_original_maximized_state(self):
        self.maximize_with_full_work_area_restore_geometry()
        self.begin()
        self.controller.finish(cancelled=True)
        QTest.qWait(80)
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.user32.IsZoomed(int(self.window.winId())))
        self.assertIsNone(self.controller.preview)

    def test_intentional_preview_maximize_still_maximizes_source(self):
        self.window.resize(1000, 700)
        self.window.show()
        QTest.qWait(30)
        preview = self.begin()
        preview.showMaximized()
        QTest.qWait(80)
        self.assertTrue(preview.isMaximized())
        self.controller.finish()
        QTest.qWait(300)
        self.assertTrue(self.window.isMaximized())
        self.assertTrue(self.user32.IsZoomed(int(self.window.winId())))
        self.assertIsNone(self.controller.preview)


if __name__ == '__main__':
    unittest.main()
