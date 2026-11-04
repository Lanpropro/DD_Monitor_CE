"""Embedded page routing restores the host, including after unload and window hiding."""
import os
from pathlib import Path
import sys
import unittest

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from ddm.plugins import PluginContext, PluginManager

APP = QApplication.instance() or QApplication([])


def settle():
    for _ in range(4):
        APP.processEvents()


class WorkspacePageTests(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        self.host._content = QWidget(self.host)
        QVBoxLayout(self.host).addWidget(self.host._content)
        self.wall = QLabel('original wall', self.host._content)
        self.hint = QLabel('empty state', self.host._content)
        layout = QVBoxLayout(self.host._content)
        layout.addWidget(self.wall)
        layout.addWidget(self.hint)
        self.hint.hide()
        self.manager = PluginManager(plugins_dir='unused', enabled=[])
        self.manager.window = self.host
        self.record = PluginContext(self.manager, 'record')
        self.match = PluginContext(self.manager, 'match')
        self.host.resize(1000, 700)
        self.host.show()
        settle()

    def tearDown(self):
        self.manager.unload()
        self.host.close()
        self.host.deleteLater()
        settle()

    def test_embedded_page_replaces_content_and_restores_visibility(self):
        page = QWidget()
        self.assertTrue(self.record.show_workspace(page))
        settle()
        self.assertFalse(page.isWindow())
        self.assertIs(page.parentWidget(), self.host._content)
        self.assertTrue(page.isVisible())
        self.assertTrue(self.wall.isHidden())
        self.host.resize(1200, 780)
        settle()
        self.assertEqual(page.geometry(), self.host._content.rect())
        page.close()
        settle()
        self.assertTrue(self.wall.isVisible())
        self.assertTrue(self.hint.isHidden())

    def test_switching_closes_previous_page_in_both_directions(self):
        record = QWidget()
        match = QWidget(self.host._content)
        self.record.show_workspace(record)
        self.match.show_workspace(match, manages_content=True)
        settle()
        self.assertTrue(record.isHidden())
        self.assertTrue(match.isVisible())
        self.record.show_workspace(record)
        settle()
        self.assertTrue(match.isHidden())
        self.assertTrue(record.isVisible())
        self.assertEqual(self.manager._workspace_pages.active[0], 'record')
        record.close()
        self.assertTrue(self.wall.isVisible())

    def test_parent_hide_preserves_active_page_and_unload_restores_base(self):
        page = QWidget()
        self.record.show_workspace(page)
        self.host.hide()
        settle()
        self.assertIsNotNone(self.manager._workspace_pages.active)
        self.host.show()
        settle()
        self.assertTrue(page.isVisible())
        self.host.hide()
        self.manager.unload()
        settle()
        self.assertTrue(page.isHidden())
        self.assertIsNone(self.manager._workspace_pages.active)
        self.host.show()
        settle()
        self.assertTrue(self.wall.isVisible())
        with self.assertRaises(RuntimeError):
            self.record.show_workspace(page)


if __name__ == '__main__':
    unittest.main()
