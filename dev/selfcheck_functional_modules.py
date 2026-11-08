"""Functional ownership boundaries; isolated Qt processes and temporary data only."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class FunctionalModulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from ddm import config, images, motion
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-functional-'))
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(images, 'REPO', directory))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            if isValid(widget):
                widget.close()
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def child(self, code):
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sidebar_domains_import_without_aggregate_or_main_window(self):
        for name in ('sidebar_items', 'sidebar_interaction'):
            self.child('import sys; import ddm.'+name+'; '
                "assert not {'ddm.app','ddm.widgets','ddm.sidebar_widgets'}.intersection(sys.modules)")

    def test_sidebar_collection_and_interaction_use_the_sidebar_as_only_owner(self):
        from ddm.sidebar_widgets import AppearanceButton, Sidebar
        sidebar, appearance = Sidebar([], auto_compact=False), AppearanceButton()
        self.widgets += [sidebar, appearance]
        for name in ('items_control', 'interaction_control'):
            self.assertEqual(vars(getattr(sidebar, name)), {'host': sidebar})
            self.assertFalse(hasattr(appearance, name))

    def test_sidebar_card_factory_add_remove_and_shared_room_data(self):
        from ddm import sidebar_widgets as module
        sidebar = module.Sidebar([], auto_compact=False)
        self.widgets.append(sidebar)
        room = {'room_id': 'fixture:1', 'uname': 'Fixture', 'live': False}
        with patch.object(module, 'NavItem', wraps=module.NavItem) as factory:
            self.assertEqual(sidebar.add_rooms([room, room]), [room])
        factory.assert_called_once()
        item = sidebar.items()[0]
        self.assertIs(item.room, room)
        self.assertIs(item.drop_host, sidebar)
        self.assertIs(item.parentWidget(), sidebar.list_box)
        self.assertEqual(sidebar.rooms(), [room])
        sidebar.remove_room(room)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(sidebar.items(), [])
        self.assertEqual(sidebar.rooms(), [])
        self.assertFalse(isValid(item))


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(FunctionalModulesTests, __file__))
    else:
        unittest.main(verbosity=2)
