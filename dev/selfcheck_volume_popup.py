"""Offline Qt regression for compact volume controls; no accounts or playback."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QEnterEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QSlider, QVBoxLayout, QWidget

from ddm import theme
from ddm.widgets import Tile, VolumeButton

APP = QApplication.instance() or QApplication([])


class VolumePopupTests(unittest.TestCase):
    def setUp(self):
        theme.apply('dark')
        self.host = QWidget()
        self.host.setGeometry(160, 180, 360, 300)
        layout = QVBoxLayout(self.host)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tile = Tile({'room_id': 'volume-test', 'live': False, 'muted': False, 'volume': 42})
        layout.addWidget(self.tile)
        self.other = QPushButton('Other control')
        layout.addWidget(self.other)
        self.pointer = QPoint(-1000, -1000)
        self.cursor_patch = patch('PySide6.QtGui.QCursor.pos', side_effect=lambda: self.pointer)
        self.cursor_patch.start()
        self.host.show()
        APP.processEvents()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.host.close()
        self.host.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.processEvents()
        self.cursor_patch.stop()

    def hover_volume(self):
        button = self.tile.volume_button
        self.pointer = button.mapToGlobal(button.rect().center())
        QApplication.sendEvent(button, QEnterEvent(QPointF(button.rect().center()),
                                                  QPointF(), QPointF(self.pointer)))
        APP.processEvents()
        return self.tile.volume_menu

    def wait_pointer(self, point):
        self.pointer = point
        QTest.qWait(260)
        APP.processEvents()

    def test_narrow_click_toggles_mute_with_and_without_popup(self):
        changes = []
        self.tile.muteToggled.connect(lambda room, muted: changes.append(muted))
        QTest.mouseClick(self.tile.volume_button, Qt.LeftButton)
        self.assertTrue(self.tile.muted, 'compact click must still mute')
        self.assertTrue(self.tile.room['muted'])
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        QTest.mouseClick(self.tile.volume_button, Qt.LeftButton)
        self.assertFalse(self.tile.muted)
        self.assertTrue(popup.isVisible(), 'mute click must not dismiss the hovered slider')
        self.assertEqual(changes, [True, False])
        self.assertEqual(self.tile.volume, 42)

    def test_hover_opens_without_a_mouse_grab_or_focus_change(self):
        self.other.setFocus()
        APP.processEvents()
        focus = APP.focusWidget()
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible(), 'compact volume must open on hover')
        self.assertIsNone(APP.activePopupWidget())
        self.assertIsNone(QWidget.mouseGrabber())
        # Offscreen Qt activates even a plain WindowDoesNotAcceptFocus tool;
        # check actual focus retention using the Windows backend below.
        self.assertTrue(popup.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertEqual(popup.slider.focusPolicy(), Qt.NoFocus)
        if APP.platformName() == 'windows':
            self.assertIs(APP.focusWidget(), focus)
        self.assertIs(popup.parentWidget(), self.host)
        self.assertTrue(popup.testAttribute(Qt.WA_TranslucentBackground))
        self.assertLess(popup.grab().toImage().pixelColor(0, 0).alpha(), 30)

    def test_pointer_can_cross_gap_and_use_slider_then_leave(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        button = self.tile.volume_button
        anchor = QRect(button.mapToGlobal(QPoint()), button.size())
        gap = QPoint(anchor.center().x(), (popup.geometry().bottom() + anchor.top()) // 2)
        self.wait_pointer(gap)
        self.assertTrue(popup.isVisible(), 'the travel gap must stay open even for slow motion')
        self.wait_pointer(popup.geometry().center())
        self.assertTrue(popup.isVisible())
        changes = []
        self.tile.volumeChanged.connect(lambda room, level: changes.append(level))
        self.tile.vertical_volume.setValue(73)
        self.assertEqual((self.tile.volume, self.tile.room['volume'], self.tile.volume_slider.value()),
                         (73, 73, 73))
        self.assertEqual(changes, [73])
        self.wait_pointer(QPoint(popup.geometry().right() + 40, gap.y()))
        self.assertFalse(popup.isVisible(), 'leaving both controls must dismiss the slider')

    def test_wide_layout_uses_inline_slider_and_hides_popup(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        self.assertTrue(self.tile.volume_label.isHidden(), 'compact icon replaces the permanent number')
        self.host.resize(900, 500)
        APP.processEvents()
        self.assertTrue(self.tile.volume_slider.isVisible())
        self.assertTrue(self.tile.volume_label.isVisible())
        self.assertFalse(popup.isVisible())
        self.hover_volume()
        self.assertFalse(popup.isVisible())
        QTest.mouseClick(self.tile.volume_button, Qt.LeftButton)
        self.assertTrue(self.tile.muted)

    def test_popup_follows_owner_move_before_next_event_loop(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        before = popup.pos()
        anchor_before = self.tile.volume_button.mapToGlobal(QPoint())
        self.host.move(self.host.pos() + QPoint(57, 31))
        anchor_delta = self.tile.volume_button.mapToGlobal(QPoint()) - anchor_before
        delta = popup.pos() - before
        # Native fractional DPI rounds positions to physical pixels.
        self.assertLessEqual((delta - anchor_delta).manhattanLength(), 1,
                             'queued movement visibly lags behind')
        self.assertGreater(delta.x(), 50)
        self.assertGreater(delta.y(), 25)

    def test_outside_click_passes_through_and_closes_popup(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        clicks = []
        self.other.clicked.connect(lambda: clicks.append(True))
        QTest.mouseClick(self.other, Qt.LeftButton)
        self.assertFalse(popup.isVisible())
        self.assertEqual(clicks, [True])

    def test_deleting_tile_also_deletes_its_owned_tool_window(self):
        from shiboken6 import isValid
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        self.tile.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(popup), 'reparenting to the owner must not leak removed tiles')

    def open_settings(self):
        QTest.mouseClick(self.tile.danmaku_settings_button, Qt.LeftButton)
        APP.processEvents()
        popup = self.tile.danmaku_settings_menu
        self.assertTrue(popup.isVisible())
        return popup

    def test_danmaku_settings_follow_owner_and_keep_right_edge_alignment(self):
        popup = self.open_settings()
        button = self.tile.danmaku_settings_button
        right = button.mapToGlobal(QPoint(button.width(), 0)).x()
        self.assertLessEqual(abs(popup.geometry().right() + 1 - right), 1)
        before = popup.pos()
        anchor_before = button.mapToGlobal(QPoint())
        self.host.move(self.host.pos() + QPoint(57, 31))
        anchor_delta = button.mapToGlobal(QPoint()) - anchor_before
        self.assertLessEqual((popup.pos() - before - anchor_delta).manhattanLength(), 1)
        self.host.resize(480, 430)
        APP.processEvents()
        right = button.mapToGlobal(QPoint(button.width(), 0)).x()
        self.assertLessEqual(abs(popup.geometry().right() + 1 - right), 1)

    def test_danmaku_settings_stay_open_on_leave_and_outside_click_passes_through(self):
        popup = self.open_settings()
        self.assertIsNone(APP.activePopupWidget(), 'settings must not grab mouse like QMenu')
        self.assertIsNone(QWidget.mouseGrabber())
        self.wait_pointer(QPoint(-1000, -1000))
        self.assertTrue(popup.isVisible(), 'settings close on outside click, not pointer departure')
        clicks = []
        self.other.clicked.connect(lambda: clicks.append(True))
        QTest.mouseClick(self.other, Qt.LeftButton)
        self.assertFalse(popup.isVisible())
        self.assertEqual(clicks, [True])

    def test_danmaku_settings_sliders_keyboard_escape_and_advanced_action(self):
        popup = self.open_settings()
        changes = []
        popup.settingsChanged.connect(changes.append)
        slider = popup.controls['video_danmaku_size']
        before = slider.value()
        slider.setFocus()
        QTest.keyClick(slider, Qt.Key_Right)
        self.assertEqual(slider.value(), before + 1)
        self.assertEqual(changes[-1], {'video_danmaku_size': before + 1})
        QTest.keyClick(popup, Qt.Key_Escape)
        self.assertFalse(popup.isVisible())
        self.open_settings()
        advanced = []
        popup.advancedRequested.connect(lambda: advanced.append(True))
        popup.actions()[-1].trigger()
        self.assertEqual(advanced, [True])
        self.assertFalse(popup.isVisible(), 'advanced settings must dismiss the small picker')

    @unittest.skipUnless(APP.platformName() == 'windows', 'requires native focus routing')
    def test_danmaku_settings_keyboard_navigation_works_immediately_after_open(self):
        self.tile.danmaku_settings_button.setFocus()
        popup = self.open_settings()
        self.assertIs(APP.activeWindow(), popup)
        focus = APP.focusWidget()
        self.assertTrue(focus is popup or popup.isAncestorOf(focus))
        QTest.keyClick(focus, Qt.Key_Down)
        QTest.keyClick(APP.focusWidget(), Qt.Key_Down)
        self.assertIs(popup.activeAction(), popup.actions()[-1])

    def test_danmaku_settings_hide_with_tile_and_delete_with_anchor(self):
        from shiboken6 import isValid
        popup = self.open_settings()
        self.tile.hide()
        APP.processEvents()
        self.assertFalse(popup.isVisible())
        self.tile.show()
        APP.processEvents()
        self.open_settings()
        self.tile.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(popup))

    @unittest.skipUnless(APP.platformName() == 'windows', 'requires native Windows HWNDs')
    def test_native_drag_moves_popup_before_queued_qt_geometry(self):
        self.assert_native_drag(self.hover_volume())

    @unittest.skipUnless(APP.platformName() == 'windows', 'requires native Windows HWNDs')
    def test_native_danmaku_settings_drag_preserves_right_alignment(self):
        self.assert_native_drag(self.open_settings())

    def assert_native_drag(self, popup):
        import ctypes
        from ctypes import wintypes
        follower = popup._native_follow
        user32 = follower.user32
        user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def rect(handle):
            value = wintypes.RECT()
            self.assertTrue(user32.GetWindowRect(handle, ctypes.byref(value)))
            return value

        try:
            user32.SendMessageW(follower.owner_hwnd, 0x231, 0, 0)
            self.assertTrue(follower.dragging)
            owner_before, popup_before = rect(follower.owner_hwnd), rect(follower.popup_hwnd)
            self.wait_pointer(QPoint(-1000, -1000))
            self.assertTrue(popup.isVisible(), 'owner drag must suspend hover dismissal')
            user32.SetWindowPos(follower.owner_hwnd, None, owner_before.left + 48,
                                owner_before.top + 32, 0, 0, 0x15)
            moved = rect(follower.popup_hwnd)
            self.assertEqual(moved.left - popup_before.left, 48)
            self.assertLessEqual(abs(moved.top - popup_before.top - 32), 1,
                                 'allow one physical pixel for fractional DPI anchor rounding')
        finally:
            user32.SendMessageW(follower.owner_hwnd, 0x232, 0, 0)
        self.assertFalse(follower.dragging)
        popup.hide()
        self.assertFalse(follower.installed)

    def test_open_tool_pickers_keep_fullscreen_controls_and_cursor_visible(self):
        from ddm.fullscreen_cursor import FullscreenCursor
        self.host._fullscreen_tile = self.tile
        self.host.settings = {'fullscreen_auto_hide_controls': True}
        self.host.isActiveWindow = lambda: True
        cursor = FullscreenCursor(self.host)
        try:
            for open_picker in (self.hover_volume, self.open_settings):
                popup = open_picker()
                self.pointer = self.tile.video.mapToGlobal(self.tile.video.rect().center())
                cursor._position = self.pointer
                cursor._last_move = 0
                cursor.update_cursor()
                self.assertFalse(cursor.hidden, 'tool pickers must suspend fullscreen idle hiding')
                self.assertTrue(self.tile.bottom.isVisible())
                popup.hide()
        finally:
            cursor.stop()

    def test_plugin_interaction_keeps_fullscreen_controls_visible_with_tool_pickers(self):
        from ddm import plugins as api
        from ddm.fullscreen_cursor import FullscreenCursor
        from PySide6.QtWidgets import QLineEdit

        class ActiveControl(api.TileControl):
            def __init__(self, context):
                super().__init__(QLineEdit(context.parent), minimum_width=90)

            def interaction_active(self):
                return True

        manager = api.PluginManager()
        self.host.resize(900, 500)
        manager.register_tile_control('test', 'active', ActiveControl)
        manager.attach_tile(self.tile)
        APP.processEvents()
        self.host._fullscreen_tile = self.tile
        self.host.settings = {'fullscreen_auto_hide_controls': True}
        self.host.isActiveWindow = lambda: True
        cursor = FullscreenCursor(self.host)
        try:
            self.assertTrue(self.tile.plugin_interaction_active())
            for point in (self.tile.video.mapToGlobal(self.tile.video.rect().center()),
                          QPoint(-1000, -1000)):
                self.pointer = point
                cursor._position = point
                cursor._last_move = 0
                cursor.update_cursor()
                self.assertFalse(cursor.hidden, 'plugin interaction must suspend idle hiding')
                self.assertTrue(self.tile.bottom.isVisible())
                self.assertFalse(getattr(self.tile, '_fullscreen_controls_hidden', False))
        finally:
            cursor.stop()
            manager.unload()

    @unittest.skipUnless(APP.platformName() == 'windows', 'requires native Windows HWNDs')
    def test_native_screen_clamping_does_not_accumulate_drag_drift(self):
        import ctypes
        from ctypes import wintypes
        from ddm.native_popup import _MonitorInfo, _WindowPos
        popup = self.hover_volume()
        follower = popup._native_follow

        def dispatch(kind, position=None):
            message = wintypes.MSG()
            message.hWnd, message.message = follower.owner_hwnd, kind
            if position is not None:
                message.lParam = ctypes.addressof(position)
            follower.nativeEventFilter('windows_generic_MSG', ctypes.addressof(message))

        dispatch(0x231)
        origin = follower.origin
        try:
            proposal = _WindowPos()
            proposal.flags = 1  # SWP_NOSIZE
            proposal.x, proposal.y = -500, -500
            dispatch(0x46, proposal)
            value = wintypes.RECT()
            follower.user32.GetWindowRect(follower.popup_hwnd, ctypes.byref(value))
            owner_rect = wintypes.RECT(-500, -500, -500 + origin[4], -500 + origin[5])
            monitor = follower.user32.MonitorFromRect(ctypes.byref(owner_rect), 2)
            info = _MonitorInfo()
            info.size = ctypes.sizeof(info)
            self.assertTrue(follower.user32.GetMonitorInfoW(monitor, ctypes.byref(info)))
            self.assertGreaterEqual(value.left, info.work.left)
            self.assertGreaterEqual(value.top, info.work.top)
            self.assertLessEqual(value.right, info.work.right)
            self.assertLessEqual(value.bottom, info.work.bottom)
            proposal.x, proposal.y = origin[0] + 32, origin[1] + 24
            dispatch(0x46, proposal)
            follower.user32.GetWindowRect(follower.popup_hwnd, ctypes.byref(value))
            self.assertEqual(value.left, origin[2] + 32)
            self.assertLessEqual(abs(value.top - origin[3] - 24), 1)
        finally:
            dispatch(0x232)

    def test_escape_owner_hide_and_tile_hide_close_popup(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        QTest.keyClick(self.host, Qt.Key_Escape)
        self.assertFalse(popup.isVisible())
        self.hover_volume()
        self.tile.hide()
        APP.processEvents()
        self.assertFalse(popup.isVisible())
        self.tile.show()
        APP.processEvents()
        self.hover_volume()
        self.host.hide()
        self.assertFalse(popup.isVisible())

    def test_layout_move_reanchors_popup_and_stays_on_screen(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        self.host.resize(480, 420)
        APP.processEvents()
        button = self.tile.volume_button
        self.assertLess(popup.geometry().bottom(), button.mapToGlobal(QPoint()).y())
        self.assertLessEqual(abs(popup.geometry().center().x() -
                                 button.mapToGlobal(button.rect().center()).x()), 1)
        with patch('PySide6.QtGui.QScreen.availableGeometry', return_value=QRect(0, 0, 700, 500)):
            self.host.move(1, -self.tile.volume_button.mapTo(self.host, QPoint()).y() + 10)
            APP.processEvents()
            self.assertGreater(popup.y(), button.mapToGlobal(QPoint()).y(), 'flip below at top edge')
            self.assertTrue(QRect(0, 0, 700, 500).contains(popup.geometry()))

    def test_slider_drag_is_not_cancelled_when_pointer_leaves(self):
        popup = self.hover_volume()
        self.assertTrue(popup.isVisible())
        slider = self.tile.vertical_volume
        QTest.mousePress(slider, Qt.LeftButton, pos=slider.rect().center())
        self.wait_pointer(QPoint(popup.geometry().right() + 80, popup.y()))
        self.assertTrue(popup.isVisible(), 'keep active slider gestures alive')
        QTest.mouseRelease(slider, Qt.LeftButton, pos=slider.rect().center())
        self.wait_pointer(self.pointer)
        self.assertFalse(popup.isVisible())

    def test_wheel_unmutes_and_syncs_all_controls(self):
        button = self.tile.volume_button
        self.tile.set_muted(True)
        wheel = QWheelEvent(QPointF(button.rect().center()), QPointF(self.pointer), QPoint(),
                            QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(button, wheel)
        self.assertEqual(self.tile.volume, 47)
        self.assertEqual(self.tile.vertical_volume.value(), 47)
        self.assertFalse(self.tile.muted)
        self.assertFalse(self.tile.room['muted'])
        self.assertFalse(button.muted, 'wheel adjustment must update the mute icon')
        self.tile.set_volume(0)
        self.tile.set_muted(False)
        zero = button.grab().toImage()
        self.tile.set_muted(True)
        self.assertEqual(button.grab().toImage(), zero, 'zero volume also displays the speaker cross')

    def test_each_volume_slider_unmutes_and_notifies_after_setting_volume(self):
        menu = self.tile.build_menu()
        self.addCleanup(menu.deleteLater)
        menu_slider = menu.findChild(QSlider)
        self.assertIsNotNone(menu_slider)
        events = []
        self.tile.volumeChanged.connect(lambda room, level: events.append(('volume', level)))
        self.tile.muteToggled.connect(lambda room, muted: events.append(('mute', muted)))
        for name, slider in (('inline', self.tile.volume_slider),
                             ('popup', self.tile.vertical_volume), ('menu', menu_slider)):
            for level in (0, 73):
                with self.subTest(control=name, level=level):
                    self.tile.set_volume(42)
                    slider.blockSignals(True)
                    slider.setValue(42)
                    slider.blockSignals(False)
                    self.tile.set_muted(True)
                    events.clear()
                    slider.setValue(level)
                    self.assertFalse(self.tile.muted, 'manual volume changes must unmute')
                    self.assertFalse(self.tile.room['muted'])
                    self.assertFalse(self.tile.volume_button.muted)
                    self.assertEqual(self.tile.room['volume'], level)
                    self.assertEqual(self.tile.volume_slider.value(), level)
                    self.assertEqual(self.tile.vertical_volume.value(), level)
                    self.assertEqual(self.tile.volume_label.text(), str(level))
                    self.assertEqual(self.tile.vertical_volume_label.text(), str(level))
                    self.assertEqual(events, [('volume', level), ('mute', False)])
                    events.clear()
                    slider.setValue(level + 1)
                    self.assertEqual(events, [('volume', level + 1)],
                                     'already unmuted tiles must not emit another mute change')

    def test_restoring_volume_and_refreshing_controls_preserve_mute(self):
        self.tile.set_muted(True)
        changes = []
        self.tile.muteToggled.connect(lambda room, muted: changes.append(muted))
        self.tile.set_volume(17)
        self.tile.sync_audio_ui()
        self.assertTrue(self.tile.muted)
        self.assertTrue(self.tile.room['muted'])
        self.assertTrue(self.tile.volume_button.muted)
        self.assertEqual((self.tile.volume_slider.value(), self.tile.vertical_volume.value()),
                         (17, 17))
        self.assertEqual(changes, [])

    def test_icon_displays_three_distinct_volume_bands_in_compact_width(self):
        button = self.tile.volume_button
        self.assertLessEqual(button.width(), 30)
        images = []
        for level in (0, 1, 33, 34, 66, 67, 100):
            button.set_state(False, level)
            images.append(button.grab().toImage())
        self.assertEqual(images[1], images[2])
        self.assertEqual(images[3], images[4])
        self.assertEqual(images[5], images[6])
        self.assertNotEqual(images[0], images[1])
        self.assertNotEqual(images[1], images[3])
        self.assertNotEqual(images[3], images[5])
        for channel, text in ((VolumeButton.CHANNEL_LEFT, '声道：左'),
                              (VolumeButton.CHANNEL_RIGHT, '声道：右')):
            button.set_state(False, 42, channel)
            self.assertIn(text, button.toolTip())

    def test_volume_numbers_are_centered_inline_and_in_popup(self):
        self.host.resize(900, 500)
        APP.processEvents()
        for level in (0, 42, 100):
            self.tile.set_volume(level)
            for label in (self.tile.volume_label, self.tile.vertical_volume_label):
                self.assertEqual(label.text(), str(level))
                self.assertTrue(label.alignment() & Qt.AlignHCenter,
                                'one, two and three digit volumes must share the same center')
                self.assertTrue(label.alignment() & Qt.AlignVCenter)

    def test_hidden_pickers_do_not_filter_unrelated_application_events(self):
        from ddm.anchored_popup import AnchoredPopupMixin
        original = AnchoredPopupMixin.eventFilter
        deliveries = []

        def observed(popup, watched, event):
            if watched is self.other:
                deliveries.append(popup)
            return original(popup, watched, event)

        with patch.object(AnchoredPopupMixin, 'eventFilter', observed):
            QApplication.sendEvent(self.other, QEvent(QEvent.User))
        self.assertEqual(deliveries, [], 'many hidden tiles must not amplify every Qt event')


if __name__ == '__main__':
    unittest.main()
