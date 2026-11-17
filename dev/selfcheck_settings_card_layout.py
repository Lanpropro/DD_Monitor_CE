"""Settings card orientation, existing preference, safe columns and isolated persistence."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_layout import SettingsColumns, SettingsSection
from ddm.settings_material import apply_properties, normalize
from ddm.settings_material_editor import SettingsMaterialEditor

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
