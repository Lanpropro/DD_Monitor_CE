"""Windows caption routing and single-window movement regression; no live accounts."""
import ctypes
from ctypes import wintypes
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QEvent, QObject, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from ddm.app import MainWindow
from ddm.plugins import PluginManager
from dev.selfcheck_display_transition import make_window, assert_settled


@unittest.skipUnless(sys.platform == 'win32', 'Windows native window state')
class MoveRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.user32 = ctypes.windll.user32
        cls.user32.IsZoomed.argtypes = (wintypes.HWND,)
        cls.user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        cls.user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    def setUp(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Requires native Windows Qt backend')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(PluginManager, 'load'))
        for name in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                     'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                     'load_cached_covers', 'load_cached_avatars', '_check_startup_update'):
            self.stack.enter_context(patch.object(MainWindow, name))
        self.window = make_window(6, 'corner')
        self.window.setWindowOpacity(0)
        self.addCleanup(self.close)

    def close(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def send(self, code):
        self.user32.SendMessageW(int(self.window.winId()), code, 0, 0)

    def test_caption_messages_delegate_without_capture_or_substitute_windows(self):
        windows = set(QApplication.topLevelWidgets())
        for code in (0x00A1, 0x00A2, 0x00A3):
            message = wintypes.MSG()
            message.hWnd = int(self.window.winId())
            message.message, message.wParam = code, 2
            with patch.object(QMainWindow, 'nativeEvent', return_value=(False, 0)) as native, \
                    patch.object(QWidget, 'grabMouse') as capture:
                result = self.window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
            self.assertEqual(result, (False, 0))
            native.assert_called_once()
            capture.assert_not_called()
            self.assertEqual(set(QApplication.topLevelWidgets()), windows)

    def test_ordinary_move_keeps_real_window_visible_and_does_not_relayout(self):
        window = self.window
        hwnd = int(window.winId())
        events = []
        class Observer(QObject):
            def eventFilter(self, obj, event):
                if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
                    events.append(event.type())
                return False
        observer = Observer(window)
        window.installEventFilter(observer)
        with patch.object(window.wall, 'relayout', wraps=window.wall.relayout) as layout:
            self.send(0x0231)
            window.move(window.pos()+QPoint(15, 10))
            self.send(0x0232)
            QTest.qWait(80)
        self.assertTrue(window.isVisible())
        self.assertEqual(int(window.winId()), hwnd)
        self.assertEqual(events, [])
        layout.assert_not_called()
        assert_settled(window)

    def test_native_restore_of_equal_size_maximized_window_stays_normal(self):
        window = self.window
        window.show_initial_maximized()
        QTest.qWait(100)
        hwnd = int(window.winId())
        self.assertTrue(window.isMaximized())
        self.assertTrue(self.user32.IsZoomed(hwnd))
        # Model the OS restore transition, not physical caption input. Actual
        # title-bar input is recorded separately in the isolated root GUI.
        self.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        window.move(window.pos()+QPoint(15, 10))
        QTest.qWait(300)
        self.assertFalse(window.isMaximized())
        self.assertFalse(self.user32.IsZoomed(hwnd))
        self.assertTrue(window.isVisible())
        self.assertEqual(int(window.winId()), hwnd)

    def test_native_caption_double_click_still_toggles_maximize(self):
        hwnd = int(self.window.winId())
        for expected in (True, False):
            self.user32.SendMessageW(hwnd, 0x00A3, 2, 0)
            QTest.qWait(300)
            self.assertEqual(self.window.isMaximized(), expected)
            self.assertEqual(bool(self.user32.IsZoomed(hwnd)), expected)


if __name__ == '__main__':
    unittest.main()
