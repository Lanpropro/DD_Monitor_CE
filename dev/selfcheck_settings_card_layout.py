"""Settings card orientation, existing preference, safe columns and isolated persistence."""
from pathlib import Path
import os
import json
import time
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_layout import SettingsColumns, SettingsSection
from ddm.settings_material import apply_properties, normalize
from ddm.settings_material_editor import SettingsMaterialEditor

if sys.argv[1:] == ['--portrait-worker']:
    from ddm import dialogs, settings_process
    original_dialog = dialogs.SettingsDialog

    class ProbeDialog(original_dialog):
        def showEvent(self, event):
            super().showEvent(event)
            self._probe_ready = True
            QTimer.singleShot(20, self.report)

        def event(self, event):
            result = super().event(event)
            if (event.type() == QEvent.DynamicPropertyChange
                    and event.propertyName() == b'settings_portrait'
                    and getattr(self, '_probe_ready', False)):
                QTimer.singleShot(20, self.report)
            return result

        def report(self):
            print(settings_process.PREFIX + json.dumps(dict(
                kind='layout-probe', portrait=bool(self.property('settings_portrait')),
                columns=self.general_page.sections.columns,
                geometry=self.frameGeometry().getRect(),
                preference=self.settings()['settings_card_layout'])), flush=True)

    dialogs.SettingsDialog = ProbeDialog
    raise SystemExit(settings_process.run_worker())

APP = QApplication.instance() or QApplication([])


def settle():
    for _ in range(4):
        APP.processEvents()


