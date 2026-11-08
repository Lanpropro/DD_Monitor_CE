"""Wide/narrow settings geometry, existing controls and plugin grid compatibility."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QScrollArea
from ddm import config, theme
from ddm.dialogs import SettingsDialog

APP = QApplication.instance() or QApplication([])


def settle():
    for _ in range(8):
        APP.processEvents()


class SettingsLayoutTests(unittest.TestCase):
    def setUp(self):
        self.dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        self.dialog.setAttribute(Qt.WA_DontShowOnScreen)
        self.dialog.setStyleSheet(theme.qss())
        self.dialog.show()
        self.dialog.resize(1200, 800)
        settle()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        settle()

    def page(self, index):
        self.dialog.nav.setCurrentRow(index)
        settle()
        return self.dialog.general_page if index == 0 else self.dialog._loaded_pages[index]

    def test_wide_pages_use_two_columns_and_same_control_objects(self):
        for index in (0, 2, 3, 4, 5):
            with self.subTest(page=index):
                page = self.page(index)
                self.assertEqual(page.sections.columns, 2)
                left, right = [widget for _key, widget, wide in page.sections.entries if not wide][:2]
                self.assertEqual(left.y(), right.y())
                self.assertLess(left.geometry().right(), right.x())
                self.assertGreaterEqual(left.width(), 400)
                self.assertGreaterEqual(right.width(), 400)

    def test_narrow_pages_stack_without_horizontal_scroll_and_keep_edits(self):
        for index in (0, 2, 3, 4, 5):
            page = self.page(index)
            before = page.values()
            self.dialog.resize(760, 650)
            settle()
            with self.subTest(page=index):
                self.assertEqual(self.dialog.width(), 760)
                self.assertEqual(page.sections.columns, 1)
                left, right = [widget for _key, widget, wide in page.sections.entries if not wide][:2]
                self.assertLess(left.geometry().bottom(), right.y())
                self.assertEqual(page.values(), before)
                scroll = self.dialog.general_scroll if index == 0 else getattr(page, 'scroll', None)
                if isinstance(scroll, QScrollArea):
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
            self.dialog.resize(1200, 800)
            settle()

    def test_general_reset_and_released_plugin_insertion_anchor(self):
        page = self.page(0)
        grid = page.layout().itemAt(1).layout()
        anchor = page._checks['sidebar_platform_logos']
        row = grid.getItemPosition(grid.indexOf(anchor))[0] + 1
        checks = []
        for index, platform in enumerate(('domestic', 'global')):
            check = QCheckBox(platform + ' 平台标识', page)
            check.setObjectName(platform + '_show_platform_logo')
            grid.addWidget(check, row + index, 0, 1, 2)
            checks.append(check)
        settle()
        for check in checks:
            self.assertTrue(check.isVisible())
            self.assertGreater(check.y(), page.sections.geometry().bottom())
        self.assertLess(checks[0].geometry().bottom(), checks[1].y())
        page.volume_slider.setValue(19)
        page.poll_spin.setValue(8)
        self.assertEqual(self.dialog.settings()['default_volume'], 19)
        self.dialog._reset_current()
        self.assertEqual(page.volume_slider.value(), config.DEFAULT_SETTINGS['default_volume'])
        self.assertEqual(page.poll_spin.value(), config.DEFAULT_SETTINGS['poll_minutes'])
        self.assertIsNotNone(grid.itemAt(grid.indexOf(anchor)))

    def test_sc_curve_and_preview_share_a_row_with_display_controls_below(self):
        page = self.page(2)
        left, right, display = [page.sections.section(key) for key in
                                ('sc_curve', 'sc_placement', 'sc_display')]
        self.assertEqual(left.y(), right.y())
        self.assertGreater(display.y(), left.geometry().bottom())
        self.assertGreater(display.width(), left.width() * 1.9)
        points = [[0, .5], [1, 1], [2, 1.4]]
        page.super_chat_scale_curve.set_curve(points)
        page.super_chat_scale_curve.curveChanged.emit(points)
        self.assertEqual(page.super_chat_placement.scale_curve, points)
        self.assertEqual(self.dialog.settings()['super_chat_scale_curve'], points)
        self.assertIs(page.super_chat_placement.parentWidget(), right)

    def test_recording_state_and_shortcuts_survive_column_changes(self):
        page = self.page(3)
        page.directory.setText('offline-recordings')
        page.recording_enabled.setChecked(False)
        self.assertFalse(page.format.isEnabled())
        self.dialog.resize(760, 650)
        settle()
        self.assertEqual(page.values()['recording_dir'], 'offline-recordings')
        self.assertFalse(page.values()['recording_enabled'])
        self.dialog.resize(1200, 800)
        page = self.page(5)
        page._edits['mute'].setKeySequence('Ctrl+M')
        self.assertEqual(self.dialog.shortcuts()['mute'], 'Ctrl+M')
        self.dialog.resize(760, 650)
        settle()
        self.assertEqual(self.dialog.shortcuts()['mute'], 'Ctrl+M')
        self.dialog._reset_current()
        self.assertEqual(self.dialog.shortcuts()['mute'], 'M')

    def test_tray_retains_menu_preview_order_and_visibility(self):
        page = self.page(6)
        editor = page.tile_menu
        editor.move_before('reload', 'mute')
        editor.checks['reload'].setChecked(False)
        before = editor.values()
        for width in (760, 1200):
            self.dialog.resize(width, 800)
            settle()
            self.assertEqual(editor.values(), before)
            self.assertTrue(editor.preview.isVisible())
            self.assertTrue(editor.checks['reload'].isVisible())


if __name__ == '__main__':
    unittest.main()
