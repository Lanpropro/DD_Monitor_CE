"""Drag hit coordinates, occlusion and transparent native windows; no user data."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from ddm import sidebar_hit_test as hit


class SidebarHitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_non_native_backend_keeps_qt_lookup(self):
        point = QPoint(40, 50)
        with patch.object(QApplication, 'platformName', return_value='offscreen'), \
                patch.object(QApplication, 'widgetAt', return_value='qt-target') as query:
            self.assertEqual(hit.widget_at(point), 'qt-target')
            query.assert_called_once_with(point)

    def test_native_lookup_scales_offsets_and_never_changes_window_masks(self):
        for origin, point, ratio, expected in (
                (QPoint(), QPoint(10, 20), 1, (10, 20)),
                (QPoint(-1920, 0), QPoint(-1820, 100), 1.5, (-1770, 150)),
                (QPoint(1920, -1080), QPoint(2020, -980), 2, (2120, -880))):
            screen = SimpleNamespace(geometry=lambda: QRect(origin.x(), origin.y(), 1200, 900),
                                     devicePixelRatio=lambda: ratio)
            native = Mock()
            native.GetDesktopWindow.return_value = 1
            native.ChildWindowFromPointEx.return_value = 2
            window = Mock()
            window.testAttribute.return_value = False
            window.mapFromGlobal.return_value = QPoint(8, 9)
            window.childAt.return_value = 'child-target'
            with self.subTest(ratio=ratio, origin=origin), \
                    patch.object(hit, '_user32', native), \
                    patch.object(QApplication, 'platformName', return_value='windows'), \
                    patch.object(QApplication, 'screenAt', return_value=screen), \
                    patch.object(QApplication, 'widgetAt', side_effect=AssertionError('No mask-based lookup')), \
                    patch.object(QWidget, 'find', return_value=window) as find:
                self.assertEqual(hit.widget_at(point), 'child-target')
                desktop, physical, flags = native.ChildWindowFromPointEx.call_args.args
                self.assertEqual((desktop, physical.x, physical.y, flags), (1, *expected, 5))
                find.assert_called_once_with(2)
                window.childAt.assert_called_once_with(QPoint(8, 9))

    def test_native_occlusion_and_no_child_keep_existing_target_boundaries(self):
        native = Mock()
        native.GetDesktopWindow.return_value = 1
        screen = SimpleNamespace(geometry=lambda: QRect(0, 0, 1000, 1000), devicePixelRatio=lambda: 1)
        with patch.object(hit, '_user32', native), \
                patch.object(QApplication, 'platformName', return_value='windows'), \
                patch.object(QApplication, 'screenAt', return_value=screen), \
                patch.object(QWidget, 'find', return_value=None) as find:
            for handle in (0, 1, 99):
                native.ChildWindowFromPointEx.return_value = handle
                self.assertIsNone(hit.widget_at(QPoint(30, 40)))
            find.assert_called_once_with(99)
            window = Mock()
            window.testAttribute.return_value = False
            window.childAt.return_value = None
            find.return_value = window
            self.assertIs(hit.widget_at(QPoint(30, 40)), window)
            window.testAttribute.return_value = True
            with patch.object(QApplication, 'widgetAt', return_value='under-transparent-window'):
                self.assertEqual(hit.widget_at(QPoint(30, 40)), 'under-transparent-window')
        with patch.object(hit, '_user32', native), \
                patch.object(QApplication, 'platformName', return_value='windows'), \
                patch.object(QApplication, 'screenAt', return_value=None), \
                patch.object(QApplication, 'widgetAt', return_value='qt-fallback'):
            self.assertEqual(hit.widget_at(QPoint(30, 40)), 'qt-fallback')

    def test_native_ghost_is_excluded_without_hiding_it_or_using_qt_masks(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Native Windows backend; run in hosted CI')
        owner = QWidget(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                        | Qt.WindowDoesNotAcceptFocus)
        owner.setAttribute(Qt.WA_ShowWithoutActivating)
        screen = self.app.primaryScreen()
        owner.setGeometry(QRect(screen.availableGeometry().topLeft() + QPoint(8, 8),
                                QSize(64, 64)))
        target = QFrame(owner)
        target.setGeometry(owner.rect())
        ghost = QLabel(owner, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        ghost.setAttribute(Qt.WA_ShowWithoutActivating)
        ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
        ghost.setAttribute(Qt.WA_TranslucentBackground)
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.red)
        ghost.setPixmap(pixmap)
        ghost.resize(64, 64)
        try:
            owner.show()
            ghost.move(owner.mapToGlobal(QPoint()))
            ghost.show()
            self.app.processEvents()
            point = target.mapToGlobal(QPoint(20, 20))
            self.assertTrue(ghost.geometry().contains(point))
            with patch.object(QApplication, 'widgetAt', side_effect=AssertionError('Native fast path required')):
                self.assertIs(hit.widget_at(point), target)
            self.assertTrue(ghost.isVisible())
        finally:
            owner.close()
            owner.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
