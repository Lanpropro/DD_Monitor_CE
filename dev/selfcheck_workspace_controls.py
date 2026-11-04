"""Offline workspace placement, existing footer order and plugin ownership checks."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QStyle, QToolButton, QWidget
from ddm import theme
from ddm.plugins import PluginContext, PluginManager
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
        self.sidebar = self.host.sidebar = Sidebar([], auto_compact=False)
        QHBoxLayout(self.host).addWidget(self.sidebar)
        self.host.resize(900, 760)
        self.manager = PluginManager(window=self.host, plugins_dir='unused', enabled=[])
        self.context = PluginContext(self.manager, 'workspace-test')
        self.host.show()
        settle()

    def tearDown(self):
        self.manager.unload()
        settle()
        self.host.close()
        self.host.deleteLater()
        settle()

    def add(self, key, text, priority):
        action = QAction(text, self.host)
        action.setCheckable(True)
        action.setIcon(self.host.style().standardIcon(QStyle.SP_DialogSaveButton))
        widget = QToolButton(self.host)
        widget.setDefaultAction(action)
        self.assertTrue(self.context.register_workspace_control(key, widget, priority=priority))
        settle()
        return widget, action

    def assert_footer_order(self):
        box = self.sidebar._layout
        positions = [box.indexOf(widget) for widget in (self.sidebar.footer,
            self.sidebar.account_row, self.sidebar.tool_row, self.sidebar.normal_bar)]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(all(index >= 0 for index in positions))

    def assert_original_controls_visible(self):
        for widget in (self.sidebar.account_row, self.sidebar.layout_button,
                       self.sidebar.settings_button, self.sidebar.import_button, self.sidebar.add_button):
            self.assertTrue(widget.isVisible())

    def test_empty_priority_click_and_original_footer(self):
        panel = self.sidebar.workspace_controls
        self.assertFalse(panel.isVisible())
        match, _ = self.add('match', '比赛二路', 20)
        record, action = self.add('record', '录制切片', 10)
        self.assert_footer_order()
        self.assertEqual(panel.buttons.indexOf(record), 0)
        self.assertEqual(panel.buttons.indexOf(match), 1)
        calls = []
        action.toggled.connect(calls.append)
        record.click()
        self.assertEqual(calls, [True])
        self.assertTrue(self.sidebar.layout_button.isVisible())
        self.assertTrue(self.sidebar.settings_button.isVisible())
        self.assertTrue(self.sidebar.import_button.isVisible())
        self.assertTrue(self.sidebar.add_button.isVisible())
        self.assertLess(record.geometry().right(), match.geometry().left())
        self.assertLessEqual(match.geometry().right(), panel.row.width())

    def test_collapse_portrait_and_restore_keep_registered_entries(self):
        panel = self.sidebar.workspace_controls
        record, _ = self.add('record', '录制切片', 10)
        match, _ = self.add('match', '比赛二路', 20)
        for _ in range(3):
            self.sidebar.set_collapsed(True, animate=False)
            settle()
            self.assertTrue(record.isVisible() and match.isVisible())
            self.assertEqual(record.toolButtonStyle(), Qt.ToolButtonIconOnly)
            self.assertLess(record.geometry().bottom(), match.geometry().top())
            self.sidebar.set_collapsed(False, animate=False)
            settle()
            self.assert_footer_order()
            self.assertEqual(record.toolButtonStyle(), Qt.ToolButtonTextBesideIcon)
            self.sidebar.set_side('top')
            settle()
            self.assertIs(panel.parentWidget(), self.sidebar._bar_row)
            for collapsed in (True, False):
                self.sidebar.set_collapsed(collapsed, animate=False)
                settle()
                self.assertTrue(record.isVisible() and match.isVisible())
            self.sidebar.set_side('left')
            settle()
            self.assert_footer_order()

    def test_unregister_and_manager_unload_remove_only_owned_controls(self):
        panel = self.sidebar.workspace_controls
        self.add('record', '录制切片', 10)
        with self.assertRaises(ValueError):
            self.add('record', '重复', 10)
        other = PluginContext(self.manager, 'other')
        widget = QToolButton(self.host)
        widget.setText('其他工具')
        other.register_workspace_control('entry', widget)
        self.context.unregister_workspace_control('record')
        settle()
        self.assertEqual(set(panel.entries), {('other', 'entry')})
        self.manager.unload()
        settle()
        self.assertFalse(panel.entries)
        self.assertFalse(panel.isVisible())
        with self.assertRaises(RuntimeError):
            self.context.register_workspace_control('late', QToolButton(self.host))

    def test_footer_slide_can_reverse_from_current_height(self):
        self.add('record', '录制切片', 10)
        footer = self.sidebar.footer
        expanded = footer.height()
        with patch('ddm.motion.enabled', return_value=True):
            footer.toggle_button.click()
            self.assertTrue(footer.minimized)
            self.assertEqual(footer.animation.state(), QAbstractAnimation.Running)
            footer.animation.setCurrentTime(60)
            partial = footer.height()
            self.assert_original_controls_visible()
            self.assertLess(partial, expanded)
            self.assertGreater(partial, footer.HANDLE_HEIGHT)
            footer.restore_button.click()
            self.assertFalse(footer.minimized)
            self.assertEqual(footer.height(), partial)
            footer.animation.setCurrentTime(footer.animation.duration())
            settle()
            self.assertEqual(footer.height(), expanded)
            self.assertTrue(footer.restore_button.isHidden())
            footer.set_minimized(True)
            footer.animation.setCurrentTime(footer.animation.duration())
            settle()
            self.assertEqual(footer.height(), footer.HANDLE_HEIGHT)
            self.assertTrue(footer.body.isHidden())
            self.assertTrue(footer.restore_button.isVisible())
            self.assert_original_controls_visible()

    def test_reduced_motion_and_keyboard_toggle_without_sliding(self):
        self.add('record', '录制切片', 10)
        footer = self.sidebar.footer
        with patch('ddm.motion.enabled', return_value=False):
            footer.toggle_button.click()
            settle()
            self.assertEqual(footer.height(), footer.HANDLE_HEIGHT)
            self.assertEqual(footer.animation.state(), QAbstractAnimation.Stopped)
            footer.restore_button.click()
            settle()
        with patch('ddm.motion.enabled', return_value=True):
            QTest.keyClick(footer.toggle_button, Qt.Key_Space)
            settle()
            self.assertTrue(footer.minimized)
            self.assertEqual(footer.animation.state(), QAbstractAnimation.Stopped)
            QTest.keyClick(footer.restore_button, Qt.Key_Space)
            settle()
            self.assertFalse(footer.minimized)
            self.assertGreater(footer.height(), footer.HANDLE_HEIGHT)


if __name__ == '__main__':
    unittest.main()
