"""Offline native-caption theme checks; never load accounts, media or plugins."""
from contextlib import ExitStack
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from ddm import theme, window_fullscreen
from ddm.app import MainWindow


def colorref(value):
    color = theme.qcolor(value)
    return color.red() + color.green() * 256 + color.blue() * 65536


class TitlebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_mode = theme.mode()
        self.addCleanup(theme.apply, self.old_mode)

    def native_calls(self, window):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(window_fullscreen.sys, 'platform', 'win32'))
        stack.enter_context(patch.object(QApplication, 'platformName', return_value='windows'))
        return stack.enter_context(patch.object(window_fullscreen, '_dwm_set'))

    def test_no_native_handle_is_created_for_hidden_uncreated_window(self):
        window = QMainWindow()
        calls = self.native_calls(window)
        self.assertFalse(window.testAttribute(Qt.WA_WState_Created))
        window_fullscreen.sync_titlebar(window)
        calls.assert_not_called()
        self.assertFalse(window.testAttribute(Qt.WA_WState_Created))

    def test_themes_keep_native_controls_flags_geometry_and_child_handles(self):
        window = QMainWindow()
        child = QWidget(window)
        window.resize(900, 600)
        handles = int(window.winId()), int(child.winId())
        flags, geometry = window.windowFlags(), window.geometry()
        calls = self.native_calls(window)
        for mode in ('dark', 'light', 'dark'):
            theme.apply(mode)
            calls.reset_mock()
            window_fullscreen.sync_titlebar(window)
            self.assertEqual([call.args for call in calls.call_args_list], [
                (handles[0], 20, int(mode == 'dark')),
                (handles[0], 35, colorref(theme.BG)),
                (handles[0], 36, colorref(theme.TEXT1)),
                (handles[0], 34, colorref(theme.BG))])
            self.assertEqual((int(window.winId()), int(child.winId())), handles)
            self.assertEqual(window.windowFlags(), flags)
            self.assertEqual(window.geometry(), geometry)
            for flag in (Qt.WindowTitleHint, Qt.WindowMinimizeButtonHint,
                         Qt.WindowMaximizeButtonHint, Qt.WindowCloseButtonHint):
                self.assertTrue(flags & flag)
            self.assertFalse(flags & Qt.FramelessWindowHint)

    def test_fullscreen_frame_is_not_recolored_until_exit(self):
        window = QMainWindow()
        window.winId()
        calls = self.native_calls(window)
        window._fullscreen_tile = object()
        theme.apply('light')
        window_fullscreen.sync_titlebar(window)
        calls.assert_not_called()
        window._fullscreen_tile = None
        window_fullscreen.sync_titlebar(window)
        self.assertEqual(calls.call_args.args, (int(window.winId()), 34, colorref(theme.BG)))

    def test_non_windows_backend_is_untouched(self):
        window = QMainWindow()
        window.winId()
        with patch.object(QApplication, 'platformName', return_value='offscreen'), \
                patch.object(window_fullscreen, '_dwm_set') as calls:
            window_fullscreen.sync_titlebar(window)
            calls.assert_not_called()
        with patch.object(window_fullscreen.sys, 'platform', 'linux'), \
                patch.object(window_fullscreen, '_dwm_set') as calls:
            window_fullscreen.sync_titlebar(window)
            calls.assert_not_called()

    def test_unsupported_attributes_keep_native_fallback_without_error(self):
        setter = Mock(return_value=-2147024809)  # E_INVALIDARG on older systems.
        library = Mock(DwmSetWindowAttribute=setter)
        with patch.object(ctypes, 'windll', Mock(dwmapi=library), create=True):
            window_fullscreen._dwm_set(0x123456789, 35, 0x123456)
        self.assertEqual(setter.call_args.args[:2], (0x123456789, 35))
        self.assertEqual(ctypes.cast(setter.call_args.args[2],
                                    ctypes.POINTER(wintypes.DWORD)).contents.value, 0x123456)
        self.assertEqual(setter.argtypes[0], wintypes.HWND)

    def test_main_window_show_theme_change_and_fullscreen_exit_sync(self):
        with ExitStack() as stack:
            for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                           'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                           'load_cached_covers', 'load_cached_avatars', '_start_avatar_loader'):
                stack.enter_context(patch.object(MainWindow, method))
            stack.enter_context(patch('ddm.app.QTimer.singleShot'))
            stack.enter_context(patch('ddm.motion.enabled', return_value=False))
            window = MainWindow([], [], layout_id='1x1', state={'plugins_enabled': []})
            stack.callback(window.close)
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.move(-10000, -10000)
            calls = stack.enter_context(patch.object(window_fullscreen, 'sync_titlebar'))
            window.show()
            self.app.processEvents()
            self.assertTrue(calls.called)
            calls.reset_mock()
            theme.apply('light')
            calls.assert_called_once_with(window)
            tile = window.wall.tiles[0]
            tile.set_room({'room_id': '990000', 'uname': 'Fixture'})
            handles = int(window.winId()), int(tile.video.winId())
            window._on_fullscreen(tile)
            theme.apply('dark')
            calls.reset_mock()
            window._exit_fullscreen()
            self.assertIsNone(window._fullscreen_tile)
            self.assertTrue(calls.called)
            self.assertEqual((int(window.winId()), int(tile.video.winId())), handles)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_native_dwm_colors_and_fullscreen_roundtrip_on_hidden_fixture(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Run with QT_QPA_PLATFORM=windows for native DWM verification')
        if sys.getwindowsversion().build < 22000:
            self.skipTest('Caption colors require Windows 11')
        window = QMainWindow()
        child = QWidget(window)
        window.resize(900, 600)
        handles = int(window.winId()), int(child.winId())
        results = []
        original = window_fullscreen._dwm_set
        def record(hwnd, attribute, value):
            result = original(hwnd, attribute, value)
            results.append((hwnd, attribute, value, result))
            return result
        # Caption colors are set-only DWM attributes, not queryable with DwmGet.
        with patch.object(window_fullscreen, '_dwm_set', side_effect=record):
            for mode in ('light', 'dark'):
                theme.apply(mode)
                window_fullscreen.sync_titlebar(window)
                self.assertEqual(results[-4:], [
                    (handles[0], 20, int(mode == 'dark'), 0),
                    (handles[0], 35, colorref(theme.BG), 0),
                    (handles[0], 36, colorref(theme.TEXT1), 0),
                    (handles[0], 34, colorref(theme.BG), 0)])
        state = window_fullscreen.enter(window)
        window._fullscreen_tile = object()
        theme.apply('light')
        with patch.object(window_fullscreen, '_dwm_set') as calls:
            window_fullscreen.sync_titlebar(window)
            calls.assert_not_called()
        window_fullscreen.exit(window, state)
        window._fullscreen_tile = None
        with patch.object(window_fullscreen, '_dwm_set', side_effect=record):
            window_fullscreen.sync_titlebar(window)
            self.assertEqual(results[-1], (handles[0], 34, colorref(theme.BG), 0))
        self.assertEqual((int(window.winId()), int(child.winId())), handles)
        self.assertFalse(window.isVisible())


if __name__ == '__main__':
    unittest.main()
