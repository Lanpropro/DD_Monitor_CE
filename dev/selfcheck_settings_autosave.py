"""Automatic settings persistence and acknowledged close; isolated default data."""
import os
from pathlib import Path
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from ddm import config, theme
from ddm.dialogs import SettingsDialog
APP = None if '--worker' in sys.argv else QApplication.instance() or QApplication([])

class AutoSaveTests(unittest.TestCase):
    def setUp(self):
        self.dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        self.dialog._auto_save_enabled = True
        self.dialog.resize(1200, 800)
        self.dialog.show()
        APP.processEvents()
        self.requests = []
        self.fail = False
        self.automatic_ack = True
        self.dialog.auto_save.requested.connect(self.save)

    def save(self, changes):
        self.requests.append(deepcopy(changes))
        if self.automatic_ack:
            self.dialog.auto_save.acknowledge('fixture write failure' if self.fail else '')

    def tearDown(self):
        self.dialog.auto_save.active = False
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_no_footer_and_close_keeps_the_changed_values(self):
        texts = [button.text() for button in self.dialog.findChildren(QPushButton) if not button.isHidden()]
        self.assertNotIn('保存', texts)
        self.assertNotIn('取消', texts)
        self.assertTrue(self.dialog.window_header.isAncestorOf(self.dialog.reset_button))
        self.assertTrue(self.dialog.confirm_button.isHidden())
        self.dialog.general_page._checks['default_muted'].setChecked(False)
        self.dialog.window_header.close_button.click()
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.requests, [{'settings': {'default_muted': False}}])
        self.assertFalse(self.dialog.auto_save.active)
        self.dialog.general_page.volume_slider.setValue(17)
        QTest.qWait(300)
        self.assertEqual(len(self.requests), 1)

    def test_slider_release_coalesces_changes_and_unchanged_controls_do_not_save(self):
        page = self.dialog.general_page
        self.dialog.auto_save.flush()
        self.assertFalse(self.requests)
        page.volume_slider.setSliderDown(True)
        page.volume_slider.setValue(17)
        page.volume_slider.setValue(19)
        self.dialog.auto_save.flush()
        self.assertFalse(self.requests)
        page.volume_slider.setSliderDown(False)
        self.assertEqual(self.requests, [{'settings': {'default_volume': 19}}])
        self.dialog.auto_save.flush()
        self.assertEqual(len(self.requests), 1)

    def test_inflight_edits_are_sent_after_ack_and_close_waits(self):
        self.automatic_ack = False
        page = self.dialog.general_page
        page._checks['default_muted'].setChecked(False)
        self.dialog.auto_save.flush()
        page.volume_slider.setValue(17)
        self.dialog.reject()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(len(self.requests), 1)
        self.dialog.auto_save.acknowledge()
        self.assertEqual(self.requests[-1], {'settings': {'default_volume': 17}})
        self.assertTrue(self.dialog.isVisible())
        self.dialog.auto_save.acknowledge()
        self.assertFalse(self.dialog.isVisible())

    def test_write_failure_stays_visible_and_retry_saves_then_closes(self):
        self.fail = True
        self.dialog.general_page.volume_slider.setValue(7)
        self.dialog.reject()
        self.assertTrue(self.dialog.isVisible())
        self.assertEqual(self.dialog.save_status.text(), '保存失败')
        self.assertTrue(self.dialog.retry_button.isVisible())
        self.fail = False
        self.dialog.retry_button.click()
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(len(self.requests), 2)

    def test_lazy_pages_and_reset_use_only_changed_settings(self):
        self.dialog.nav.setCurrentRow(2)
        APP.processEvents()
        self.dialog.auto_save.flush()
        self.assertFalse(self.requests)
        self.dialog.nav.setCurrentRow(0)
        self.dialog.general_page.volume_slider.setValue(7)
        self.dialog.auto_save.flush()
        self.dialog.reset_button.click()
        self.assertEqual(self.requests[-1], {'settings': {'default_volume': 40}})

    def test_preview_placeholder_pages_keep_explicit_actions_hidden(self):
        self.dialog.auto_save.active = False
        for index in (7, 8, 0):
            self.dialog.nav.setCurrentRow(index)
            APP.processEvents()
            self.assertTrue(self.dialog.confirm_button.isHidden())

    def test_explicit_migration_is_not_prepared_by_autosave(self):
        page = self.dialog.general_page
        from types import SimpleNamespace
        data = SimpleNamespace(target='fixture-destination', prepare=unittest.mock.Mock())
        self.dialog._loaded_pages[8] = SimpleNamespace(data_page=data, values=lambda: {})
        page.volume_slider.setValue(7)
        self.dialog.auto_save.flush()
        data.prepare.assert_not_called()
        self.dialog._loaded_pages.pop(8)

    def test_same_process_applies_without_closing(self):
        import tempfile
        from ddm import app as app_module, plugins
        from dev.selfcheck_tile_fullscreen import SilentPoller
        with tempfile.TemporaryDirectory() as root, \
                patch.object(config, 'REPO', root), \
                patch.object(config, 'CONFIG_PATH', str(Path(root) / 'config.json')), \
                patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(root) / 'plugins')), \
                patch.object(app_module, 'StatusPoller', SilentPoller), \
                patch.object(app_module, 'StatsPoller', SilentPoller), \
                patch('ddm.app.QTimer.singleShot', lambda *args: None), patch.dict(os.environ):
            os.environ.pop('DDM_NO_SAVE', None)
            window = app_module.MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit',
                    'settings_glass_enabled': True, 'settings_glass_opacity': 55, 'settings_glass_blur': 8}})
            dialog = window._create_settings_dialog()
            try:
                window.show()
                dialog.show()
                APP.processEvents()
                dialog.nav.setCurrentRow(1)
                with patch('ddm.motion.enabled', return_value=True):
                    window.set_appearance('light')
                self.assertTrue(window._theme_transition.overlays, 'The main appearance entry keeps its wave')
                for mode in ('dark', 'light', 'dark'):
                    dialog.appearance_page.buttons[mode].click()
                    self.assertEqual(window.settings['appearance_mode'], mode)
                    self.assertFalse(getattr(getattr(window, '_theme_transition', None), 'overlays', []),
                                     'Settings changes must repaint in place without a window-covering wave')
                    self.assertTrue(dialog.isVisible())
                material = dialog.appearance_page.material_editor
                self.assertEqual(set(material.controls), {'settings_no_shadows', 'settings_glass_enabled', 'settings_segment_motion'})
                material.controls['settings_no_shadows'].setChecked(True)
                dialog.auto_save.flush()
                self.assertEqual(window.settings['settings_glass_opacity'], 55)
                self.assertEqual(window.settings['settings_glass_blur'], 8)
                self.assertTrue(window.settings['settings_no_shadows'])
                self.assertTrue(dialog.property('settings_glass_enabled'))
                dialog.nav.setCurrentRow(0)
                dialog.general_page.volume_slider.setValue(17)
                dialog.auto_save.flush()
                self.assertEqual(window.settings['default_volume'], 17)
                self.assertTrue(dialog.isVisible())
                self.assertEqual(dialog.save_status.text(), '已保存')
                entry = dict(id='fixture', name='Fixture', version='1', description='', enabled=True,
                             status='已加载', reason='')
                with patch.object(window.plugins, 'catalog', return_value=[entry]), \
                        patch('ddm.online_ui.OnlinePage.start'):
                    dialog.nav.setCurrentRow(7)
                    dialog.plugin_page.checks['fixture'].setChecked(False)
                    dialog.auto_save.flush()
                self.assertEqual(window.plugins.enabled, set())
                self.assertFalse(getattr(window, '_closing', False))
                self.assertTrue(dialog.isVisible())
                self.assertTrue(dialog.confirm_button.isVisible())
                self.assertEqual(dialog.confirm_button.text(), '重启以应用')
                dialog.reject()
                self.assertEqual(window.settings['default_volume'], 17)
                self.assertEqual(config.load()['settings']['default_volume'], 17)
                reopened = window._create_settings_dialog()
                self.assertEqual(reopened.general_page.volume_slider.value(), 17)
                self.assertEqual(reopened.property('settings_glass_opacity'), 55)
                self.assertTrue(reopened.property('settings_no_shadows'))
                self.assertTrue(reopened.property('settings_glass_enabled'))
                reopened.deleteLater()
            finally:
                dialog.auto_save.active = False
                dialog.close()
                dialog.deleteLater()
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_checked_config_write_reports_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root, \
                patch.object(config, 'CONFIG_PATH', str(Path(root) / 'config.json')), \
                patch('ddm.config.io.open', side_effect=PermissionError('fixture denied')):
            previous = os.environ.pop('DDM_NO_SAVE', None)
            try:
                with self.assertRaises(PermissionError):
                    config.save({}, raise_errors=True)
                config.save({})
            finally:
                if previous is not None:
                    os.environ['DDM_NO_SAVE'] = previous

    def test_contributed_controls_send_the_effective_group(self):
        from PySide6.QtWidgets import QCheckBox
        page = self.dialog.general_page
        grid = page.layout().itemAt(1).layout()
        controls = []
        for name in ('fixture_domestic', 'fixture_global'):
            check = QCheckBox(name, page)
            check.setObjectName(name)
            grid.addWidget(check, grid.rowCount(), 0, 1, 2)
            controls.append(check)
        APP.processEvents()
        self.dialog.auto_save.adopt('plugin_controls', dict(fixture_domestic=False, fixture_global=False))
        controls[1].setChecked(True)
        self.dialog.auto_save.flush()
        self.assertEqual(self.requests[-1]['plugin_controls'], dict(fixture_domestic=False, fixture_global=True))

    def test_failed_value_can_be_reverted_and_still_written(self):
        self.fail = True
        self.dialog.general_page.volume_slider.setValue(7)
        self.dialog.auto_save.flush()
        self.fail = False
        self.dialog.general_page.volume_slider.setValue(40)
        self.dialog.auto_save.flush()
        self.assertEqual(self.requests[-1], {'settings': {'default_volume': 40}})
        self.assertEqual(self.dialog.save_status.text(), '已保存')

    def test_worker_close_waits_for_main_process_acknowledgement(self):
        import time
        from ddm import settings_process
        from PySide6.QtCore import QProcess
        client = settings_process.SettingsProcess()
        messages, persisted, visibility = [], [], []
        client.received.connect(messages.append)
        def persist(message):
            visibility.append(client.visible)
            persisted.append(message['changes'])
            QTimer.singleShot(40, lambda: client._send({'kind': 'auto-saved', 'error': ''}))
        client.autoSaveRequested.connect(persist)
        with patch.object(settings_process, 'worker_command', return_value=(sys.executable, [str(Path(__file__).resolve()), '--worker'])), \
                patch.object(settings_process, '_allow_foreground'):
            try:
                client.open(dict(config.DEFAULT_SETTINGS), {})
                until = time.monotonic() + 12
                while not any(message['kind'] == 'result' for message in messages) and time.monotonic() < until:
                    APP.processEvents()
                    QTest.qWait(10)
                self.assertTrue(any(message['kind'] == 'result' for message in messages), messages)
                self.assertEqual(persisted, [{'settings': {'default_volume': 17}}])
                self.assertEqual(visibility, [True])
                self.assertFalse(client.visible)
            finally:
                client.stop()
                until = time.monotonic() + 6
                while client.process.state() != QProcess.NotRunning and time.monotonic() < until:
                    APP.processEvents()
                    QTest.qWait(10)
                self.assertEqual(client.process.state(), QProcess.NotRunning)

if __name__ == '__main__':
    if '--worker' in sys.argv:
        from ddm import dialogs, settings_process
        class ExerciseDialog(SettingsDialog):
            def showEvent(self, event):
                super().showEvent(event)
                if not getattr(self, '_exercised', False):
                    self._exercised = True
                    QTimer.singleShot(0, self.exercise)
            def exercise(self):
                self.general_page.volume_slider.setValue(17)
                self.window_header.close_button.click()
        dialogs.SettingsDialog = ExerciseDialog
        raise SystemExit(settings_process.run_worker())
    theme.apply('dark')
    unittest.main()
