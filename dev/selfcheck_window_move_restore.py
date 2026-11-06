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
from PySide6.QtGui import QScreen
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm.window_move import MovePreview, WindowMove
from ddm.window_fullscreen import _dwm_get, _dwm_set


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

    def test_preview_is_painted_before_source_is_hidden(self):
        # A fully transparent QWidget skips painting; use a nearly transparent
        # preview for this paint-delivery regression only.
        initialize = MovePreview.__init__
        def paintable(preview, *args):
            initialize(preview, *args)
            preview.setWindowOpacity(0.01)
        self.window.resize(1000, 700)
        self.window.show()
        QTest.qWait(30)
        painted = []
        paint = MovePreview.paintEvent
        def record(preview, event):
            painted.append(_dwm_get(int(self.window.winId()), 14) == 0)
            return paint(preview, event)
        with patch.object(MovePreview, '__init__', paintable), patch.object(MovePreview, 'paintEvent', record):
            self.begin()
        self.assertIn(True, painted, 'Source cloaked before preview first paint')

    def test_handoff_disables_transitions_and_cancel_restores_them(self):
        self.window.resize(1000, 700)
        self.window.show()
        changes = []
        def record(hwnd, attribute, value):
            changes.append((hwnd, attribute, value, self.window.isVisible()))
            return _dwm_set(hwnd, attribute, value)
        with patch('ddm.window_move._dwm_set', side_effect=record, create=True):
            preview = self.begin()
            hwnd = int(preview.winId())
            self.controller.cancel()
        self.assertEqual(changes, [(hwnd, 3, 1, True),
                                  (int(self.window.winId()), 3, 1, True),
                                  (int(self.window.winId()), 13, 1, True),
                                  (int(self.window.winId()), 15, 0, True),
                                  (int(self.window.winId()), 13, 0, True),
                                  (int(self.window.winId()), 3, 0, True)])
        self.assertTrue(self.window.isVisible())
        self.assertEqual(_dwm_get(int(self.window.winId()), 14), 0)
        self.assertFalse(preview.thumbnail)

    def test_completed_handoff_restores_source_transitions(self):
        self.window.resize(1000, 700)
        self.window.show()
        with patch('ddm.window_move._dwm_set', wraps=_dwm_set, create=True) as setter:
            self.begin()
            self.controller.finish()
            QTest.qWait(300)
        self.assertIsNone(self.controller.preview)
        self.assertTrue(self.window.isVisible())
        setter.assert_called_with(int(self.window.winId()), 3, 0)

    def test_offscreen_move_uses_full_composition_without_desktop_capture(self):
        area = self.window.screen().availableGeometry()
        self.window.setGeometry(area.right()-100, area.bottom()-100, 1000, 700)
        self.window.show()
        # Windows may select a neighbouring monitor when this fixture straddles
        # an edge. Deliver its initial DPI/size messages before starting a move.
        QTest.qWait(120)
        with patch.object(QScreen, 'grabWindow', side_effect=AssertionError('Desktop capture')):
            preview = self.begin()
        self.assertTrue(preview.thumbnail)
        self.assertEqual(preview.size(), self.window.size())
        self.assertTrue(self.window.isVisible())
        self.assertEqual(_dwm_get(int(self.window.winId()), 14), 1)
        self.controller.cancel()
        self.assertEqual(_dwm_get(int(self.window.winId()), 14), 0)
        self.assertFalse(preview.thumbnail)

    def test_unavailable_composition_leaves_source_visible(self):
        self.window.show()
        with patch.object(ctypes.windll.dwmapi, 'DwmRegisterThumbnail', return_value=-1):
            self.assertIsNone(self.controller.begin())
        self.assertTrue(self.window.isVisible())
        self.assertEqual(_dwm_get(int(self.window.winId()), 14), 0)
        self.assertIsNone(self.controller.preview)


if __name__ == '__main__':
    unittest.main()
