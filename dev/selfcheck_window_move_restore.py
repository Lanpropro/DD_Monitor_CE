"""Windows caption routing and single-window movement regression; no live accounts."""
import ctypes
from ctypes import wintypes
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
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

    def test_restore_order_keeps_interactive_resize_until_native_exit(self):
        window = self.window
        for enter_first in (True, False):
            with self.subTest(enter_first=enter_first):
                window._native_size_state = 2
                message = wintypes.MSG()
                message.hWnd = int(window.winId())
                message.message, message.wParam = 0x0005, 0
                if enter_first:
                    self.send(0x0231)
                with patch.object(QMainWindow, 'nativeEvent', return_value=(False, 0)):
                    window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
                if not enter_first:
                    self.assertTrue(window._resize_idle_timer.isActive())
                    self.send(0x0231)
                QTest.qWait(230)
                self.assertTrue(window._interactive_resize)
                self.assertTrue(window.wall._interactive_resize)
                self.assertFalse(window._resize_idle_timer.isActive())
                self.send(0x0232)
                assert_settled(window)

    def test_resize_trace_records_native_order_and_nested_layout_work(self):
        from dev.diagnose_window_resize import WindowResizeTrace
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resize.jsonl'
            trace = WindowResizeTrace(path)
            with trace:
                # PySide caches virtual overrides when constructing an object;
                # install before construction, as the diagnostic launcher does.
                window = make_window(6, 'corner')
                try:
                    hwnd = int(window.winId())
                    self.user32.SendMessageW(hwnd, 0x0231, 0, 0)
                    window.resize(window.width() + 40, window.height() + 20)
                    QTest.qWait(70)
                    self.user32.SendMessageW(hwnd, 0x0232, 0, 0)
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            row = json.loads(path.read_text())
        self.assertFalse(row['final']['interactive'])
        self.assertFalse(row['final']['wallInteractive'])
        self.assertEqual([x['message'] for x in row['messages'] if x['message'] in (0x0231, 0x0232)],
                         [0x0231, 0x0232])
        self.assertTrue(any(x['method'] == 'WallGrid._flush_resize' for x in row['calls']))
        self.assertTrue(any(x['method'] == 'Tile._layout_areas' for x in row['calls']))
        self.assertTrue(all(x['elapsedMs'] >= x['selfMs'] >= 0 for x in row['calls']))


if __name__ == '__main__':
    unittest.main()
