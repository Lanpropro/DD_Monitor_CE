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
        cls.user32.GetParent.argtypes = (wintypes.HWND,)
        cls.user32.GetParent.restype = wintypes.HWND

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

    def test_native_video_and_bar_keep_handles_without_promoting_bar_children(self):
        window = self.window
        self.assertFalse(window.sidebar.internalWinId(), 'Sidebar does not need a native sibling window')
        tile = window.wall.tiles[0]
        tile.video.winId()  # The same explicit native binding used by TilePlayer.bind.
        self.assertTrue(window.centralWidget().internalWinId())
        self.assertTrue(window._content.internalWinId())
        self.assertIs(window.wall.parentWidget(), window._content)
        self.assertEqual(self.user32.GetParent(int(window.wall.internalWinId())),
                         int(window._content.internalWinId()))
        for widget in (tile.video, tile.bottom, tile.controls, tile.stream_badge):
            self.assertTrue(widget.internalWinId(), type(widget).__name__)
        for widget in (tile.pause_button, tile.volume_slider, tile.volume_label,
                       tile.danmaku_button, tile.recording_button):
            self.assertFalse(widget.internalWinId(), type(widget).__name__)
        paused = []
        tile.pauseToggled.connect(paused.append)
        point = tile.pause_button.mapTo(tile.bottom, tile.pause_button.rect().center())
        scale = tile.bottom.devicePixelRatioF()
        packed = round(point.x()*scale) | (round(point.y()*scale) << 16)
        hwnd = int(tile.bottom.internalWinId())
        self.user32.SendMessageW(hwnd, 0x0201, 1, packed)
        self.user32.SendMessageW(hwnd, 0x0202, 0, packed)
        self.app.processEvents()
        self.assertEqual(paused, [tile.room], f'bar={tile.bottom.isVisible()} button={tile.pause_button.isVisible()}')

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

    def test_first_native_size_arms_wall_before_qt_resizes_children(self):
        window = self.window
        message = wintypes.MSG()
        message.hWnd = int(window.winId())
        message.message = 0x02e0
        with patch.object(QMainWindow, 'nativeEvent', return_value=(False, 0)):
            self.assertEqual(window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message)),
                             (False, 0))
        self.assertFalse(window.wall._interactive_resize, 'DPI outside a native gesture stays unchanged')
        tiles = list(window.wall.tiles)
        video_handles = [int(tile.video.internalWinId()) for tile in tiles]
        for code in (0x0005, 0x02e0):  # WM_SIZE and cross-screen WM_DPICHANGED
            with self.subTest(message=hex(code)):
                window._startup_layout_pending = True  # Parent can be covered by native children.
                self.send(0x0231)
                self.assertFalse(window._startup_layout_pending)
                self.assertFalse(window.wall._interactive_resize,
                                 'Pure movement must not activate wall resize')
                message = wintypes.MSG()
                message.hWnd = int(window.winId())
                message.message, message.wParam = code, 0
                with patch.object(QMainWindow, 'nativeEvent', return_value=(False, 0)):
                    window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
                self.assertTrue(window.wall._interactive_resize)
                with patch.object(window.wall, '_relayout_corner', wraps=window.wall._relayout_corner) as layout:
                    window.resize(window.width() + 30, window.height() + 15)
                    layout.assert_not_called()
                    self.assertTrue(window.wall._resize_timer.isActive())
                    self.send(0x0232)
                    layout.assert_called_once()
                assert_settled(window)
                self.assertEqual(window.wall.tiles, tiles)
                self.assertEqual([int(tile.video.internalWinId()) for tile in tiles], video_handles)

    def test_resize_trace_records_native_order_and_nested_layout_work(self):
        from dev.diagnose_window_resize import WindowResizeTrace
        class Probe:
            def event(self, event):
                if event.type() == QEvent.ScreenChangeInternal:
                    raise RuntimeError('probe')
                return 42
        original_event = Probe.event
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resize.jsonl'
            trace = WindowResizeTrace(path, profile_dpi=True)
            with trace:
                trace.wrap(Probe, 'event', event_types=(QEvent.ScreenChangeInternal,
                                                       QEvent.DevicePixelRatioChange))
                # PySide caches virtual overrides when constructing an object;
                # install before construction, as the diagnostic launcher does.
                window = make_window(6, 'corner')
                try:
                    hwnd = int(window.winId())
                    self.user32.SendMessageW(hwnd, 0x0231, 0, 0)
                    message = wintypes.MSG()
                    message.hWnd, message.message = hwnd, 0x02e0
                    with patch.object(QMainWindow, 'nativeEvent', return_value=(False, 0)):
                        window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
                    probe = Probe()
                    self.assertEqual(probe.event(QEvent(QEvent.Resize)), 42)
                    self.assertEqual(probe.event(QEvent(QEvent.DevicePixelRatioChange)), 42)
                    with self.assertRaisesRegex(RuntimeError, 'probe'):
                        probe.event(QEvent(QEvent.ScreenChangeInternal))
                    window.move(window.pos() + QPoint(20, 10))
                    self.assertIsNone(trace.dpi_profiler)
                    window.resize(window.width() + 40, window.height() + 20)
                    QTest.qWait(70)
                    self.user32.SendMessageW(hwnd, 0x0232, 0, 0)
                    trace.MAX_CALLS = 2
                    self.user32.SendMessageW(hwnd, 0x0231, 0, 0)
                    window.move(window.pos() + QPoint(20, 10))
                    window.move(window.pos() + QPoint(20, 10))
                    self.user32.SendMessageW(hwnd, 0x0232, 0, 0)
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            row = next(row for row in rows if row['source'] == 'native-resize')
            capped = [row for row in rows if row['source'] == 'native-resize'][1]
        self.assertTrue(capped['messagesCapped'])
        self.assertEqual(len(capped['messages']), 2)
        self.assertLessEqual(len(capped['calls']), 2)
        self.assertFalse(capped['final']['interactive'])
        self.assertFalse(row['final']['interactive'])
        self.assertFalse(row['final']['wallInteractive'])
        self.assertEqual([x['message'] for x in row['messages'] if x['message'] in (0x0231, 0x0232)],
                         [0x0231, 0x0232])
        self.assertIn(0x0003, [x['message'] for x in row['messages']])
        self.assertFalse(row['messagesCapped'])
        self.assertEqual(len(row['dpiProfiles']), 1)
        profile = row['dpiProfiles'][0]
        self.assertLessEqual(len(profile['functions']), 120)
        self.assertTrue(profile['functions'])
        self.assertIsNone(trace.dpi_profiler)
        self.assertGreaterEqual(row['cpuMs'], 0)
        self.assertTrue(all(x['cpuAtMs'] >= 0 for x in row['messages']))
        for key in ('initialTopology', 'finalTopology'):
            topology = row[key]
            self.assertGreater(topology['nativeWidgets'], 0)
            self.assertLessEqual(topology['nativeWidgets'], topology['widgets'])
            self.assertEqual(topology['nativeWidgets'], sum(topology['nativeTypes'].values()))
        self.assertTrue(any(x['method'] == 'WallGrid._flush_resize' for x in row['calls']))
        self.assertTrue(any(x['method'] == 'Tile._layout_areas' for x in row['calls']))
        self.assertTrue(all(x['elapsedMs'] >= x['selfMs'] >= 0 for x in row['calls']))
        self.assertTrue(all(x['cpuMs'] >= x['selfCpuMs'] >= 0 for x in row['calls']))
        self.assertIs(Probe.event, original_event)
        self.assertEqual([x['eventType'] for x in row['calls'] if x['method'] == 'Probe.event'],
                         [int(QEvent.DevicePixelRatioChange), int(QEvent.ScreenChangeInternal)])
        screen = self.window.screen()
        self.assertEqual(row['initial']['screenGeometry'], list(screen.geometry().getRect()))
        self.assertEqual(row['final']['screenAvailable'], list(screen.availableGeometry().getRect()))
        self.assertEqual(row['final']['screenScale'], screen.devicePixelRatio())
        self.assertNotIn('screenName', row['final'])
        self.assertEqual(row['source'], 'native-resize')
        self.assertIn('orientation', row['initial'])
        self.assertIn('sidebarSide', row['final'])

    def test_resize_trace_covers_menu_orientation_and_restores_wrappers(self):
        from ddm.window_layout import WindowLayout
        from dev.diagnose_window_resize import WindowResizeTrace
        original = WindowLayout.on_layout_changed
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resize.jsonl'
            trace = WindowResizeTrace(path)
            with trace:
                window = make_window(6, 'corner')
                try:
                    window._on_layout_changed('portrait_main2')
                    window._on_layout_changed('corner')
                finally:
                    window.close()
                    window.deleteLater()
                    self.app.processEvents()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertIs(WindowLayout.on_layout_changed, original)
        menus = [row for row in rows if row['source'] == 'WindowLayout.on_layout_changed']
        self.assertEqual(len(menus), 2)
        self.assertEqual([row['final']['orientation'] for row in menus], ['portrait', 'landscape'])
        self.assertTrue(any(call['method'] == 'SidebarOrientation.set_side'
                            for row in menus for call in row['calls']))
        self.assertTrue(any(call['method'] == 'WindowLayout.apply_orientation'
                            for row in menus for call in row['calls']))
        self.assertTrue(all(len(row['calls']) <= trace.MAX_CALLS for row in rows))
        self.assertNotIn('uname', json.dumps(rows))

    def test_resize_trace_stops_at_session_limit(self):
        from dev.diagnose_window_resize import WindowResizeTrace
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resize.jsonl'
            trace = WindowResizeTrace(path)
            trace.MAX_GESTURES = 2
            for _ in range(4):
                trace.begin(self.window)
                trace.flush()
            rows = path.read_text().splitlines()
        self.assertEqual(len(rows), 2)

    def test_dpi_profile_is_opt_in_bounded_and_stops_on_flush(self):
        from dev.diagnose_window_resize import WindowResizeTrace
        previous = sys.getprofile()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'resize.jsonl'
            trace = WindowResizeTrace(path)
            trace.begin(self.window)
            trace.start_dpi_profile()
            self.assertIsNone(trace.dpi_profiler)
            trace.flush()
            trace = WindowResizeTrace(path, profile_dpi=True)
            trace.MAX_DPI_PROFILES = 1
            trace.begin(self.window)
            trace.start_dpi_profile()
            sum(range(100))
            trace.finish_dpi_profile()
            trace.start_dpi_profile()
            self.assertIsNone(trace.dpi_profiler)
            trace.flush()
            trace.begin(self.window)
            trace.start_dpi_profile()
            trace.flush()  # Exit without a subsequent move must also disable profiling.
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertIs(sys.getprofile(), previous)
        self.assertEqual([len(row['dpiProfiles']) for row in rows], [0, 1, 1])
        self.assertTrue(any('builtins.sum' in f['function'] for f in rows[1]['dpiProfiles'][0]['functions']))
        self.assertTrue(all(len(p['functions']) <= 120 for row in rows for p in row['dpiProfiles']))
        self.assertNotIn('uname', json.dumps(rows))
        self.assertIsNone(trace.dpi_profiler)

    def test_same_size_native_message_still_clears_wall_mode_on_exit(self):
        window = self.window
        self.send(0x0231)
        message = wintypes.MSG()
        message.hWnd = int(window.winId())
        message.message, message.wParam = 0x0005, 0
        with patch.object(QMainWindow, 'nativeEvent', return_value=(False, 0)):
            window.nativeEvent(b'windows_generic_MSG', ctypes.addressof(message))
        self.assertTrue(window.wall._interactive_resize)
        self.send(0x0232)
        assert_settled(window)


if __name__ == '__main__':
    unittest.main()
