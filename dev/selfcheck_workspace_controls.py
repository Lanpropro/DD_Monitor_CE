"""Offline navigation, plugin overflow, action ownership and orientation regression."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QAction, QFocusEvent
from PySide6.QtTest import QTest
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

    def add(self, key, text, priority=0):
        action = QAction(text, self.host)
        action.setCheckable(True)
        action.setIcon(self.host.style().standardIcon(QStyle.SP_DialogSaveButton))
        widget = QToolButton(self.host)
        widget.setDefaultAction(action)
        self.assertTrue(self.context.register_workspace_control(key, widget, priority=priority))
        settle()
        return widget, action

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
        bottom = [self.sidebar.layout_button, self.sidebar.clear_wall_button, self.sidebar.picture_in_picture_button,
                  self.sidebar.notification_button, self.sidebar.appearance_button,
                  self.sidebar.settings_button]
        for group in (top, plugins, bottom):
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

    def test_pin_limit_and_empty_pins_survive_reload(self):
        panel = self.sidebar.workspace_controls
        for i in range(6):
            self.add(str(i), f'工具{i}', i)
        panel.toggle_pin(('workspace-test', '2'))
        panel.toggle_pin(('workspace-test', '3'))
        panel.toggle_pin(('workspace-test', '4'))
        self.assertEqual(len(panel.pinned()), 4)
        saved = panel.pin_state()
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
            self.assertIs(self.sidebar.clear_wall_button.parentWidget(), self.sidebar._bar_row)
            self.assertTrue(self.sidebar.clear_wall_button.isVisible())
            self.assertEqual(self.sidebar.clear_wall_button.size().width(), 30)
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
        nav.density_button.click()
        self.assertFalse(self.sidebar.card_mode)
        nav.density_button.click()
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
        nav.menu.actions()[0].trigger()
        nav.menu.actions()[1].trigger()
        nav.menu.hide()
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
