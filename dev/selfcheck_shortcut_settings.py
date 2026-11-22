"""Shortcut page filtering, compact layout and existing save contracts; offline Qt."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFontDatabase, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from ddm import theme
from ddm.dialogs import SettingsDialog
from ddm.settings_shortcuts import ShortcutSettingsPage
from ddm.shortcut_actions import SHORTCUT_ACTIONS, configured_shortcuts

APP = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')


def settle():
    for _ in range(3):
        APP.processEvents()


def dispose(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class ShortcutSettingsTests(unittest.TestCase):
    def page(self, values=None, width=1000):
        page = ShortcutSettingsPage(values or {})
        self.addCleanup(dispose, page)
        page.setStyleSheet(theme.qss())
        page.resize(width, 800)
        page.show()
        settle()
        return page

    def test_search_matches_chinese_pinyin_initials_english_and_current_binding_without_changing_data(self):
        page = self.page({'focus': 'Ctrl+K', 'record': ''})
        before = page.values()
        self.assertEqual(set(before), {item[0] for item in SHORTCUT_ACTIONS})
        for query, expected in (('全屏查看', 'focus'), ('quanpingchakan', 'focus'),
                                ('qpck', 'focus'), ('audio_cycle', 'audio_cycle'),
                                ('Ctrl+K', 'focus'), ('画中画 音量', 'pip_volume_up')):
            page.search.setText(query)
            settle()
            self.assertTrue(page._rows[expected].isVisible(), query)
            self.assertEqual(page.values(), before)
            self.assertFalse(page.empty.isVisible())
        sequence = page._edits['pip_volume_up'].keySequence()
        for format in (QKeySequence.PortableText, QKeySequence.NativeText):
            page.search.setText(sequence.toString(format))
            self.assertTrue(page._rows['pip_volume_up'].isVisible())
            self.assertEqual(page.values(), before)
        page.search.setText('audio_cycle')
        self.assertEqual([key for key, row in page._rows.items() if row.isVisible()], ['audio_cycle'])
        self.assertEqual([key for key, _card, _wide in page.sections.entries], ['general'])
        page.search.setText('没有此功能xyz')
        self.assertTrue(page.empty.isVisible())
        self.assertFalse(any(row.isVisible() for row in page._rows.values()))
        self.assertEqual(page.values(), before)
        page.search.clear()
        self.assertTrue(all(row.isVisible() for row in page._rows.values()))
        self.assertEqual(len(page.sections.entries), 5)
        self.assertEqual(page.values(), before)

    def test_keyboard_mouse_binding_disabled_values_and_reset_keep_original_contract(self):
        page = self.page({'focus': '', 'volume_up': 'Alt+WheelUp'})
        self.assertFalse(page._row_toggles['focus'].isChecked())
        self.assertFalse(page._edits['focus'].isEnabled())
        self.assertEqual(page.values()['focus'], '')
        page._row_toggles['focus'].click()
        self.assertTrue(page._edits['focus'].isEnabled())
        editor = page._edits['focus']
        editor.setFocus()
        QTest.keyClick(editor, Qt.Key_L, Qt.ControlModifier)
        self.assertEqual(editor.keySequence().toString(), 'Ctrl+L')
        self.assertEqual(page.values()['focus'], 'Ctrl+L')
        mouse = page._edits['volume_up']
        mouse.setFocus()
        mouse.selectAll()
        QTest.keyClicks(mouse, 'Shift+WheelUp')
        self.assertTrue(mouse.property('mouseShortcut'))
        self.assertEqual(page.values()['volume_up'], 'Shift+WheelUp')
        page._row_toggles['focus'].click()
        self.assertEqual(page.values()['focus'], '')
        reopened = self.page(page.values())
        self.assertEqual(reopened.values()['focus'], '')
        page._reset_one('focus')
        self.assertEqual(page.values()['focus'], 'F')
        page._edits['audio_cycle'].setKeySequence(QKeySequence('Ctrl+E'))
        page._reset_group([item for item in SHORTCUT_ACTIONS if item[0] in page._group_keys['general']])
        self.assertEqual(page.values()['audio_cycle'], 'E')
        page.reset()
        self.assertEqual(page.values(), {key: default for key, _label, default in SHORTCUT_ACTIONS})

    def test_custom_layout_gestures_are_searchable_help_and_do_not_add_bindings(self):
        page = self.page(width=500)
        before = page.values()
        for query, expected in (('Ctrl+滚轮', 'Ctrl＋滚轮'), ('Ctrl+WheelDown', 'Ctrl＋滚轮'),
                                ('1×3', '右键直播格'), ('竖屏占位', '右键直播格')):
            page.search.setText(query)
            settle()
            visible = [label.text() for label, _terms in page._layout_shortcut_hints if label.isVisible()]
            self.assertEqual(len(visible), 1)
            self.assertIn(expected, visible[0])
            self.assertFalse(page.empty.isVisible())
            self.assertEqual([key for key, _card, _wide in page.sections.entries], ['wheel'])
        self.assertEqual(page.values(), before)

    def test_compact_rows_fit_narrow_width_large_font_and_descriptions_are_not_repeated(self):
        previous = dict(theme._preferences)
        self.addCleanup(theme.configure_appearance, previous)
        for size in (13, 20):
            theme.configure_appearance({'appearance_font_size': size})
            page = self.page(width=500)
            for width in (500, 1200):
                page.resize(width, 800)
                settle()
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                self.assertTrue(all('⌄' not in label.text() for label in page.findChildren(QLabel)))
                self.assertFalse(any(button.text() == '✎' for button in page.findChildren(QPushButton)))
                for key, description, _default in SHORTCUT_ACTIONS:
                    row = page._rows[key]
                    edit, toggle = page._edits[key], page._row_toggles[key]
                    labels = row.findChildren(QLabel)
                    self.assertEqual(len(labels), 1)
                    self.assertEqual(labels[0].toolTip(), description)
                    self.assertEqual(edit.accessibleDescription(), description)
                    self.assertEqual(edit.width(), 150)
                    reset = row.findChild(QPushButton)
                    for widget in (edit, toggle, reset):
                        self.assertTrue(row.rect().contains(widget.geometry().bottomRight()),
                                        (size, width, key, type(widget).__name__, row.rect(), widget.geometry()))
                    self.assertLess(labels[0].geometry().right(), edit.x())
                    self.assertLess(edit.geometry().right(), toggle.x())
                    self.assertLess(toggle.geometry().right(), reset.x())
                    self.assertLessEqual(max(widget.geometry().center().y() for widget in (edit, toggle, reset))
                                         - min(widget.geometry().center().y() for widget in (edit, toggle, reset)), 1)
            page.hide()

    def test_filtering_does_not_save_and_existing_controls_still_trigger_autosave(self):
        dialog = SettingsDialog({}, {}, preview=True)
        self.addCleanup(dispose, dialog)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['shortcuts'])
        page = dialog.shortcut_page
        requested = []
        dialog.auto_save.requested.connect(requested.append)
        dialog.auto_save.start()
        self.addCleanup(dialog.auto_save.stop)
        page.search.setText('全屏')
        dialog.auto_save.flush()
        self.assertEqual(requested, [])
        page._edits['focus'].setKeySequence(QKeySequence('Ctrl+K'))
        self.assertTrue(dialog.auto_save.timer.isActive())
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['shortcuts']['focus'], 'Ctrl+K')
        dialog.auto_save.acknowledge()
        page._row_toggles['focus'].click()
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['shortcuts']['focus'], '')

    def test_wheel_options_save_in_shortcuts_page_and_restore_defaults(self):
        dialog = SettingsDialog({'wheel_volume_step': 7, 'hover_wheel_volume': False,
                                 'settings_wheel_speed': 3}, {}, preview=True)
        self.addCleanup(dispose, dialog)
        self.assertNotIn('hover_wheel_volume', dialog.general_page.values())
        self.assertEqual(dialog.settings()['wheel_volume_step'], 7)
        self.assertEqual(dialog.settings()['hover_wheel_volume_step'], 3)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['shortcuts'])
        page = dialog.shortcut_page
        self.assertEqual(page.wheel_step.value(), 7)
        self.assertEqual(page.hover_wheel_step.value(), 3)
        self.assertFalse(page.hover_wheel_volume.isChecked())
        self.assertEqual(page.wheel_speed.currentData(), 3)
        requested = []
        dialog.auto_save.requested.connect(requested.append)
        dialog.auto_save.start()
        self.addCleanup(dialog.auto_save.stop)
        page.search.setText('音量步长')
        self.assertFalse(page._wheel_options.isHidden())
        self.assertEqual([key for key, _card, _wide in page.sections.entries], ['wheel'])
        page.hover_wheel_step.setValue(4)
        page.hover_wheel_volume.click()
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['settings'],
                         {'hover_wheel_volume_step': 4, 'hover_wheel_volume': True})
        dialog.auto_save.acknowledge()
        page.wheel_step.setValue(8)
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['settings'], {'wheel_volume_step': 8})
        dialog.auto_save.acknowledge()
        reset = next(button for button in page.sections.section('wheel').findChildren(QPushButton)
                     if button.accessibleName() == '恢复本组')
        reset.click()
        self.assertEqual(page.settings_values(), {'wheel_volume_step': 10, 'hover_wheel_volume_step': 3,
                                                   'hover_wheel_volume': False, 'settings_wheel_speed': 1})

    def test_shared_legacy_bindings_are_copied_and_explicit_context_bindings_win(self):
        bindings = configured_shortcuts({'mute': 'Ctrl+M', 'solo': '',
                                         'pip_volume_up': 'Ctrl+U', 'pip_mute': 'Ctrl+J'})
        page = self.page(bindings)
        self.assertEqual(page.values()['fullscreen_volume_up'], 'Ctrl+U')
        self.assertEqual(page.values()['pip_volume_up'], 'Ctrl+U')
        self.assertEqual(page.values()['pip_solo'], '')
        self.assertEqual(page.values()['pip_mute'], 'Ctrl+J')
        page._edits['pip_volume_up'].setKeySequence(QKeySequence('Ctrl+P'))
        page._row_toggles['pip_exit'].click()
        self.assertEqual(page.values()['fullscreen_volume_up'], 'Ctrl+U')
        self.assertEqual(page.values()['pip_volume_up'], 'Ctrl+P')
        self.assertEqual(page.values()['restore'], 'Esc')
        self.assertEqual(page.values()['pip_exit'], '')


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(ShortcutSettingsTests, __file__))
    else:
        unittest.main()
