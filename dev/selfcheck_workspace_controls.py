"""Offline navigation, plugin overflow, action ownership and orientation regression."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QAbstractAnimation, QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QAction, QEnterEvent, QFocusEvent, QInputDevice, QMouseEvent, QPointingDevice, QTransform, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QStyle, QToolButton, QVBoxLayout, QWidget
from ddm import continuous_corners as corners, motion, theme
from ddm.dock_feedback import REST, active, icon_color
from ddm.plugins import PluginContext, PluginManager
from ddm.sidebar_navigation import RAIL_WIDTH
from ddm.widgets import Sidebar

APP = QApplication.instance() or QApplication([])


def settle():
    for _ in range(5):
        APP.processEvents()


class WorkspaceControlTests(unittest.TestCase):
    def test_plugin_card_drag_shows_ghost_and_releases_owner_on_cancel(self):
        from unittest.mock import Mock
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QListView
        source=QListView(self.host)
        source.show()
        mime=QMimeData()
        mime.setData('application/x-test-card',b'fixture')
        pixmap=QPixmap(100,60)
        pixmap.fill(Qt.red)
        done=Mock()
        session=self.sidebar.drag_session
        try:
            self.assertTrue(self.context.start_sidebar_drag(source,mime,pixmap,QPoint(20,30),
                source.mapToGlobal(QPoint(20,30)),on_finished=done))
            self.assertTrue(session.ghost.isVisible())
            self.assertIs(session.area,source)
            self.assertEqual(session.plugin_owner,'workspace-test')
            self.assertFalse(self.context.start_sidebar_drag(source,mime,pixmap,QPoint(),QPoint(),on_finished=Mock()))
            self.context._clear_workspace_controls()
            done.assert_called_once()
            self.assertFalse(session.active)
            self.assertIsNone(session.ghost)
            self.assertIsNone(QWidget.mouseGrabber())
            self.assertIsNone(QWidget.keyboardGrabber())
        finally:
            session.cancel()
            source.deleteLater()

    def test_plugin_card_drag_source_hide_cancels_once(self):
        from unittest.mock import Mock
        from PySide6.QtCore import QMimeData
        from PySide6.QtGui import QPixmap
        source=QWidget(self.host)
        source.show()
        done=Mock()
        self.context.start_sidebar_drag(source,QMimeData(),QPixmap(20,20),QPoint(),QPoint(),on_finished=done)
        source.hide()
        self.context.cancel_sidebar_drag()
        done.assert_called_once()
        self.assertFalse(self.sidebar.drag_session.active)
        source.deleteLater()

    def test_sidebar_extension_search_keeps_follow_query_and_header(self):
        from unittest.mock import Mock
        self.sidebar.search.setText('示例主播1')
        widget, query = QWidget(), Mock()
        icon = self.host.style().standardIcon(QStyle.SP_MediaPlay)
        self.context.register_sidebar_page('order',widget,title='观看顺序',icon=icon,on_filter=query)
        pages = self.sidebar.plugin_pages
        pages.select(('workspace-test','order'))
        self.sidebar.search.setText('视频')
        query.assert_called_with('视频')
        self.assertEqual(self.sidebar.filter_text,'示例主播1')
        self.assertFalse(self.sidebar.navigation.add_button.isHidden())
        self.assertEqual(self.sidebar.navigation.title.text(),'关注')
        pages.select()
        self.assertEqual(self.sidebar.search.text(),'示例主播1')
        self.context.unregister_sidebar_page('order')
        widget.deleteLater()

    def test_sidebar_extension_switches_follow_and_cleans_only_its_owner(self):
        first, second = QWidget(), QWidget()
        icon = self.host.style().standardIcon(QStyle.SP_MediaPlay)
        self.context.register_sidebar_page('order', first, title='观看顺序', icon=icon)
        pages = self.sidebar.plugin_pages
        pages.add('other', 'other', second, '其他页面', icon)
        pages.select(('workspace-test','order'))
        settle()
        self.assertTrue(first.isVisible())
        self.assertTrue(self.sidebar.scroll.isHidden())
        self.assertFalse(self.sidebar.search.isHidden())
        self.assertEqual(self.sidebar.navigation.title.text(),'关注')
        self.sidebar.navigation.all_button.click()
        self.assertTrue(first.isHidden())
        self.assertFalse(self.sidebar.scroll.isHidden())
        self.context._clear_workspace_controls()
        self.assertNotIn(('workspace-test','order'),pages.entries)
        self.assertIn(('other','other'),pages.entries)
        self.assertIsNone(first.parentWidget())
        pages.remove_owner('other')
        first.deleteLater()
        second.deleteLater()

    def test_sidebar_extension_collapsed_and_portrait_restore_follow(self):
        widget = QWidget()
        icon = self.host.style().standardIcon(QStyle.SP_MediaPlay)
        self.context.register_sidebar_page('order',widget,title='观看顺序',icon=icon)
        pages = self.sidebar.plugin_pages
        pages.select(('workspace-test','order'))
        self.sidebar.set_collapsed(True,animate=False)
        self.assertIsNone(pages.current)
        self.assertTrue(widget.isHidden())
        self.sidebar.set_collapsed(False,animate=False)
        pages.select(('workspace-test','order'))
        self.sidebar.set_side('top')
        settle()
        self.assertIsNone(pages.current)
        self.assertTrue(widget.isHidden())
        self.sidebar.set_side('left')
        self.context.unregister_sidebar_page('order')
        widget.deleteLater()

    def setUp(self):
        self.host = QWidget()
        self.host.setAttribute(Qt.WA_DontShowOnScreen)
        self.host.setStyleSheet(theme.qss())
        rooms = [{'room_id': str(i), 'uname': f'示例主播{i}', 'live': i % 2 == 0}
                 for i in range(8)]
        self.sidebar = self.host.sidebar = Sidebar(rooms, auto_compact=False)
        QHBoxLayout(self.host).addWidget(self.sidebar)
        self.host.resize(900, 760)
        self.manager = PluginManager(window=self.host, plugins_dir='unused', enabled=[])
        self.context = PluginContext(self.manager, 'workspace-test')
        self.host.show()
        settle()

    def tearDown(self):
        self.manager.unload()
        self.sidebar.workspace_controls.popup.hide()
        self.host.close()
        self.host.deleteLater()
        settle()

    def add(self, key, text, priority=0, *, dock_motion=None):
        action = QAction(text, self.host)
        action.setCheckable(True)
        action.setIcon(self.host.style().standardIcon(QStyle.SP_DialogSaveButton))
        widget = QToolButton(self.host)
        if dock_motion is not None:
            widget.setProperty('dockMotion', dock_motion)
        widget.setDefaultAction(action)
        self.assertTrue(self.context.register_workspace_control(key, widget, priority=priority))
        settle()
        return widget, action

    def move_pointer(self, source, position):
        APP.sendEvent(source, QMouseEvent(QEvent.MouseMove, source.mapFromGlobal(position),
            position, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))

    def drag_icon(self, source, target, *, cancel=False):
        QTest.mousePress(source, Qt.LeftButton, pos=source.rect().center())
        position = target.mapToGlobal(QPoint(target.width()//2, target.height()-2))
        self.move_pointer(source, position)
        self.assertIsNotNone(self.sidebar.navigation.icon_drag.ghost)
        if cancel:
            QTest.keyClick(source, Qt.Key_Escape)
        QTest.mouseRelease(source, Qt.LeftButton, pos=source.mapFromGlobal(position))
        settle()

    def test_drag_plugin_icons_reorders_pins_without_triggering_actions(self):
        first, first_action = self.add('first', '第一项')
        second, second_action = self.add('second', '第二项')
        panel = self.sidebar.workspace_controls
        changes = []
        clicks = []
        panel.pinsChanged.connect(lambda: changes.append(panel.pin_state()))
        first.clicked.connect(lambda: clicks.append('first'))
        second.clicked.connect(lambda: clicks.append('second'))
        nav = self.sidebar.navigation
        nav.activate(first)
        self.drag_icon(first, second)
        self.assertEqual(panel.pinned(), [('workspace-test', 'second'), ('workspace-test', 'first')])
        self.assertLess(second.y(), first.y())
        self.assertEqual(len(changes), 1)
        self.assertEqual(clicks, [])
        self.assertFalse(first_action.isChecked())
        self.assertFalse(second_action.isChecked())
        self.assertIs(nav.active_button, first)
        self.assertIsNone(QWidget.mouseGrabber())
        self.assertIsNone(nav.icon_drag.ghost)
        QTest.mouseClick(first, Qt.LeftButton)
        self.assertEqual(clicks, ['first'])
        self.assertTrue(first_action.isChecked())

    def test_drag_tools_keeps_fixed_icons_spacing_and_survives_orientation(self):
        nav = self.sidebar.navigation
        source, target = self.sidebar.layout_button, self.sidebar.picture_in_picture_button
        changes = []
        clicks = []
        nav.orderChanged.connect(lambda: changes.append(nav.order_state()))
        source.clicked.connect(lambda: clicks.append('layout'))
        fixed_buttons = [self.sidebar.notification_button, self.sidebar.appearance_button, self.sidebar.settings_button]
        fixed = [button.y() for button in fixed_buttons]
        self.drag_icon(source, target)
        expected = [button for button in nav.movable_tools()]
        self.assertIs(expected[-1], source)
        self.assertEqual(clicks, [])
        self.assertEqual(len(changes), 1)
        self.assertEqual([button.y() for button in fixed_buttons], fixed)
        for group in (expected, fixed_buttons):
            positions = [button.mapTo(nav.rail, QPoint()).y() for button in group]
            self.assertEqual([b-a for a,b in zip(positions, positions[1:])], [40]*(len(group)-1))
        saved = nav.order_state()
        for collapsed in (True, False):
            self.sidebar.set_collapsed(collapsed, animate=False)
            settle()
            self.assertEqual(nav.movable_tools(), expected)
        self.sidebar.set_side('top')
        settle()
        self.sidebar.set_side('left')
        settle()
        self.assertEqual(nav.movable_tools(), expected)
        self.assertEqual(nav.order_state(), saved)
        fixed_after_orientation = [button.y() for button in fixed_buttons]
        nav.restore_order(['notification', 'layout', 'pip'])
        self.assertNotIn('notification', nav.order_state())
        self.assertEqual([button.y() for button in fixed_buttons], fixed_after_orientation)
        self.assertTrue(nav.fixed_divider.isVisible())
        self.assertGreater(nav.fixed_divider.y(), nav.movable_tools()[-1].mapTo(nav.rail, QPoint()).y()+34)
        self.assertLess(nav.fixed_divider.geometry().bottom(), fixed_buttons[0].mapTo(nav.rail, QPoint()).y())
        nav.restore_order(saved)
        self.assertEqual(nav.movable_tools(), expected)

    def test_fixed_icons_cannot_drag_and_cross_group_drops_cancel(self):
        first, _ = self.add('first', '第一项')
        second, _ = self.add('second', '第二项')
        nav = self.sidebar.navigation
        panel = self.sidebar.workspace_controls
        for button in (nav.follow_button, panel.launcher, self.sidebar.notification_button, self.sidebar.appearance_button,
                       self.sidebar.settings_button):
            QTest.mousePress(button, Qt.LeftButton, pos=button.rect().center())
            self.assertIsNone(nav.icon_drag.source)
            QTest.mouseRelease(button, Qt.LeftButton, pos=QPoint(-20, -20))
        before = panel.pin_state()
        tools = nav.movable_tools()
        self.drag_icon(first, self.sidebar.notification_button)
        self.assertEqual(panel.pin_state(), before)
        self.assertEqual(nav.movable_tools(), tools)
        self.drag_icon(self.sidebar.layout_button, second)
        self.assertEqual(panel.pin_state(), before)
        self.assertEqual(nav.movable_tools(), tools)
        self.assertTrue(nav.divider.isVisible())
        divider = nav.tools_divider
        self.assertTrue(divider.isVisible())
        self.assertGreater(divider.y(), second.mapTo(nav.rail, QPoint()).y()+second.height())
        self.assertLess(divider.geometry().bottom(), tools[0].mapTo(nav.rail, QPoint()).y())

    def test_drag_escape_outside_and_plugin_unload_release_input_without_saving(self):
        first, _ = self.add('first', '第一项')
        second, _ = self.add('second', '第二项')
        nav = self.sidebar.navigation
        panel = self.sidebar.workspace_controls
        changes = []
        panel.pinsChanged.connect(lambda: changes.append(True))
        self.drag_icon(first, second, cancel=True)
        self.assertEqual(panel.pinned()[0], ('workspace-test', 'first'))
        QTest.mousePress(first, Qt.LeftButton, pos=first.rect().center())
        outside = self.host.mapToGlobal(QPoint(self.host.width()-10, 20))
        self.move_pointer(first, outside)
        self.assertIsNotNone(nav.icon_drag.ghost)
        self.assertFalse(nav.icon_drag.marker.isVisible())
        QTest.mouseRelease(first, Qt.LeftButton, pos=first.mapFromGlobal(outside))
        self.assertIsNone(nav.icon_drag.source)
        QTest.mousePress(first, Qt.LeftButton, pos=first.rect().center())
        self.move_pointer(first, second.mapToGlobal(second.rect().center()))
        self.context.unregister_workspace_control('first')
        settle()
        self.assertIsNone(nav.icon_drag.source)
        self.assertIsNone(QWidget.mouseGrabber())
        self.assertFalse(changes)

    def test_pin_reorder_preserves_unavailable_plugins_and_restore_order_validation(self):
        first, _ = self.add('first', '第一项')
        second, _ = self.add('second', '第二项')
        panel = self.sidebar.workspace_controls
        panel.restore_pins([['workspace-test', 'first'], ['missing', 'entry'], ['workspace-test', 'second']])
        self.drag_icon(first, second)
        self.assertEqual(panel.pin_state(), [['workspace-test', 'second'], ['workspace-test', 'first'], ['missing', 'entry']])
        saved = panel.pin_state()
        panel.restore_pins([])
        panel.restore_pins(saved)
        self.assertLess(second.y(), first.y())
        nav = self.sidebar.navigation
        nav.restore_order(['notification', None, 'settings', 'notification', 'follow', 'pip'])
        self.assertEqual(nav.order_state(), ['pip'])
        self.assertIs(nav.movable_tools()[0], self.sidebar.picture_in_picture_button)
        nav.restore_order(None)
        self.assertEqual(nav.order_state(), [])

    def assert_global_buttons(self):
        for widget in (self.sidebar.layout_button, self.sidebar.clear_wall_button, self.sidebar.picture_in_picture_button,
                       self.sidebar.settings_button, self.sidebar.notification_button,
                       self.sidebar.appearance_button, self.sidebar.workspace_controls.launcher):
            self.assertTrue(widget.isVisible(), widget.accessibleName())
            self.assertTrue(self.sidebar.rect().contains(widget.mapTo(self.sidebar, QPoint(0, 0))))

    def open_page(self):
        self.host._content = QWidget(self.host)
        self.host.layout().addWidget(self.host._content, 1)
        wall = QWidget(self.host._content)
        QVBoxLayout(self.host._content).addWidget(wall)
        button, action = self.add('page', '录制切片示例')
        class Page(QWidget):
            allow_close = True

            def closeEvent(self, event):
                if not self.allow_close:
                    event.ignore()
                    return
                action.setChecked(False)
                super().closeEvent(event)
        page = Page()
        button.click()
        self.assertTrue(self.context.show_workspace(page))
        settle()
        return page, button, action, wall

    def test_follow_icon_returns_from_plugin_page_and_follow_browsing_keeps_selection(self):
        page, button, action, wall = self.open_page()
        nav = self.sidebar.navigation
        self.assertTrue(page.isVisible())
        self.assertTrue(wall.isHidden())
        QTest.mouseClick(self.sidebar.search, Qt.LeftButton)
        self.assertIs(nav.active_button, button)
        self.assertTrue(active(button))
        self.assertFalse(active(nav.follow_button))
        nav.follow_button.click()
        settle()
        self.assertTrue(page.isHidden())
        self.assertTrue(wall.isVisible())
        self.assertFalse(action.isChecked())
        self.assertIsNone(self.manager._workspace_pages.active)
        self.assertIs(nav.active_button, nav.follow_button)
        self.assertEqual(sum(active(entry) for entry in nav.buttons()), 1)

    def test_follow_icon_keeps_page_and_selection_if_close_is_refused(self):
        page, button, action, wall = self.open_page()
        page.allow_close = False
        self.sidebar.navigation.follow_button.click()
        settle()
        self.assertTrue(page.isVisible())
        self.assertTrue(wall.isHidden())
        self.assertTrue(action.isChecked())
        self.assertIs(self.sidebar.navigation.active_button, button)
        self.assertFalse(active(self.sidebar.navigation.follow_button))
        page.allow_close = True

    def test_current_rail_icon_closes_page_without_retriggering_action(self):
        page, button, action, wall = self.open_page()
        calls = []
        action.triggered.connect(calls.append)
        QTest.mouseClick(button, Qt.LeftButton)
        settle()
        self.assertTrue(page.isHidden())
        self.assertTrue(wall.isVisible())
        self.assertFalse(action.isChecked())
        self.assertEqual(calls, [])
        self.assertIs(self.sidebar.navigation.active_button, self.sidebar.navigation.follow_button)

    def test_current_rail_icon_and_function_center_respect_close_refusal(self):
        page, button, action, wall = self.open_page()
        page.allow_close = False
        calls = []
        action.triggered.connect(calls.append)
        QTest.keyClick(button, Qt.Key_Space)
        settle()
        self.assertTrue(page.isVisible())
        self.assertTrue(active(button))
        self.assertTrue(action.isChecked())
        panel = self.sidebar.workspace_controls
        panel._rows[('workspace-test', 'page')][1].click()
        settle()
        self.assertTrue(page.isVisible())
        self.assertTrue(wall.isHidden())
        self.assertEqual(calls, [])
        page.allow_close = True
        panel._rows[('workspace-test', 'page')][1].click()
        settle()
        self.assertTrue(page.isHidden())
        self.assertTrue(wall.isVisible())
        self.assertEqual(calls, [])

    def test_page_close_and_replacement_keep_navigation_in_sync(self):
        page, button, action, wall = self.open_page()
        page.close()
        settle()
        nav = self.sidebar.navigation
        self.assertTrue(wall.isVisible())
        self.assertIs(nav.active_button, nav.follow_button)
        button.click()
        self.context.show_workspace(page)
        other = PluginContext(self.manager, 'other-page')
        other_action = QAction('另一个功能页', self.host)
        other_action.setCheckable(True)
        other_button = QToolButton(self.host)
        other_button.setDefaultAction(other_action)
        other.register_workspace_control('page', other_button)
        other_page = QWidget()
        other_button.click()
        self.assertTrue(other.show_workspace(other_page))
        settle()
        self.assertTrue(page.isHidden())
        self.assertFalse(action.isChecked())
        self.assertTrue(other_page.isVisible())
        self.assertIs(nav.active_button, other_button)
        # A plugin may update its QAction after the page has closed.
        other_page.close()
        settle()
        self.assertTrue(other_action.isChecked())
        self.assertIs(nav.active_button, nav.follow_button)
        self.assertFalse(active(other_button))

    def test_card_area_and_global_actions_are_independent(self):
        self.assertEqual(self.sidebar.width(), theme.SIDEBAR_WIDTH + RAIL_WIDTH)
        self.assert_global_buttons()
        self.assertTrue(self.sidebar.normal_bar.isHidden())
        self.assertTrue(self.sidebar.tool_row.isHidden())
        self.assertTrue(self.sidebar.navigation.header.isVisible())
        self.assertEqual(self.sidebar.scroll.width(), theme.SIDEBAR_WIDTH-24)
        calls = []
        self.sidebar.pictureInPictureRequested.connect(lambda: calls.append('pip'))
        self.sidebar.settingsRequested.connect(lambda: calls.append('settings'))
        self.sidebar.clearWallRequested.connect(lambda: calls.append('clear'))
        self.sidebar.set_wall_rooms(['1'])
        self.sidebar.clear_wall_button.click()
        self.sidebar.picture_in_picture_button.click()
        self.sidebar.settings_button.click()
        self.assertEqual(calls, ['clear', 'pip', 'settings'])

    def test_rail_button_sizes_and_spacing_match_prototype(self):
        self.add('first', '第一项')
        self.add('second', '第二项')
        rail = self.sidebar.navigation.rail
        top = [self.sidebar.navigation.follow_button,
               self.sidebar.workspace_controls.launcher]
        plugins = [self.sidebar.workspace_controls.entries[i][1]
                   for i in self.sidebar.workspace_controls.pinned()]
        bottom = self.sidebar.navigation.movable_tools()
        fixed = [self.sidebar.notification_button, self.sidebar.appearance_button,
                  self.sidebar.settings_button]
        for group in (top, plugins, bottom, fixed):
            for button in group:
                self.assertEqual((button.width(), button.height()), (34, 34))
            positions = [button.mapTo(rail, QPoint()).y() for button in group]
            self.assertEqual([b-a for a,b in zip(positions, positions[1:])], [40]*(len(group)-1))
        divider = self.sidebar.navigation.divider
        self.assertTrue(divider.isVisible())
        self.assertEqual((divider.width(), divider.height()), (24, 2))
        self.assertGreater(divider.y(), top[-1].mapTo(rail, QPoint()).y()+34)
        self.assertLess(divider.geometry().bottom(), plugins[0].mapTo(rail, QPoint()).y())
        self.assertEqual(divider.geometry().center().x(), rail.rect().center().x())

    def test_dock_selection_tracks_follow_interaction_without_closing_plugin(self):
        nav = self.sidebar.navigation
        first, action = self.add('first', '第一个')
        first.click()
        self.assertIs(nav.active_button, first)
        self.assertTrue(active(first))
        self.assertFalse(active(nav.follow_button))
        QTest.mouseClick(self.sidebar.search, Qt.LeftButton)
        self.assertIs(nav.active_button, nav.follow_button)
        self.assertTrue(active(nav.follow_button))
        self.assertFalse(active(first))
        self.assertTrue(action.isChecked(), 'Visual navigation must not stop a running plugin')
        nav.activate(first)
        self.sidebar.workspace_controls.launcher.click()
        self.assertIs(nav.active_button, self.sidebar.workspace_controls.launcher)
        self.sidebar.workspace_controls.popup.hide()
        self.assertIs(nav.active_button, first)
        self.context.unregister_workspace_control('first')
        self.assertIs(nav.active_button, nav.follow_button)

    def test_registering_an_already_active_plugin_has_only_one_selected_icon(self):
        action = QAction('已开启功能', self.host)
        action.setCheckable(True)
        action.setChecked(True)
        button = QToolButton(self.host)
        button.setDefaultAction(action)
        self.context.register_workspace_control('already-active', button)
        settle()
        nav = self.sidebar.navigation
        self.assertIs(nav.active_button, button)
        self.assertEqual(sum(active(entry) for entry in nav.buttons()), 1)
        self.assertFalse(active(nav.follow_button))
        QTest.mouseClick(self.sidebar.search, Qt.LeftButton)
        self.assertTrue(action.isChecked())
        self.assertEqual(sum(active(entry) for entry in nav.buttons()), 1)
        self.assertFalse(active(button))
        self.assertEqual(corners._filter.values(button)['background'], 'transparent')
        button.click()
        self.assertFalse(action.isChecked(), 'Second plugin click must retain its original wall-return toggle')
        self.assertTrue(active(nav.follow_button))

    def test_function_center_toggle_does_not_replay_its_outside_press(self):
        panel = self.sidebar.workspace_controls
        nav = self.sidebar.navigation
        plugin, _action = self.add('first', '第一个')
        plugin.click()
        events = []
        class PopupTrace(QObject):
            def eventFilter(self, watched, event):
                if event.type() in (QEvent.Show, QEvent.Hide):
                    events.append((event.type(), watched.testAttribute(Qt.WA_NoMouseReplay)))
                return False
        trace = PopupTrace(panel.popup)
        panel.popup.installEventFilter(trace)
        for _ in range(4):
            panel.launcher.click()
            settle()
            self.assertTrue(panel.popup.isVisible())
            self.assertIs(nav.active_button, panel.launcher)
            point = panel.popup.mapFromGlobal(panel.launcher.mapToGlobal(panel.launcher.rect().center()))
            QTest.mouseClick(panel.popup, Qt.LeftButton, pos=point)
            settle()
            self.assertEqual(events[-2:], [(QEvent.Show, False), (QEvent.Hide, True)])
            self.assertFalse(panel.popup.isVisible())
            self.assertFalse(panel.launcher.isChecked())
            self.assertIs(nav.active_button, plugin)
            self.assertEqual(sum(active(entry) for entry in nav.buttons()), 1)
        panel.launcher.click()
        QTest.keyClick(panel.search, Qt.Key_Escape)
        settle()
        self.assertFalse(panel.popup.isVisible())
        self.assertIs(nav.active_button, plugin)

    def test_popup_focus_restoration_does_not_select_follow(self):
        panel = self.sidebar.workspace_controls
        nav = self.sidebar.navigation
        plugin, _action = self.add('first', '第一个')
        plugin.click()
        APP.setActiveWindow(self.host)
        plugin.setFocus(Qt.OtherFocusReason)
        self.sidebar.search.setFocus(Qt.OtherFocusReason)
        settle()
        self.assertTrue(self.sidebar.search.hasFocus())
        self.assertIs(nav.active_button, plugin)
        panel.launcher.click()
        APP.sendEvent(self.sidebar.search, QFocusEvent(QEvent.FocusIn, Qt.PopupFocusReason))
        self.assertIs(nav.active_button, panel.launcher)
        panel.popup.hide()
        self.assertIs(nav.active_button, plugin)
        APP.sendEvent(self.sidebar.search, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
        self.assertIs(nav.active_button, nav.follow_button)

    def test_semantic_hover_plays_once_and_interrupts_without_moving_buttons(self):
        nav = self.sidebar.navigation
        for button in (nav.follow_button, self.sidebar.workspace_controls.launcher,
                       self.sidebar.picture_in_picture_button, self.sidebar.notification_button,
                       self.sidebar.appearance_button, self.sidebar.settings_button):
            geometry = button.geometry()
            feedback = button._dock_feedback
            with patch.object(motion, 'enabled', return_value=True):
                feedback.keyboard = False
                feedback.hover(entering=True)
                feedback.hover_animation.setCurrentTime(84)
                self.assertNotEqual(feedback.pose, REST)
                self.assertFalse(button.grab().isNull())
                current = feedback.pose
                feedback.hover()
                self.assertEqual(feedback.pose, current)
                feedback.hover_animation.setCurrentTime(160)
                self.assertEqual(feedback.pose, REST)
                feedback.hover(entering=True)
                feedback.hover_animation.setCurrentTime(280)
                self.assertEqual(feedback.pose, REST)
                feedback.hover(entering=True)
                feedback.hover_animation.setCurrentTime(84)
                APP.sendEvent(button, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
                self.assertEqual(feedback.pose, REST)
                self.assertEqual(feedback.scale, 1)
                APP.sendEvent(button, QFocusEvent(QEvent.FocusOut))
            with patch.object(motion, 'enabled', return_value=False):
                feedback.hover(entering=True)
                self.assertEqual(feedback.pose, REST)
            self.assertEqual(button.geometry(), geometry)

    def test_pointer_focus_has_no_border_and_keyboard_still_activates(self):
        first, action = self.add('first', '第一个')
        QTest.mouseClick(first, Qt.LeftButton)
        self.assertTrue(action.isChecked())
        self.assertFalse(first.property('keyboardFocus'))
        self.assertEqual(corners._filter.values(first)['border'], 'none')
        APP.sendEvent(first, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
        self.assertTrue(first.property('keyboardFocus'))
        with patch.object(first, 'hasFocus', return_value=True):
            self.assertIn(theme.ACCENT, corners._filter.values(first)['border'])
        QTest.keyClick(first, Qt.Key_Space)
        self.assertFalse(action.isChecked())
        QTest.mouseClick(first, Qt.LeftButton)
        self.assertFalse(first.property('keyboardFocus'))
        self.assertEqual(corners._filter.values(first)['border'], 'none')

    def test_dock_feedback_preserves_geometry_and_respects_motion_and_keyboard(self):
        button = self.sidebar.navigation.follow_button
        feedback = button._dock_feedback
        geometry = button.geometry()
        with patch.object(motion, 'enabled', return_value=True):
            feedback.transition(1.1)
            feedback.animation.setCurrentTime(80)
            current = feedback.scale
            self.assertGreater(current, 1)
            self.assertLessEqual(current, 1.1)
            feedback.transition(1)
            self.assertEqual(feedback.animation.startValue(), current)
            feedback.animation.setCurrentTime(160)
            self.assertEqual(feedback.scale, 1)
            APP.sendEvent(button, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
            feedback.transition(1.1)
            self.assertEqual(feedback.scale, 1)
            APP.sendEvent(button, QFocusEvent(QEvent.FocusOut))
        with patch.object(motion, 'enabled', return_value=False):
            feedback.transition(1.1)
            self.assertEqual(feedback.scale, 1)
        self.assertEqual(button.geometry(), geometry)

    def test_rail_speed_lines_move_right_behind_stationary_icon(self):
        button, action = self.add('slide', 'F1 Play', dock_motion='slide-in-left')
        geometry = button.geometry()
        feedback = button._dock_feedback
        pos = QPointF(button.rect().center())
        global_pos = QPointF(button.mapToGlobal(pos.toPoint()))

        def enter(device):
            APP.sendEvent(button, QEnterEvent(pos, pos, global_pos, device))

        def red_pixels():
            frame = button.grab().toImage()
            return [x / frame.devicePixelRatio() for y in range(frame.height()) for x in range(frame.width())
                    if (color := frame.pixelColor(x, y)).red() > color.green() + 40
                    and color.red() > color.blue() + 30]

        mouse = QPointingDevice.primaryPointingDevice()
        touchscreen = QPointingDevice('Touch', 1, QInputDevice.DeviceType.TouchScreen,
                                      QPointingDevice.PointerType.Finger, QInputDevice.Capability.Position, 1, 0)
        with patch.object(motion, 'enabled', return_value=True):
            enter(touchscreen)
            self.assertEqual(feedback.streak_progress, 1)
            enter(mouse)
            self.assertEqual(feedback.streak_progress, 0)
            self.assertEqual(red_pixels(), [])
            feedback.hover_animation.setCurrentTime(40)
            first = red_pixels()
            self.assertTrue(first)
            transform = QTransform()
            feedback.transform(transform)
            self.assertTrue(transform.isIdentity())
            feedback.hover_animation.setCurrentTime(95)
            later = red_pixels()
            self.assertTrue(later)
            self.assertGreater(sum(later) / len(later), sum(first) / len(first))
            self.assertTrue(all(3 <= x < button.width() - 3 for x in first + later))
            current = feedback.streak_progress
            APP.sendEvent(button, QEvent(QEvent.Leave))
            self.assertAlmostEqual(feedback.streak_progress, current)
            enter(mouse)
            self.assertAlmostEqual(feedback.streak_progress, current)
            feedback.hover_animation.setCurrentTime(motion.CONTROL_FEEDBACK_MS)
            self.assertEqual(red_pixels(), [])
            enter(mouse)
            feedback.hover_animation.setCurrentTime(40)
            APP.sendEvent(button, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
            self.assertEqual(red_pixels(), [])
            APP.sendEvent(button, QFocusEvent(QEvent.FocusOut))
            QTest.keyClick(button, Qt.Key_Space)
            self.assertTrue(action.isChecked())
            APP.sendEvent(button, QFocusEvent(QEvent.FocusOut))
        with patch.object(motion, 'enabled', return_value=False):
            enter(mouse)
            self.assertEqual(red_pixels(), [])
            self.assertEqual(feedback.hover_animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(button.geometry(), geometry)

    def test_dock_selected_surface_and_icon_follow_both_themes(self):
        self.addCleanup(theme.apply, theme.mode())
        plugin, _action = self.add('first', '第一个')
        for mode, background, foreground in (('dark', 'TEXT1', 'BG'),
                                              ('light', 'ACCENT', '#ffffff')):
            theme.apply(mode)
            self.host.setStyleSheet(theme.qss())
            settle()
            for button in (self.sidebar.navigation.follow_button, plugin):
                self.sidebar.navigation.activate(button)
                self.assertEqual(corners._filter.values(button)['background'], getattr(theme, background))
                self.assertEqual(icon_color(button), theme.qcolor(getattr(theme, foreground, foreground)))
                image = button.grab().toImage()
                scale = image.devicePixelRatio()
                self.assertEqual(image.pixelColor(round(button.width()/2*scale), round(3*scale)).name(),
                                 theme.qcolor(getattr(theme, background)).name())

    def test_dock_hover_recovers_without_qt_enter_and_clears_on_miss(self):
        first, action = self.add('first', '插件入口')
        second, _ = self.add('second', '另一入口')
        clicked = QSignalSpy(first.clicked)
        nav = self.sidebar.navigation
        with patch('PySide6.QtGui.QCursor.pos') as cursor, \
                patch.object(QApplication, 'widgetAt') as hit:
            for button in (first, second, self.sidebar.layout_button):
                button.setAttribute(Qt.WA_UnderMouse, False)
                cursor.return_value = button.mapToGlobal(button.rect().center())
                hit.return_value = button
                self.sidebar._hover_sync_timer.timeout.emit()
                self.assertFalse(button.underMouse())
                self.assertEqual(icon_color(button), theme.qcolor(theme.ACCENT))
                self.assertEqual(corners._filter.values(button)['background'], theme.CONTENT_HOVER)
                image = button.grab().toImage()
                scale = image.devicePixelRatio()
                self.assertEqual(image.pixelColor(round(button.width() / 2 * scale), round(3 * scale)).name(),
                                 theme.qcolor(theme.CONTENT_HOVER).name())
                if button is not first:
                    self.assertEqual(icon_color(first), theme.qcolor(theme.TEXT2))
            layout_button = self.sidebar.layout_button
            layout_button.setAttribute(Qt.WA_UnderMouse, True)
            hit.return_value = None
            self.sidebar._hover_sync_timer.timeout.emit()
            self.assertEqual(icon_color(layout_button), theme.qcolor(theme.TEXT2))
            self.assertNotEqual(corners._filter.values(layout_button)['background'], theme.CONTENT_HOVER)
            layout_button.setAttribute(Qt.WA_UnderMouse, False)
            cursor.return_value = first.mapToGlobal(first.rect().center())
            hit.return_value = first
            self.sidebar._hover_sync_timer.timeout.emit()
            self.assertEqual(clicked.count(), 0)
            self.assertIs(nav.active_button, nav.follow_button)
            QTest.mouseClick(first, Qt.LeftButton)
            self.assertEqual(clicked.count(), 1)
            self.assertTrue(action.isChecked())

    def test_running_badge_survives_final_dock_tint_and_selected_surface(self):
        self.addCleanup(theme.apply, theme.mode())
        button, _action = self.add('running', '运行状态')
        for mode in ('dark', 'light'):
            theme.apply(mode)
            self.host.setStyleSheet(theme.qss())
            for selected in (True, False):
                self.sidebar.navigation.activate(button if selected else self.sidebar.navigation.follow_button)
                for running in (True, False):
                    button.setProperty('workspaceRunning', running)
                    button.update()
                    settle()
                    image = button.grab().toImage()
                    scale = image.devicePixelRatio()
                    pixel = image.pixelColor(round((button.width() - 6.5) * scale), round(6.5 * scale))
                    self.assertEqual(pixel == theme.qcolor(theme.SUCCESS), running, (mode, selected))

    def test_24_plugins_do_not_reduce_follow_height(self):
        panel = self.sidebar.workspace_controls
        before = self.sidebar.scroll.height()
        for i in range(24):
            self.add(str(i), f'插件功能 {i:02}', i)
        self.assertEqual(self.sidebar.scroll.height(), before)
        self.assertEqual(len(panel.pinned()), 2)
        self.assertEqual(sum(w.isVisible() for _p, w in panel.entries.values()), 2)
        panel.launcher.click()
        settle()
        self.assertTrue(panel.popup.isVisible())
        self.assertEqual(len(panel._rows), 24)
        self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 0)
        area = panel.popup.screen().availableGeometry()
        self.assertTrue(area.contains(panel.popup.frameGeometry()))
        self.assertLessEqual(panel.popup.width(), 352)
        self.assertEqual(self.sidebar.scroll.height(), before)
        panel.search.setText('功能 23')
        self.assertEqual(sum(not row.isHidden() for row, _b, _p in panel._rows.values()), 1)
        panel.search.setText('不存在')
        self.assertTrue(panel.empty.isVisible())
        QTest.keyClick(panel.search, Qt.Key_Escape)
        settle()
        self.assertFalse(panel.popup.isVisible())
        self.assertFalse(panel.launcher.isChecked())

    def test_function_search_supports_pinyin_and_keeps_action_order(self):
        first, first_action = self.add('subtitle', '字幕工具 42')
        first.setToolTip('实时翻译 · 小明 Example')
        self.add('recording', '录制助手')
        panel = self.sidebar.workspace_controls
        panel.launcher.click()
        settle()
        order = list(panel._rows)
        cases = [('字幕', {'subtitle'}), ('zimu', {'subtitle'}), ('ZM', {'subtitle'}),
                 ('ssfy', {'subtitle'}), ('XM', {'subtitle'}), ('EXAMPLE', {'subtitle'}),
                 ('42', {'subtitle'}), ('zimu 42 example', {'subtitle'}), ('lz', {'recording'}),
                 ('zm missing', set()), ('subtitle', set())]
        for query, expected in cases:
            panel.search.setText(query)
            self.assertEqual({key[1] for key, (row, _launch, _pin) in panel._rows.items()
                              if not row.isHidden()}, expected, query)
            self.assertEqual(list(panel._rows), order)
        panel.search.clear()
        self.assertTrue(all(not row.isHidden() for row, _launch, _pin in panel._rows.values()))
        self.assertFalse(first_action.isChecked(), 'Searching must not activate a function')
        self.assertIs(panel.entries[('workspace-test', 'subtitle')][1], first)

    def test_popup_uses_original_click_and_action_state(self):
        panel = self.sidebar.workspace_controls
        first, action = self.add('first', '第一个', 0)
        _second, other = self.add('second', '第二个', 1)
        clicks = []
        first.clicked.connect(lambda: clicks.append('original'))
        panel._rows[('workspace-test', 'first')][1].click()
        self.assertEqual(clicks, ['original'])
        self.assertTrue(action.isChecked())
        other.setChecked(True)
        self.assertFalse(panel._rows[('workspace-test', 'first')][1].isChecked())
        self.assertTrue(panel._rows[('workspace-test', 'second')][1].isChecked())
        action.setEnabled(False)
        self.assertFalse(panel._rows[('workspace-test', 'first')][1].isEnabled())

    def test_all_pins_and_empty_pins_survive_reload(self):
        panel = self.sidebar.workspace_controls
        for i in range(6):
            self.add(str(i), f'工具{i}', i)
        panel.toggle_pin(('workspace-test', '2'))
        panel.toggle_pin(('workspace-test', '3'))
        panel.toggle_pin(('workspace-test', '4'))
        panel.toggle_pin(('workspace-test', '5'))
        self.assertEqual(len(panel.pinned()), 6)
        saved = panel.pin_state()
        panel.restore_pins(saved)
        self.assertEqual(panel.pin_state(), saved)
        self.assertEqual(len(panel.pinned()), 6)
        self.context.unregister_workspace_control('2')
        self.assertIn(['workspace-test', '2'], panel.pin_state())
        self.add('2', '工具2', 2)
        self.assertEqual(panel.pin_state(), saved)
        self.assertIn(('workspace-test', '2'), panel.pinned())
        panel.restore_pins([])
        self.assertEqual(panel.pinned(), [])
        self.add('new', '新增插件', 9)
        self.assertEqual(panel.pin_state(), [])
        self.assertFalse(panel.isVisible())
        self.assertTrue(panel.launcher.isVisible())

    def test_many_pins_scroll_without_hiding_global_tools(self):
        panel = self.sidebar.workspace_controls
        follow_height = self.sidebar.scroll.height()
        controls = [self.add(str(i), f'工具{i}', i) for i in range(24)]
        panel.restore_pins([])
        for i in range(24):
            pin = panel._rows[('workspace-test', str(i))][2]
            self.assertTrue(pin.isEnabled())
            pin.click()
        settle()
        self.assertEqual(len(panel.pinned()), 24)
        self.assertEqual(self.sidebar.scroll.height(), follow_height)
        self.assert_global_buttons()
        scroll = self.sidebar.navigation.pin_scroll
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        scroll.verticalScrollBar().setValue(0)
        point = scroll.viewport().rect().center()
        APP.sendEvent(scroll.viewport(), QWheelEvent(point, scroll.viewport().mapToGlobal(point),
            QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        settle()
        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        last, action = controls[-1]
        scroll.ensureWidgetVisible(last, 0, 0)
        settle()
        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertTrue(scroll.viewport().rect().contains(last.mapTo(scroll.viewport(), last.rect().center())))
        QTest.mouseClick(last, Qt.LeftButton)
        self.assertTrue(action.isChecked())
        saved = panel.pin_state()
        self.sidebar.set_side('top')
        settle()
        self.sidebar.set_side('left')
        settle()
        self.assertEqual(panel.pin_state(), saved)
        self.assertEqual(len(panel.pinned()), 24)
        self.assert_global_buttons()

    def test_collapse_portrait_restore_and_selection_keep_global_access(self):
        panel = self.sidebar.workspace_controls
        self.add('record', '录制中心')
        for _ in range(3):
            for collapsed in (True, False):
                self.sidebar.set_collapsed(collapsed, animate=False)
                settle()
                self.assert_global_buttons()
                self.assertEqual(self.sidebar.width(), RAIL_WIDTH + (
                    theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH))
            self.sidebar.set_side('top')
            settle()
            self.assertTrue(self.sidebar.navigation.rail.isHidden())
            self.assertIs(panel.launcher.parentWidget(), self.sidebar._bar_row)
            for button in (self.sidebar.layout_button, self.sidebar.picture_in_picture_button):
                self.assertIs(button.parentWidget(), self.sidebar._bar_row)
                self.assertTrue(button.isVisible())
                self.assertEqual(button.size(), self.sidebar.settings_button.size())
                self.assertTrue(self.sidebar.rect().contains(button.mapTo(
                    self.sidebar, button.rect().bottomRight())))
            self.assertTrue(self.sidebar.clear_wall_button.isVisible())
            self.assertIs(self.sidebar.clear_wall_button.parentWidget(), self.sidebar._bar_row)
            for collapsed in (True, False):
                self.sidebar.set_collapsed(collapsed, animate=False)
                settle()
                self.assertTrue(panel.launcher.isVisible())
            self.sidebar.set_side('left')
            settle()
            self.assert_global_buttons()
            self.assertEqual(self.sidebar._layout.indexOf(self.sidebar.navigation.filters),
                             self.sidebar._layout.indexOf(self.sidebar.search)+1)
        self.sidebar.set_select_mode(True)
        settle()
        self.assert_global_buttons()
        self.assertTrue(self.sidebar.batch_bar.isVisible())

    def test_search_live_filter_and_density_preserve_order(self):
        nav = self.sidebar.navigation
        before = [room['room_id'] for room in self.sidebar.rooms()]
        nav.live_button.click()
        self.assertEqual(len(self.sidebar.visible_items()), 4)
        self.sidebar.search.setText('主播2')
        self.assertEqual(len(self.sidebar.visible_items()), 1)
        self.sidebar.search.clear()
        nav.all_button.click()
        self.assertEqual(len(self.sidebar.visible_items()), 8)
        calls = []
        self.sidebar.refreshRequested.connect(lambda: calls.append('refresh'))
        self.assertTrue(self.sidebar.batch_button.isVisible() and self.sidebar.refresh_button.isVisible())
        self.sidebar.refresh_button.click()
        self.assertEqual(calls, ['refresh'])
        self.sidebar.batch_button.click()
        self.assertTrue(self.sidebar.select_mode)
        self.sidebar.batch_button.click()
        self.assertFalse(self.sidebar.select_mode)

        def choose_density(label):
            nav.open_manage_menu()
            actions = {action.text(): action for action in nav.menu.actions()}
            self.assertTrue({'多选管理', '刷新关注状态'}.isdisjoint(actions))
            actions[label].trigger()
            nav.menu.close()

        choose_density('切换为列表')
        self.assertFalse(self.sidebar.card_mode)
        choose_density('切换为封面卡片')
        self.assertTrue(self.sidebar.card_mode)
        self.assertEqual([room['room_id'] for room in self.sidebar.rooms()], before)
        self.assertEqual(self.sidebar.scroll.width(), theme.SIDEBAR_WIDTH-24)
        self.sidebar.set_select_mode(True)
        self.sidebar.set_select_mode(False)
        self.assertTrue(self.sidebar.normal_bar.isHidden())
        self.assertTrue(self.sidebar.tool_row.isHidden())
        self.assert_global_buttons()

    def test_unpinned_button_without_action_retains_click_behavior(self):
        panel = self.sidebar.workspace_controls
        panel.restore_pins([])
        button = QToolButton(self.host)
        button.setText('独立按钮')
        calls = []
        button.clicked.connect(lambda: calls.append('clicked'))
        self.context.register_workspace_control('plain', button)
        panel._rows[('workspace-test', 'plain')][1].click()
        self.assertEqual(calls, ['clicked'])
        self.assertIs(self.sidebar.navigation.active_button, self.sidebar.navigation.follow_button)

    def test_menus_emit_existing_signals_and_store_route(self):
        calls = []
        self.sidebar.addRoomClicked.connect(lambda: calls.append('add'))
        self.sidebar.importFollowsClicked.connect(lambda: calls.append('import'))
        self.sidebar.pluginSettingsRequested.connect(lambda: calls.append('store'))
        nav = self.sidebar.navigation
        nav.open_add_menu()
        self.sidebar.import_button.click()
        self.sidebar.workspace_controls.store_button.click()
        self.assertEqual(calls, ['add', 'import', 'store'])

    def test_unregister_only_removes_owned_entries(self):
        self.add('first', '第一个')
        other = PluginContext(self.manager, 'other')
        widget = QToolButton(self.host)
        widget.setText('其他工具')
        other.register_workspace_control('entry', widget)
        self.context.unregister_workspace_control('first')
        settle()
        self.assertEqual(set(self.sidebar.workspace_controls.entries), {('other', 'entry')})
        self.manager.unload()
        settle()
        self.assertFalse(self.sidebar.workspace_controls.entries)
        with self.assertRaises(RuntimeError):
            self.context.register_workspace_control('late', QToolButton(self.host))


if __name__ == '__main__':
    unittest.main()
