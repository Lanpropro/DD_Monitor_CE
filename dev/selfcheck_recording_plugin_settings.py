"""Recording plugin hooks are lazy, parent-owned and available to the worker shell."""
import os
from types import SimpleNamespace
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtWidgets import QApplication, QLabel
from ddm.config import DEFAULT_SETTINGS
from ddm.dialogs import SettingsDialog
from ddm.plugin_types import Plugin
from ddm.settings_process import HOST_PAGES
from ddm.settings_host import SettingsHost

APP = QApplication.instance() or QApplication([])


class RecordingPluginSettingsTests(unittest.TestCase):
    def test_lazy_hook_and_host_recording_values(self):
        class Extra(Plugin):
            name = 'Extra recording'
            context = SimpleNamespace(name='extra')

            def recording_settings(self, parent):
                calls.append(parent)
                return QLabel('Extra options', parent)

        calls = []
        extra = Extra()
        extra.context = SimpleNamespace(name='extra')
        dialog = SettingsDialog(dict(DEFAULT_SETTINGS), {}, preview=True,
            plugin_manager=SimpleNamespace(plugins=[Plugin(), extra]))
        try:
            self.assertFalse(calls)
            page = dialog.recording_page
            self.assertEqual(calls, [page])
            self.assertIs(page, dialog.recording_page)
            card = page.sections.section('plugin_extra')
            self.assertEqual(page.sections.entries[-1][0], 'plugin_extra')
            self.assertEqual(card.findChildren(QLabel)[-1].text(), 'Extra options')
            page.directory.setText('offline-recording-target')
            values = SettingsHost.values(SimpleNamespace(dialog=dialog))
            self.assertEqual(values['recording_dir'], 'offline-recording-target')
            self.assertEqual(HOST_PAGES[3], 'recording')
        finally:
            dialog.deleteLater()

    def test_without_plugins_has_only_host_sections(self):
        dialog = SettingsDialog(dict(DEFAULT_SETTINGS), {}, preview=True)
        try:
            self.assertEqual(len(dialog.recording_page.sections.entries), 3)
        finally:
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