def dispose(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class SettingsCardLayoutTests(unittest.TestCase):
    def root_with_columns(self, *, respect_preference=True):
        root = QWidget()
        root.setAttribute(Qt.WA_DontShowOnScreen)
        root.setStyleSheet(theme.qss())
        root.box = QVBoxLayout(root)
        root.box.setContentsMargins(0, 0, 0, 0)
        columns = SettingsColumns(root, respect_preference=respect_preference)
        root.box.addWidget(columns)
        for key in ('first', 'second'):
            card = SettingsSection(key)
            text = QLabel('测试卡片内容')
            text.setWordWrap(True)
            card.grid.addWidget(text, 0, 0)
            columns.add_section(key, card)
        root.resize(1180, 850)
        root.show()
        settle()
        self.addCleanup(lambda: dispose(root) if isValid(root) else None)
        return root, columns

    def test_old_single_column_preference_and_three_existing_editor_choices(self):
        self.assertEqual(normalize({'settings_card_layout': 'vertical'})['settings_card_layout'], 'vertical')
        self.assertEqual(normalize({'settings_card_layout': 'horizontal'})['settings_card_layout'], 'horizontal')
        self.assertEqual(normalize({'settings_card_layout': 'invalid'})['settings_card_layout'], 'auto')
        editor = SettingsMaterialEditor({'settings_card_layout': 'vertical'})
        self.addCleanup(dispose, editor)
        self.assertEqual([editor.card_layout.itemData(n) for n in range(editor.card_layout.count())],
                         ['auto', 'vertical', 'horizontal'])
        self.assertEqual([editor.card_layout.itemText(n) for n in range(editor.card_layout.count())],
                         ['自动', '单列', '双列'])
        self.assertEqual(editor.values()['settings_card_layout'], 'vertical')
        editor.card_layout.setCurrentIndex(2)
        self.assertEqual(editor.values()['settings_card_layout'], 'horizontal')
        editor.reset()
        self.assertEqual(editor.values()['settings_card_layout'], 'auto')

    def test_auto_prioritizes_portrait_when_only_window_height_changes(self):
        root, columns = self.root_with_columns()
        self.assertEqual(columns.columns, 2)
        before_width = columns.width()
        root.resize(root.width(), 1400)
        settle()
        self.assertEqual(columns.width(), before_width)
        self.assertEqual(columns.columns, 1)
        root.resize(root.width(), 850)
        settle()
        self.assertEqual(columns.columns, 2)

    def test_main_portrait_context_drives_wide_settings_without_changing_preference(self):
        root, columns = self.root_with_columns()
        self.assertGreater(root.width(), root.height())
        self.assertEqual(columns.columns, 2)
        root.setProperty('settings_portrait', True)
        settle()
        self.assertEqual(columns.columns, 1, 'Portrait host must override a wide settings shell in auto mode')
        self.assertEqual(root.property('settings_card_layout'), None)
        apply_properties(root, {'settings_card_layout': 'horizontal'})
        settle()
        self.assertEqual(columns.columns, 2)
        apply_properties(root, {'settings_card_layout': 'auto'})
        settle()
        self.assertEqual(columns.columns, 1)
        root.setProperty('settings_portrait', False)
        settle()
        self.assertEqual(columns.columns, 2)

    def test_in_process_dialog_fits_narrow_portrait_work_area_and_controls(self):
        from ddm.settings_control import SettingsControl
        theme.configure_appearance({'appearance_font': theme.danmaku_font_family()})
        APP.setStyleSheet(theme.qss())
        owner = QWidget()
        owner.orientation = 'portrait'
        owner.settings = dict(config.DEFAULT_SETTINGS)
        owner.shortcuts = {}
        owner._available_update = None
        owner._plugin_update_offers = []
        owner.plugins = None
        owner._get_update_page = Mock()
        owner._remember_updates = Mock()
        owner.set_appearance = Mock()
        area = QRect(-800, 80, 540, 1280)
        with patch('ddm.settings_autosave_apply.bind_dialog'), \
                patch.object(SettingsControl, 'streamer_rooms', return_value={}), \
                patch.object(owner, 'screen', return_value=SimpleNamespace(availableGeometry=lambda: area)):
            dialog = SettingsControl(owner).create_settings_dialog(
                dialog_class=lambda *args, **kwargs: SettingsDialog(*args, preview=True, **kwargs))
        try:
            dialog.setAttribute(Qt.WA_DontShowOnScreen)
            dialog.show()
            settle()
            self.assertTrue(dialog.property('settings_portrait'))
            self.assertTrue(area.contains(dialog.frameGeometry()), dialog.frameGeometry())
            self.assertTrue(dialog.navigation.collapsed)
            self.assertEqual(dialog.general_page.sections.columns, 1)
            self.assertEqual(dialog.settings()['settings_card_layout'], 'auto')
            viewport = dialog.general_scroll.viewport()
            page = dialog.general_page
            toggle = page._checks['default_muted']
            for control in (toggle, page.volume_slider, page.poll_stepper,
                            page.compact_threshold_stepper, page.codec_editor):
                dialog.general_scroll.ensureWidgetVisible(control)
                settle()
                origin = control.mapTo(viewport, control.rect().topLeft())
                self.assertGreaterEqual(origin.x(), 0, control)
                self.assertLess(origin.x() + control.width() - 1, viewport.width(), control)
            dialog.general_scroll.ensureWidgetVisible(toggle)
            previous = toggle.isChecked()
            QTest.mouseClick(toggle, Qt.LeftButton)
            self.assertNotEqual(toggle.isChecked(), previous)
            dialog.set_host_layout(False, (0, 0, 1920, 1080))
            settle()
            self.assertFalse(dialog.navigation.collapsed)
            self.assertEqual(dialog.width(), 1200)
        finally:
            dispose(dialog)
            dispose(owner)

    def test_embedded_settings_receive_host_orientation_without_saving_it(self):
        from ddm.settings_host import SettingsHost
        root, columns = self.root_with_columns()
        client = Mock()
        session = SimpleNamespace(window=SimpleNamespace(orientation='portrait'), stack=root,
            values=lambda: {'settings_card_layout': 'auto'}, last_state=None, client=client,
            dialog=SimpleNamespace(confirm_button=Mock(), PAGES=[]))
        session.dialog.confirm_button.isEnabled.return_value = True
        session.dialog.confirm_button.isHidden.return_value = True
        session.dialog.confirm_button.text.return_value = ''
        SettingsHost.sync(session)
        settle()
        self.assertEqual(columns.columns, 1)
        self.assertTrue(client._send.call_args.args[0]['portrait'])
        self.assertEqual(client._send.call_args.args[0]['values'], {'settings_card_layout': 'auto'})
        session.window.orientation = 'landscape'
        SettingsHost.sync(session)
        settle()
        self.assertEqual(columns.columns, 2)
        self.assertFalse(client._send.call_args.args[0]['portrait'])

    def test_real_worker_snapshot_focus_and_host_state_follow_portrait(self):
        from ddm import settings_process
        owner = QWidget()
        owner.orientation = 'portrait'
        client = settings_process.SettingsProcess(owner)
        messages, errors = [], []
        client.received.connect(lambda message: messages.append(message) if message['kind'] == 'layout-probe' else None)
        client.failed.connect(errors.append)
        def wait_for(predicate):
            until = time.monotonic() + 15
            while not predicate() and not errors and time.monotonic() < until:
                APP.processEvents()
                time.sleep(.01)
            self.assertFalse(errors)
            self.assertTrue(predicate(), messages)
        command = (sys.executable, [str(Path(__file__).resolve()), '--portrait-worker'])
        with tempfile.TemporaryDirectory(prefix='ddm-portrait-worker-') as directory, \
                patch.object(config, 'REPO', directory), \
                patch.object(settings_process, 'worker_command', return_value=command), \
                patch.object(settings_process, '_allow_foreground'), \
                patch.object(owner, 'screen', return_value=SimpleNamespace(
                    availableGeometry=lambda: QRect(100, 50, 1920, 1080))):
            try:
                client.open(dict(config.DEFAULT_SETTINGS), {})
                wait_for(lambda: any(row['portrait'] and row['columns'] == 1 for row in messages))
                self.assertLess(messages[-1]['geometry'][2], 1040)
                owner.orientation = 'landscape'
                client.open(dict(config.DEFAULT_SETTINGS), {})
                wait_for(lambda: any(not row['portrait'] and row['columns'] == 2 for row in messages))
                self.assertEqual(messages[-1]['geometry'][2], 1200)
                before = len(messages)
                narrow = QRect(-800, 80, 700, 1280)
                client._send(dict(kind='host-state', portrait=True, work_area=narrow.getRect(),
                    values={'settings_card_layout': 'auto'}, material_background='',
                    save_enabled=True, action_visible=False, save_text='', marks={}))
                wait_for(lambda: any(row['portrait'] and row['columns'] == 1 for row in messages[before:]))
                self.assertTrue(narrow.contains(QRect(*messages[-1]['geometry'])))
                self.assertTrue(all(row['preference'] == 'auto' for row in messages))
            finally:
                client.finish()
                dispose(owner)

    def test_explicit_double_columns_keep_narrow_and_large_font_safety(self):
        root, columns = self.root_with_columns()
        root.resize(1180, 1400)
        apply_properties(root, {'settings_card_layout': 'horizontal'})
        settle()
        self.assertEqual(columns.columns, 2, 'User double-column choice overrides portrait auto')
        root.resize(640, 1000)
        settle()
        self.assertEqual(columns.columns, 1, 'Double-column preference must not clip narrow controls')
        root.resize(1180, 850)
        with patch.object(theme, 'FONT_CONTROL', 26):
            columns._arrange()
            self.assertEqual(columns.columns, 1)
        apply_properties(root, {'settings_card_layout': 'vertical'})
        settle()
        self.assertEqual(columns.columns, 1)
        for _key, card, _wide in columns.entries:
            self.assertTrue(root.rect().contains(card.mapTo(root, card.rect().bottomRight())))

    def test_nested_columns_ignore_override_but_still_follow_portrait_auto(self):
        root, columns = self.root_with_columns(respect_preference=False)
        apply_properties(root, {'settings_card_layout': 'vertical'})
        settle()
        self.assertEqual(columns.columns, 2)
        root.resize(root.width(), 1400)
        settle()
        self.assertEqual(columns.columns, 1)
        apply_properties(root, {'settings_card_layout': 'horizontal'})
        self.assertEqual(columns.columns, 1)

    def test_reparented_columns_detach_previous_resize_and_destroyed_signals(self):
        first, columns = self.root_with_columns()
        second = QWidget()
        second.setAttribute(Qt.WA_DontShowOnScreen)
        box = QVBoxLayout(second)
        columns.setParent(second)
        box.addWidget(columns)
        second.resize(1180, 1400)
        second.show()
        columns.show()
        settle()
        self.assertIs(columns._layout_window, second)
        self.assertEqual(columns.columns, 1)
        first.resize(1180, 850)
        dispose(first)
        self.assertIs(columns._layout_window, second)
        second.resize(1180, 850)
        settle()
        self.assertEqual(columns.columns, 2)
        columns.setParent(None)
        columns.hide()
        dispose(second)
        self.assertIsNone(columns._layout_window)
        dispose(columns)

    def test_dialog_choice_autosaves_roundtrips_and_hot_applies_same_property(self):
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        dialog.setAttribute(Qt.WA_DontShowOnScreen)
        dialog.resize(1400, 850)
        dialog.show()
        settle()
        changes = []
        dialog.auto_save.requested.connect(changes.append)
        dialog.auto_save.start()
        try:
            dialog.nav.setCurrentRow(1)
            settle()
            editor = dialog.appearance_page.material_editor
            editor.card_layout.setCurrentIndex(editor.card_layout.findData('horizontal'))
            settle()
            dialog.auto_save.flush()
            self.assertEqual(changes[-1]['settings']['settings_card_layout'], 'horizontal')
            self.assertEqual(dialog.property('settings_card_layout'), 'horizontal')
            self.assertEqual(dialog.settings()['settings_card_layout'], 'horizontal')
            dialog.auto_save.acknowledge()
            with tempfile.TemporaryDirectory(prefix='ddm-card-layout-') as directory, \
                    patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')), \
                    patch.dict(os.environ):
                os.environ.pop('DDM_NO_SAVE', None)
                config.save({'version': 'card-layout-fixture', 'settings': dialog.settings()}, raise_errors=True)
                saved = config.load()['settings']
            reopened = SettingsDialog(saved, {}, preview=True)
            try:
                self.assertEqual(reopened.property('settings_card_layout'), 'horizontal')
                reopened.appearance_page.material_editor.set_values(saved)
                self.assertEqual(reopened.appearance_page.material_editor.card_layout.currentData(), 'horizontal')
                reopened.set_material({'settings_card_layout': 'vertical'})
                self.assertEqual(reopened.property('settings_card_layout'), 'vertical')
                reopened.appearance_page.material_editor.reset()
                self.assertEqual(reopened.settings()['settings_card_layout'], 'auto')
            finally:
                dispose(reopened)
        finally:
            dispose(dialog)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(SettingsCardLayoutTests, __file__))
    unittest.main(verbosity=2)
