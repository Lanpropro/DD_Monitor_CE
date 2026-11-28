"""Recording plugin hooks are lazy, parent-owned and available to the worker shell."""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
from ddm.config import DEFAULT_SETTINGS
from ddm.dialogs import SettingsDialog
from ddm.plugin_types import Plugin
from ddm.plugins import PluginContext, PluginManager
from ddm.settings_process import HOST_PAGES
from ddm.settings_host import SettingsHost

APP = QApplication.instance() or QApplication([])


class RecordingPluginSettingsTests(unittest.TestCase):
    def test_managed_recording_preferences_lock_the_native_page_and_release_ownership(self):
        host = QMainWindow()
        host.state = {}
        host.settings = dict(DEFAULT_SETTINGS, recording_dir='original')
        host.current_state = lambda: {'settings': dict(host.settings)}
        host._sync_recording_switch = lambda: None
        host._sync_replay_scope = lambda: None
        manager = PluginManager(window=host, enabled=[])
        owner = PluginContext(manager, 'editor')
        other = PluginContext(manager, 'other')
        dialog = SettingsDialog(host.settings, {}, host, plugin_manager=manager, preview=True)
        try:
            self.assertTrue(dialog.recording_page.directory.isEnabled())
            owner.set_recording_settings_managed(True)
            with self.assertRaisesRegex(RuntimeError, '其他插件'):
                other.set_recording_settings_managed(True)
            locked = dialog.recording_page
            self.assertTrue(locked.managed)
            self.assertFalse(locked.management_card.isHidden())
            self.assertTrue(locked.management_button.isHidden())
            self.assertFalse(locked.directory.isEnabled())
            editor = owner.create_recording_preferences_editor(host)
            editor.directory.setText('plugin-path')
            with patch('ddm.recording_preferences.config.save', side_effect=OSError('save failed')):
                self.assertFalse(editor.flush())
            self.assertEqual(host.settings['recording_dir'], 'original')
            with patch('ddm.recording_preferences.config.save') as save:
                self.assertTrue(editor.flush())
                self.assertEqual(save.call_args.args[0]['settings']['recording_dir'], 'plugin-path')
            self.assertEqual(locked.directory.text(), 'plugin-path')
            manager.unload()
            self.assertTrue(dialog.recording_page.directory.isEnabled())
            self.assertTrue(dialog.recording_page.management_card.isHidden())
            self.assertEqual(dialog.recording_page.directory.text(), 'plugin-path')
            editor.directory.setText('inactive')
            self.assertTrue(editor.flush())
            self.assertEqual(host.settings['recording_dir'], 'plugin-path')
        finally:
            dialog.deleteLater()
            host.deleteLater()

    def test_recording_shortcut_waits_for_autosave_and_closes_before_opening(self):
        host = QMainWindow()
        host.settings = dict(DEFAULT_SETTINGS)
        manager = PluginManager(window=host, enabled=[])
        owner = PluginContext(manager, 'ddcut_replay')
        dialog = SettingsDialog(host.settings, {}, host, plugin_manager=manager, preview=True)
        opened = []
        plugin = Plugin()
        plugin.context = owner
        plugin.name = 'DDCut'
        plugin.open_managed_recording_settings = lambda: opened.append(dialog.isVisible())
        manager.plugins.append(plugin)
        try:
            owner.set_recording_settings_managed(True)
            dialog.nav.setCurrentRow(dialog.PAGE_INDEX['recording'])
            dialog.show()
            page = dialog.recording_page
            self.assertEqual(page.management_title.text(), '录制设置已由「DDCut」接管')
            self.assertTrue(page.management_button.isVisible())
            dialog.auto_save.start()
            dialog.auto_save.pending = {'settings': {}}
            QTest.mouseClick(page.management_button, Qt.LeftButton)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(opened, [])
            dialog.auto_save.acknowledge()
            QTest.qWait(1)
            self.assertEqual(opened, [False])
            _, entry = manager.recording_settings_access.settings_entry()
            owner.set_recording_settings_managed(False)
            self.assertTrue(dialog.recording_page.management_card.isHidden())
            self.assertTrue(dialog.recording_page.directory.isEnabled())
            entry()
            self.assertEqual(opened, [False])
        finally:
            dialog.deleteLater()
            host.deleteLater()

    def test_isolated_settings_shortcut_waits_for_worker_result(self):
        messages = []
        opened = []
        session = SimpleNamespace(recording_settings_entry=None, pending_apply=None,
                                  client=SimpleNamespace(_send=messages.append))
        SettingsHost._close_for_recording_settings(session, lambda: opened.append(True))
        SettingsHost._close_for_recording_settings(session, lambda: opened.append(False))
        self.assertEqual(messages, [{'kind': 'host-cancel'}])
        self.assertEqual(opened, [])
        SettingsHost.handle(session, {'kind': 'result', 'accepted': False, 'host_saved': False})
        self.assertIsNone(session.recording_settings_entry)
        QTest.qWait(1)
        self.assertEqual(opened, [True])

    def test_full_view_keeps_host_controls_and_skips_legacy_extensions(self):
        class FullView(Plugin):
            def recording_settings_view(self, parent, controls):
                widget = QWidget(parent)
                layout = QVBoxLayout(widget)
                for control in controls.values():
                    layout.addWidget(control)
                return widget

            def recording_settings(self, parent):
                raise AssertionError('A replacement must not load extensions')

        dialog = SettingsDialog(dict(DEFAULT_SETTINGS), {}, preview=True,
                                plugin_manager=SimpleNamespace(plugins=[FullView()]))
        try:
            page = dialog.recording_page
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertIs(page.layout().itemAt(0).widget().findChild(type(page.directory)), page.directory)
            page.directory.setText('replacement-output')
            page.bitrate.setValue(7300)
            self.assertEqual(dialog.settings()['recording_dir'], 'replacement-output')
            self.assertEqual(dialog.settings()['recording_bitrate'], 7300)
            self.assertEqual(page.codec.currentData(), 'h264')
            page.reset()
            self.assertEqual(page.values()['recording_dir'], DEFAULT_SETTINGS['recording_dir'])
        finally:
            dialog.deleteLater()

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

    def test_refresh_rebuilds_presentation_with_unsaved_values_and_keeps_autosave(self):
        class SwitchableView(Plugin):
            enabled = True

            def recording_settings_view(self, parent, controls):
                if not self.enabled:
                    return None
                view = QWidget(parent)
                layout = QVBoxLayout(view)
                for control in controls.values():
                    layout.addWidget(control)
                return view

        plugin = SwitchableView()
        dialog = SettingsDialog(dict(DEFAULT_SETTINGS), {}, preview=True,
                                plugin_manager=SimpleNamespace(plugins=[plugin], enabled=None))
        requests = []
        dialog.auto_save.requested.connect(requests.append)
        try:
            dialog.nav.setCurrentRow(dialog.PAGE_INDEX['recording'])
            previous = dialog.recording_page
            dialog.auto_save.start()
            previous.bitrate.setValue(7100)
            plugin.enabled = False
            previous.presentation_refresh_requested.emit()
            previous.presentation_refresh_requested.emit()
            QCoreApplication.sendPostedEvents(None, QEvent.MetaCall)
            page = dialog.recording_page
            self.assertIsNot(page, previous)
            self.assertIs(dialog.stack.currentWidget(), page)
            self.assertIs(page.layout().itemAt(0).widget(), page.scroll)
            self.assertTrue(page.scroll.isAncestorOf(page.directory))
            self.assertEqual(page.bitrate.value(), 7100)
            self.assertEqual(page.codec.currentData(), 'h264')

            page.segment_minutes.setValue(25)
            dialog.auto_save.flush()
            self.assertEqual(requests[-1]['settings']['recording_bitrate'], 7100)
            self.assertEqual(requests[-1]['settings']['recording_segment_minutes'], 25)
            dialog.auto_save.acknowledge()
            page.bitrate.setValue(7900)
            self.assertTrue(dialog.auto_save.timer.isActive())
            plugin.enabled = True
            page.presentation_refresh_requested.emit()
            QCoreApplication.sendPostedEvents(None, QEvent.MetaCall)
            replaced = dialog.recording_page
            self.assertIsNot(replaced, page)
            self.assertEqual(replaced.values()['recording_bitrate'], 7900)
            self.assertEqual(dialog.settings()['recording_segment_minutes'], 25)
            self.assertIs(dialog.stack.currentWidget(), replaced)
        finally:
            dialog.auto_save.stop()
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
