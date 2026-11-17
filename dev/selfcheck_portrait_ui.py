"""Portrait presentation with synthetic rooms only; no accounts, plugins or media."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QBoxLayout, QMenu, QWidget
from ddm import motion, theme
from ddm.widgets import Sidebar
from ddm.window_layout import WindowLayout

APP = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')


def settle():
    for _ in range(6):
        APP.processEvents()


class PortraitUiTests(unittest.TestCase):
    def setUp(self):
        self.animation = patch.object(motion, 'enabled', return_value=False)
        self.animation.start()
        self.host = QWidget()
        self.host.setStyleSheet(theme.qss())
        self.host._root_layout = QBoxLayout(QBoxLayout.LeftToRight, self.host)
        self.host._root_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar = self.host.sidebar = Sidebar([
            dict(room_id=str(i), uname=f'示例主播{i}', live=i % 2 == 0) for i in range(12)],
            auto_compact=False)
        self.host._content = QWidget()
        self.layout = WindowLayout(self.host)
        self.layout.build_arrangement('landscape')
        self.host.resize(1200, 850)
        self.host.show()
        settle()

    def tearDown(self):
        self.sidebar.workspace_controls.popup.hide()
        self.host.close()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.animation.stop()

    def portrait(self, width):
        self.layout.build_arrangement('portrait')
        self.sidebar._sync_bar_gaps()
        self.host.resize(width, 1000)
        settle()

    def test_compact_header_keeps_essential_access_in_both_collapse_states(self):
        previous = dict(theme._preferences)
        self.addCleanup(theme.configure_appearance, previous)
        for font_size, width in ((13, 480), (13, 720), (13, 1000), (20, 480), (20, 720), (20, 1000), (13, 480)):
            theme.configure_appearance({'appearance_font_size': font_size})
            self.host.setStyleSheet(theme.qss())
            self.portrait(width)
            for collapsed in (False, True):
                self.sidebar.set_collapsed(collapsed, animate=False)
                settle()
                self.assertEqual(self.host.width(), width,
                                 (width, self.sidebar.minimumSizeHint(), self.sidebar._bar_row.minimumSizeHint()))
                self.assertLessEqual(self.sidebar.height(), (60 if collapsed else 210) + max(0, font_size - 13) * 2)
                self.assertTrue(self.sidebar.navigation.rail.isHidden())
                for widget in (self.sidebar.notification_button, self.sidebar.account_row,
                               self.sidebar.workspace_controls.launcher, self.sidebar.settings_button,
                               self.sidebar.toggle_button, self.sidebar.navigation.manage_button):
                    self.assertTrue(widget.isVisible(), (width, collapsed, widget.accessibleName()))
                    self.assertTrue(self.sidebar.rect().contains(widget.mapTo(
                        self.sidebar, widget.rect().bottomRight())), (width, collapsed, widget.geometry()))
                self.assertEqual(self.sidebar._head_scroll.isVisible(), collapsed)
                self.assertEqual(self.sidebar.scroll.isVisible(), not collapsed)
                self.assertFalse(self.sidebar._bar_right.isVisible())

    def test_landscape_restores_control_identity_parents_styles_and_signals(self):
        sidebar = self.sidebar
        controls = [sidebar.search, sidebar.account_row, sidebar.layout_button,
                    sidebar.picture_in_picture_button, sidebar.notification_button,
                    sidebar.appearance_button, sidebar.settings_button, sidebar.refresh_button,
                    sidebar.navigation.add_button, sidebar.navigation.manage_button,
                    sidebar.navigation.filters, sidebar.workspace_controls.launcher]
        baseline = [(widget, widget.parentWidget(), widget.objectName(), widget.size()) for widget in controls]
        clicks = []
        sidebar.settingsRequested.connect(lambda: clicks.append('settings'))
        sidebar.pictureInPictureRequested.connect(lambda: clicks.append('pip'))
        for width in (480, 720, 1000):
            self.portrait(width)
            sidebar.settings_button.click()
            sidebar.picture_in_picture_button.click()
            self.layout.build_arrangement('landscape')
            self.host.resize(1200, 850)
            settle()
            for widget, parent, name, size in baseline:
                self.assertIs(widget.parentWidget(), parent, widget.accessibleName())
                self.assertEqual(widget.objectName(), name)
                self.assertEqual(widget.size(), size, widget.accessibleName())
            self.assertFalse(sidebar.scroll.horizontal_only)
            self.assertTrue(sidebar.navigation.rail.isVisible())
            self.assertEqual(sidebar._layout.indexOf(sidebar.navigation.filters),
                             sidebar._layout.indexOf(sidebar.search) + 1)
        self.assertEqual(clicks, ['settings', 'pip'] * 3)

    def test_follow_filter_scroll_search_and_overflow_keep_existing_actions(self):
        self.portrait(480)
        sidebar, nav = self.sidebar, self.sidebar.navigation
        self.assertTrue(sidebar.scroll.horizontal_only)
        self.assertGreater(sidebar.scroll.horizontalScrollBar().maximum(), 0)
        nav.live_button.click()
        self.assertEqual(len(sidebar.visible_items()), 6)
        sidebar.search.setText('zhubo2')
        self.assertEqual(len(sidebar.visible_items()), 1)
        sidebar.search.clear()
        nav.all_button.click()
        self.assertEqual(len(sidebar.visible_items()), 12)
        sidebar.set_collapsed(True, animate=False)
        settle()
        self.assertGreater(sidebar._head_scroll.horizontalScrollBar().maximum(), 0)
        sidebar.focus_search()
        settle()
        self.assertFalse(sidebar.collapsed)
        self.assertTrue(sidebar.search.isVisible())
        self.assertTrue(sidebar.search.hasFocus())
        called = []
        sidebar.addRoomClicked.connect(lambda: called.append('add'))
        sidebar.pictureInPictureRequested.connect(lambda: called.append('pip'))
        nav.manage_button.click()
        settle()
        actions = {action.text(): action for action in nav.menu.actions()}
        self.assertTrue({'添加直播间…', '导入关注…', '切换卡片／列表', '布局预设', '画中画'} <= actions.keys())
        actions['添加直播间…'].trigger()
        actions['画中画'].trigger()
        self.assertEqual(called, ['add', 'pip'])
        nav.menu.close()

    def test_anonymous_and_synthetic_account_keep_the_original_entry(self):
        self.portrait(480)
        sidebar = self.sidebar
        logins = []
        sidebar.loginRequested.connect(lambda: logins.append(True))
        sidebar.account_row.clicked.emit()
        self.assertEqual(logins, [True])
        sidebar.set_account('本地示例账号', uid='fixture')
        for collapsed in (False, True):
            sidebar.set_collapsed(collapsed, animate=False)
            settle()
            self.assertTrue(sidebar.account_row.isVisible())
            self.assertLessEqual(sidebar.account_row.width(), 38)
            menu = QMenu(sidebar)
            menu.addAction('本地账号入口')
            with patch.object(menu, 'exec', return_value=None) as execute, \
                    patch.object(sidebar, 'account_menu', return_value=menu):
                sidebar.account_row.clicked.emit()
            execute.assert_called_once()
            menu.deleteLater()

    def test_orientation_only_repositions_existing_empty_video_surfaces(self):
        from ddm.wall_widgets import WallGrid
        old = self.host._content
        self.host._root_layout.removeWidget(old)
        old.deleteLater()
        wall = self.host._content = WallGrid([], layout_id='portrait_main2')
        self.host._root_layout.addWidget(wall, 1)
        surfaces = [(tile, tile.video, tile.video.parentWidget()) for tile in wall.tiles]
        preset = wall.layout_id
        parent = wall.parentWidget()
        for width in (480, 720, 1000):
            self.portrait(width)
            self.assertIs(wall.parentWidget(), parent)
            self.assertEqual(wall.layout_id, preset)
            self.assertEqual(wall.tiles, [tile for tile, _video, _parent in surfaces])
            for tile, video, owner in surfaces:
                self.assertIs(tile.video, video)
                self.assertIs(video.parentWidget(), owner)
                self.assertFalse(tile._player_active)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(PortraitUiTests, __file__))
    else:
        unittest.main()
