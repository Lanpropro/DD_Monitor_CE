"""Isolated startup regressions; native timing is not a live performance claim."""
from contextlib import ExitStack
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
runpy.run_path(str(ROOT / 'main.py'), run_name='bootstrap')

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, plugins, theme
from ddm.app import MainWindow
from ddm.fullscreen_bar import FullscreenBar
from ddm.player import TilePlayer
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

    def test_startup_restores_normal_geometry_saved_on_close(self):
        state = {'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}}
        source = MainWindow([], [], layout_id='1x1', state=state)
        source.setAttribute(Qt.WA_ShowWithoutActivating)
        source.show()
        area = source.screen().availableGeometry()
        source.resize(round(area.width() * .7), round(area.height() * .7))
        source.move(area.center() - source.rect().center())
        self.app.processEvents()
        expected = source.geometry()
        expected_pos = source.pos()
        with patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            source.close()
        restored = MainWindow([], [], state=config.load())
        restored.setAttribute(Qt.WA_ShowWithoutActivating)
        try:
            restored.show_initial_maximized()
            self.app.processEvents()
            self.assertFalse(restored.isMaximized(), 'Saved normal state must survive startup')
            self.assertLessEqual(abs(restored.width() - expected.width()), 1)
            self.assertLessEqual(abs(restored.height() - expected.height()), 1)
            self.assertLessEqual(abs(restored.x() - expected_pos.x()), 2)
            self.assertLessEqual(abs(restored.y() - expected_pos.y()), 2)
            self.assert_wall_filled(restored)
        finally:
            restored.close()
            self.app.processEvents()

    def test_initial_maximize_keeps_a_smaller_normal_restore_rectangle(self):
        window = MainWindow([], [], layout_id='1x1', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        window.resize(850, 600)
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        expected = window.size()
        try:
            window.show_initial_maximized()
            self.app.processEvents()
            self.assertTrue(window.isMaximized())
            window.showNormal()
            self.app.processEvents()
            self.assertLessEqual(abs(window.width() - expected.width()), 1)
            self.assertLessEqual(abs(window.height() - expected.height()), 1)
        finally:
            window.close()
            self.app.processEvents()

    def test_saved_maximized_state_keeps_normal_size_after_restart(self):
        source = MainWindow([], [], layout_id='1x1', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        source.setAttribute(Qt.WA_ShowWithoutActivating)
        area = source.screen().availableGeometry()
        source.resize(min(850, area.width() - 80), min(600, area.height() - 80))
        source.showMaximized()
        self.app.processEvents()
        expected = source.normalGeometry().size()
        with patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            source.close()
        restored = MainWindow([], [], state=config.load())
        restored.setAttribute(Qt.WA_ShowWithoutActivating)
        try:
            restored.show_initial_maximized()
            self.app.processEvents()
            self.assertTrue(restored.isMaximized())
            restored.showNormal()
            self.app.processEvents()
            self.assertLessEqual(abs(restored.width() - expected.width()), 1)
            self.assertLessEqual(abs(restored.height() - expected.height()), 1)
            QTest.qWait(350)  # Ordinary restore uses the existing resize settlement timer.
            self.assert_wall_filled(restored)
        finally:
            restored.close()
            self.app.processEvents()

    def test_invalid_saved_geometry_uses_initial_maximized_default(self):
        window = MainWindow([], [], layout_id='1x1', state={
            'geometry': 'invalid', 'plugins_enabled': [],
            'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        try:
            self.assertFalse(window._geometry_restored)
            window.show_initial_maximized()
            self.app.processEvents()
            self.assertTrue(window.isMaximized())
        finally:
            window.close()
            self.app.processEvents()

    def test_preview_native_window_keeps_other_cards_alien(self):
        window = QWidget(None, Qt.WindowDoesNotAcceptFocus)
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        sidebar = Sidebar([dict(room_id=str(i), uname=f'Fixture {i}') for i in range(24)], window)
        sidebar.setGeometry(0, 0, 248, 600)
        window.resize(500, 650)
        window.move(-20000, -20000)
        try:
            window.show()
            self.app.processEvents()
            first, other = sidebar.items()[:2]
            self.assertFalse(other.testAttribute(Qt.WA_NativeWindow))
            flag = Qt.AA_DontCreateNativeWidgetSiblings
            previous = QApplication.testAttribute(flag)
            with patch('ddm.player.mpv.MPV'):
                player = TilePlayer(first.thumb.video, silent=True)
                player.bind()
                self.assertTrue(first.thumb.video.internalWinId())
                self.assertEqual(QApplication.testAttribute(flag), previous)
                first.thumb.video.show()
                self.app.processEvents()
                player.release()
            self.assertFalse(first.testAttribute(Qt.WA_NativeWindow))
            self.assertFalse(first.thumb.testAttribute(Qt.WA_NativeWindow))
            self.assertFalse(other.testAttribute(Qt.WA_NativeWindow), 'One preview must not promote the whole list')
            self.assertFalse(other.thumb.video.testAttribute(Qt.WA_NativeWindow))
            self.assertFalse(other.internalWinId())
        finally:
            window.close()
            window.deleteLater()
            self.app.processEvents()

    def test_unchanged_status_does_not_repolish_or_relayout_cards(self):
        sidebar = Sidebar([dict(room_id='1', uname='Fixture', title='Title', live=False)])
        item = sidebar.items()[0]
        try:
            with patch('ddm.sidebar_item._repolish') as polish, \
                    patch.object(item.thumb, '_layout_overlay') as layout:
                item.set_live(False)
                item.set_title('Title')
                item.set_uname('Fixture')
                sidebar._sync_count()
                polish.assert_not_called()
                layout.assert_not_called()
                # Tiles may already have mutated the shared model: compare displayed state.
                item.room.update(live=True, title='New', uname='Renamed')
                item.set_live(True)
                item.set_title('New')
                item.set_uname('Renamed')
                self.assertEqual(item.badge.text(), '直播中')
                self.assertEqual(item.sub._full_text, 'New')
                self.assertEqual(item.name_label._full_text, 'Renamed')
                self.assertEqual(polish.call_count, 1)
                self.assertEqual(layout.call_count, 3)
        finally:
            sidebar.close()
            sidebar.deleteLater()
            self.app.processEvents()

    def test_startup_starts_one_current_tile_per_event_loop_turn_and_stops_on_close(self):
        tiles = [object(), object(), object()]
        host = SimpleNamespace(_closing=False, wall=SimpleNamespace(tiles=tiles[:]),
            players={tiles[1]: object()}, _resolvers={}, apply_quality_policy=Mock(), start_tile=Mock())
        from ddm.stream_playback import StreamPlayback
        host.stream_playback = StreamPlayback(host)
        callbacks = []
        with patch('ddm.app.QTimer.singleShot', side_effect=lambda delay, context, callback: callbacks.append(callback)):
            MainWindow._start_startup_tiles(host)
            host.apply_quality_policy.assert_called_once_with(restart=False)
            host.start_tile.assert_not_called()
            callbacks.pop(0)()
            host.start_tile.assert_called_once_with(tiles[0])
            self.assertEqual(len(callbacks), 1)
            callbacks.pop(0)()
            self.assertEqual([call.args[0] for call in host.start_tile.call_args_list], [tiles[0], tiles[2]])
            self.assertEqual(callbacks, [])
            host.start_tile.reset_mock()
            MainWindow._start_startup_tiles(host)
            host._closing = True
            callbacks.pop(0)()
            host.start_tile.assert_not_called()
            self.assertEqual(callbacks, [])

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

    def test_offline_tiles_clear_state_without_reentrant_paint_delivery(self):
        window = MainWindow([], [], layout_id='single', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.resize(900, 600)
        class Paints(QObject):
            def __init__(self):
                super().__init__()
                self.seen = []
            def eventFilter(self, watched, event):
                if (event.type() == QEvent.Paint and isinstance(watched, QWidget)
                        and (watched is window or window.isAncestorOf(watched))):
                    self.seen.append(type(watched).__name__)
                return False
        paints = Paints()
        try:
            window.show()
            self.app.processEvents()
            tile = window.wall.tiles[0]
            tile.room = {'room_id': 'fixture:offline', 'live': True}
            tile.set_video_active(True)
            tile.set_buffering(True)
            self.app.processEvents()
            self.app.installEventFilter(paints)
            for _ in range(3):
                tile.set_offline()
            self.assertEqual(paints.seen, [], 'Offline initialization must not synchronously paint the window')
            self.assertFalse(tile.room['live'])
            self.assertFalse(tile._player_active)
            self.assertFalse(tile._buffering)
            self.assertIsNone(tile._cover_source)
            self.assertTrue(tile.cover.isVisible())
            self.app.processEvents()
            self.assertTrue(paints.seen, 'Queued clearing must still be painted on the next event-loop turn')
            self.assertEqual(tile.cover.text(), '已下播')
        finally:
            self.app.removeEventFilter(paints)
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

    def test_wall_hover_shows_controls_before_native_enter_and_keeps_idle_hiding(self):
        window = MainWindow([], [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        window.move(-10000, -10000)
        window.show()
        self.app.processEvents()
        first, second = window.wall.visible_tiles()[:2]
        try:
            timer = window._wall_control_hover.timer
            self.assertEqual(timer.timerType(), Qt.PreciseTimer)
            self.assertLess(timer.interval(), 16)
            with patch('ddm.tile_controls.QCursor') as cursor, \
                    patch.object(window, 'isActiveWindow', return_value=True) as active:
                for tile in (first, second):
                    tile._normal_hover_active = False
                    tile.set_controls_visible(False)
                self.assertFalse(first._control_hover_timer.isActive())
                cursor.pos.return_value = first.mapToGlobal(first.video.geometry().center())
                active.return_value = False
                QTest.qWait(75)
                self.assertFalse(first.controls.isVisible())
                active.return_value = True
                QTest.qWait(75)
                self.assertTrue(first.controls.isVisible())

                first._control_last_move -= first.CONTROL_IDLE_SECONDS + 1
                QTest.qWait(100)
                self.assertFalse(first.controls.isVisible())
                self.assertTrue(first._control_hover_timer.isActive())

                cursor.pos.return_value = second.mapToGlobal(second.video.geometry().center())
                QTest.qWait(100)
                self.assertTrue(second.controls.isVisible())
                self.assertFalse(first._control_hover_timer.isActive())

                window.hide()
                self.assertFalse(window._wall_control_hover.timer.isActive())
        finally:
            window.close()
            self.app.processEvents()

    def test_video_mouse_move_wakes_controls_without_tile_enter_or_timer_tick(self):
        window = MainWindow([], [], layout_id='corner', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.move(-10000, -10000)
        window.show()
        self.app.processEvents()
        tile = window.wall.visible_tiles()[0]
        try:
            window._wall_control_hover.timer.stop()
            tile._normal_hover_active = False
            tile.set_controls_visible(False)
            point = tile.video.rect().center()
            global_point = tile.video.mapToGlobal(point)
            with patch('ddm.tile_controls.QCursor') as cursor:
                cursor.pos.return_value = global_point
                event = QMouseEvent(QEvent.MouseMove, QPointF(point), QPointF(global_point),
                                    Qt.NoButton, Qt.NoButton, Qt.NoModifier)
                self.app.sendEvent(tile.video, event)
            self.assertTrue(tile.controls.isVisible())
            self.assertTrue(tile.video.hasMouseTracking())
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
    def test_native_maximized_client_is_ready_before_first_paint(self):
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
                if msg.message == 0x000f and msg.hWnd == window.internalWinId():  # WM_PAINT
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
            # Window-position messages may precede Qt's size handling. Validate
            # the actual native paint frames while preserving normal geometry.
            for native, logical in capture.frames:
                self.assertTrue(all(abs(a-b) <= 1 for a,b in zip(native,logical)), capture.frames)
            self.assert_wall_filled(window)
            self.assertTrue(self.shows.frames)
            for bounds, area in self.shows.frames:
                self.assertEqual(bounds, area, 'A visible startup frame used stale pane geometry')
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
