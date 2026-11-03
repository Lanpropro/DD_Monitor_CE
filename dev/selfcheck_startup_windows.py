"""Isolated startup regressions; native timing is not a live performance claim."""
from contextlib import ExitStack
import os
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
runpy.run_path(str(ROOT / 'main.py'), run_name='bootstrap')

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, plugins, theme
from ddm.app import MainWindow
from ddm.fullscreen_bar import FullscreenBar
from ddm.widgets import Sidebar


class TopLevelShows(QObject):
    def __init__(self):
        super().__init__()
        self.widgets = []
        self.frames = []
        self.native_sizes = []

    def eventFilter(self, watched, event):
        if isinstance(watched, QWidget) and event.type() == QEvent.Show and watched.isWindow():
            self.widgets.append((type(watched).__name__, watched.objectName()))
        if isinstance(watched, MainWindow) and event.type() == QEvent.Paint:
            wall = watched.wall
            tiles = wall.visible_tiles()
            if tiles:
                bounds = tiles[0].geometry()
                for tile in tiles[1:]:
                    bounds = bounds.united(tile.geometry())
                self.frames.append((bounds, wall._corner_area()))
        if (isinstance(watched, MainWindow) and event.type() == QEvent.WinIdChange
                and watched.internalWinId()):
            self.native_sizes.append(watched.size())
        return False


class StartupWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(directory) / 'plugins')))
        self.stack.enter_context(patch.object(plugins.PluginManager, 'load'))
        for method in ('start_all', 'start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars', 'load_cached_covers',
                       'load_cached_avatars', '_check_startup_update', '_check_startup_plugins'):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.shows = TopLevelShows()
        self.app.installEventFilter(self.shows)
        self.addCleanup(self.app.removeEventFilter, self.shows)

    def test_sidebar_construction_never_shows_detached_header_or_account_windows(self):
        sidebar = Sidebar([])
        try:
            self.assertEqual(self.shows.widgets, [])
            for widget in (sidebar.logo_label, sidebar.title_label,
                           sidebar.subtitle_label, sidebar.account_row):
                self.assertIsNotNone(widget.parentWidget())
        finally:
            sidebar.close()
            sidebar.deleteLater()
            self.app.processEvents()

    def test_first_show_and_resize_fill_wall_before_the_settle_timer(self):
        for identifier, size in (('corner', (1600, 900)), ('2x2', (1600, 900)),
                                 ('portrait_main6', (850, 1400))):
            with self.subTest(layout=identifier):
                window = MainWindow([], [], layout_id=identifier, state={
                    'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
                try:
                    window.move(-20000, -20000)
                    window.resize(*size)
                    window.show()
                    self.app.processEvents()
                    self.assert_wall_filled(window)
                    window.resize(size[0] + 60, size[1] + 40)
                    # Ordinary resizing must still settle after the first paint.
                    QTest.qWait(350)
                    self.assert_wall_filled(window)
                    self.assertFalse(window._resize_dirty)
                    window.hide()
                    window.show()
                    QTest.qWait(350)
                    self.assert_wall_filled(window)
                finally:
                    window.close()
                    self.app.processEvents()

    def test_initial_maximize_does_not_enter_interactive_resize_mode(self):
        window = MainWindow([], [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        try:
            window.resize(1600, 900)
            window.showMaximized()
            self.assertFalse(window.wall._interactive_resize)
            self.assertFalse(window._resize_dirty)
            self.assert_wall_filled(window)
            self.app.processEvents()
            self.assert_wall_filled(window)
            QTest.qWait(350)
            self.assert_wall_filled(window)
            self.assertTrue(self.shows.frames)
            for bounds, area in self.shows.frames:
                self.assertEqual(bounds, area, 'A startup frame used stale pane geometry')
        finally:
            window.close()
            self.app.processEvents()

    def test_hidden_construction_does_not_create_native_video_windows(self):
        window = MainWindow([], [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        try:
            self.assertEqual(int(window.internalWinId()), 0)
            self.assertTrue(all(int(tile.video.internalWinId()) == 0 for tile in window.wall.tiles))
        finally:
            window.close()
            self.app.processEvents()

    def test_normal_bars_do_not_filter_unrelated_wall_events(self):
        window = MainWindow([], [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        try:
            calls = []
            with patch.object(FullscreenBar, 'eventFilter', lambda self, watched, event: calls.append(watched) or False):
                self.app.sendEvent(window.wall, QEvent(QEvent.User))
            self.assertEqual(calls, [])
        finally:
            window.close()
            self.app.processEvents()

    @unittest.skipUnless(sys.platform == 'win32', 'Native Windows visibility order')
    def test_native_maximized_client_is_ready_before_it_becomes_visible(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Requires Windows Qt on an isolated desktop')
        import ctypes
        from ctypes import wintypes
        class Visibility(QAbstractNativeEventFilter):
            def __init__(self):
                super().__init__()
                self.frames = []

            def nativeEventFilter(self, kind, message):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x47 and msg.hWnd == window.internalWinId():
                    user32 = ctypes.windll.user32
                    if user32.IsWindowVisible(wintypes.HWND(msg.hWnd)):
                        bounds = wintypes.RECT()
                        user32.GetClientRect(wintypes.HWND(msg.hWnd), ctypes.byref(bounds))
                        scale = window.devicePixelRatioF()
                        self.frames.append(((bounds.right, bounds.bottom),
                            (round(window.width()*scale), round(window.height()*scale))))
                return False, 0
        window = MainWindow([], [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        capture = Visibility()
        self.app.installNativeEventFilter(capture)
        try:
            window.show_initial_maximized()
            self.app.processEvents()
            self.assertTrue(capture.frames)
            self.assertTrue(self.shows.native_sizes)
            self.assertTrue(all(size == window.size() for size in self.shows.native_sizes))
            for native, logical in capture.frames:
                self.assertTrue(all(abs(a-b) <= 1 for a,b in zip(native,logical)), capture.frames)
            self.assert_wall_filled(window)
        finally:
            self.app.removeNativeEventFilter(capture)
            window.close()
            self.app.processEvents()

    def assert_wall_filled(self, window):
        wall = window.wall
        tiles = wall.visible_tiles()
        self.assertTrue(tiles)
        bounds = tiles[0].geometry()
        for tile in tiles[1:]:
            bounds = bounds.united(tile.geometry())
        self.assertEqual(bounds, wall._corner_area())


if __name__ == '__main__':
    unittest.main()
