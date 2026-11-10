"""Wide/narrow settings geometry, existing controls and plugin grid compatibility."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QScrollArea
from PySide6.QtTest import QTest
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.ui import SettingsSurface

APP = QApplication.instance() or QApplication([])


def settle():
    for _ in range(8):
        APP.processEvents()


class SettingsLayoutTests(unittest.TestCase):
    def setUp(self):
        self.dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        self.assertEqual(self.dialog.property('skinPart'), 'settings')
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
                for _key, card, _wide in page.sections.entries:
                    self.assertIsInstance(card, SettingsSurface)
                left, right = [widget for _key, widget, wide in page.sections.entries if not wide][:2]
                self.assertEqual(left.y(), right.y())
                self.assertLess(left.geometry().right(), right.x())
                self.assertGreaterEqual(left.width(), 400)
                self.assertGreaterEqual(right.width(), 400)
                if index == 4:
                    heading = page.sections.section('live').layout().itemAt(0).widget()
                    self.assertLess(heading.height(), heading.fontMetrics().height() * 2)

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

    def test_general_codecs_expand_inline_and_keep_edits_across_widths(self):
        page = self.page(0)
        self.assertTrue(page.codec_editor.isHidden())
        following = page.sections.section('following')
        before_height = following.height()
        playback = page.sections.section('playback')
        collapsed_height = playback.height()
        with patch('ddm.dialogs.CodecSettingsDialog') as factory:
            page.codec_button.click()
            settle()
            factory.assert_not_called()
        self.assertTrue(page.codec_editor.isVisible())
        self.assertGreater(playback.height(), collapsed_height)
        expanded_height = playback.height()
        self.assertLessEqual(page.codec_editor.mapTo(playback, page.codec_editor.rect().bottomRight()).y(), playback.height())
        self.assertEqual(following.height(), before_height)
        self.assertEqual(following.y(), page.sections.section('playback').y())
        page.codec_editor.source_buttons['hevc'].click()
        page.codec_editor.decode_control.setCurrentIndex(page.codec_editor.decode_control.findData('none'))
        self.assertIn('HEVC', page.codec_button.text())
        self.assertIn('CPU', page.codec_button.text())
        for width in (760, 1200):
            self.dialog.resize(width, 800)
            settle()
            self.assertTrue(page.codec_editor.isVisible())
            self.assertEqual(self.dialog.general_scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(self.dialog.settings()['bili_codec'], 'hevc')
            self.assertEqual(self.dialog.settings()['decode_mode'], 'none')
            select = page.codec_editor.decode_control
            self.assertTrue(select.isVisible())
            self.assertEqual(select.count(), len(config.DECODE_MODES))
            self.assertLessEqual(select.geometry().right(), page.codec_editor.width())
            self.assertEqual(page.codec_editor.decode_hint.text(), config.DECODE_HINTS['none'])
            self.assertLess(select.width(), page.codec_editor.width() * .8)
            self.assertLess(page.codec_editor.source_control.width(), page.codec_editor.width() * .8)
        page.codec_button.click()
        self.assertTrue(page.codec_editor.isHidden())
        settle()
        self.assertLess(playback.height(), expanded_height)
        self.assertEqual(page.values()['decode_mode'], 'none')
        self.dialog._reset_current()
        self.assertEqual(page.values()['bili_codec'], config.DEFAULT_SETTINGS['bili_codec'])
        self.assertEqual(page.values()['decode_mode'], config.DEFAULT_SETTINGS['decode_mode'])

    def test_general_codec_cancel_keeps_input_and_saved_choices_reload(self):
        original = dict(config.DEFAULT_SETTINGS)
        draft = SettingsDialog(original, {}, preview=True)
        restored = None
        try:
            draft.general_page.codec_editor.source_buttons['av1'].click()
            draft.general_page.codec_editor.decode_control.setCurrentIndex(draft.general_page.codec_editor.decode_control.findData('dxva2'))
            saved = draft.settings()
            draft.reject()
            self.assertEqual(original, config.DEFAULT_SETTINGS)
            restored = SettingsDialog(saved, {}, preview=True)
            self.assertEqual(restored.settings()['bili_codec'], 'av1')
            self.assertEqual(restored.settings()['decode_mode'], 'dxva2')
            self.assertTrue(restored.general_page.codec_editor.isHidden())
        finally:
            for dialog in (draft, restored):
                if dialog is not None:
                    dialog.close()
                    dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    @unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows'
                         and sys.getwindowsversion().build >= 22621, 'Windows 11 system backdrop only')
    def test_theme_switches_reuse_the_material_on_the_same_native_window(self):
        import ctypes
        from ctypes import wintypes
        extend = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
        extend.argtypes = (wintypes.HWND, ctypes.c_void_p)
        self.dialog._backdrop_key = None
        hwnd = int(self.dialog.winId())
        geometry = self.dialog.geometry()
        try:
            with patch.object(ctypes.windll.dwmapi, 'DwmExtendFrameIntoClientArea', wraps=extend) as applied:
                for mode in ('light', 'dark', 'light'):
                    theme.apply(mode)
                    settle()
                    self.assertTrue(self.dialog.isVisible())
                    self.assertTrue(self.dialog._native_glass)
                    self.assertEqual(int(self.dialog.winId()), hwnd)
                    self.assertEqual(self.dialog.geometry(), geometry)
                self.assertEqual(applied.call_count, 1, 'Theme changes must not restart the native material')
        finally:
            theme.apply('dark')

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

    def test_disclosure_keeps_neighbour_items_and_leading_controls_stable(self):
        from ddm.ui import DisclosureButton
        page = self.page(0)
        self.assertIsInstance(page.codec_button, DisclosureButton)
        neighbours = [card for key, card, _wide in page.sections.entries if key != 'playback']
        items = [page.sections.grid.itemAt(page.sections.grid.indexOf(card)) for card in neighbours]
        leading = [page._checks[key] for key in ('default_muted', 'fullscreen_solo_audio', 'fullscreen_auto_hide_controls')]
        positions = [control.pos() for control in leading]
        for expanded in (True, False, True, False):
            before = page.codec_button.geometry()
            QTest.mousePress(page.codec_button, Qt.LeftButton)
            settle()
            self.assertEqual(page.codec_button.geometry(), before)
            QTest.mouseRelease(page.codec_button, Qt.LeftButton)
            settle()
            self.assertEqual(page.codec_button.height(), theme.CONTROL_HEIGHT)
            self.assertEqual(page.codec_button.isChecked(), expanded)
            self.assertEqual(page.codec_editor.isVisible(), expanded)
            self.assertEqual([control.pos() for control in leading], positions)
            for card, item in zip(neighbours, items):
                self.assertIs(page.sections.grid.itemAt(page.sections.grid.indexOf(card)), item)

    def test_frameless_header_search_and_close_preserve_cancel_semantics(self):
        self.assertTrue(self.dialog.windowFlags() & Qt.FramelessWindowHint)
        header = self.dialog.window_header
        self.assertTrue(header.isAncestorOf(self.dialog.navigation.search))
        self.dialog.nav.setCurrentRow(3)
        settle()
        self.assertIn('录制', header.breadcrumb.text())
        self.dialog.navigation.set_collapsed(True, animate=False)
        self.assertTrue(self.dialog.navigation.search.isVisible())
        self.dialog.general_page.volume_slider.setValue(7)
        self.assertEqual(header.close_button.accessibleName(), '关闭设置')
        QTest.mouseClick(header.close_button, Qt.LeftButton)
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.dialog.result(), QDialog.Rejected)
        self.assertEqual(config.DEFAULT_SETTINGS['default_volume'], self.dialog._initial_settings['default_volume'])


    def test_material_controls_preview_reset_and_shadow_rendering(self):
        from ddm.settings_material import DEFAULTS, normalize
        self.assertEqual(normalize(dict(settings_glass_enabled='bad', settings_glass_blur=99,
                                        settings_glass_opacity=-10, settings_no_shadows=None)),
                         {**DEFAULTS, 'settings_glass_blur': 40, 'settings_glass_opacity': 0})
        editor = self.page(1).material_editor
        editor.controls['settings_glass_opacity'].setValue(55)
        editor.controls['settings_glass_blur'].setValue(8)
        editor.controls['settings_glass_enabled'].setChecked(False)
        self.assertFalse(editor.controls['settings_glass_blur'].isEnabled())
        self.assertEqual(self.dialog.property('settings_glass_opacity'), 55)
        self.assertFalse(self.dialog.property('settings_glass_enabled'))
        self.assertEqual(self.dialog.windowOpacity(), 1.0)
        self.dialog.reset_button.click()
        self.assertEqual(editor.values(), DEFAULTS)
        self.page(0).codec_button.click()
        button = self.dialog.general_page.codec_editor.source_buttons['avc']
        before = button.grab().toImage()
        self.dialog.set_material(dict(settings_no_shadows=True))
        after = button.grab().toImage()
        self.assertNotEqual(before, after, 'The shadow preference must change actual selection pixels')

    def test_material_blur_strength_changes_cached_background_pixels(self):
        import tempfile
        from PySide6.QtGui import QColor, QPainter, QPixmap
        from ddm.ui.settings_surface import _frosted_image
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'background.png'
            image = QPixmap(960, 640)
            image.fill(QColor('black'))
            painter = QPainter(image)
            painter.fillRect(0, 0, 480, 640, QColor('white'))
            painter.end()
            image.save(str(path))
            stat = path.stat()
            sharp = _frosted_image(str(path), stat.st_mtime_ns, stat.st_size, 0).toImage()
            blurred = _frosted_image(str(path), stat.st_mtime_ns, stat.st_size, 32).toImage()
            self.assertLess(blurred.pixelColor(475, 320).red(), sharp.pixelColor(475, 320).red())

    @unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows'
                         and sys.getwindowsversion().build >= 22621, 'Windows 11 system backdrop only')
    def test_material_switch_disables_the_native_effect_without_recreating_the_window(self):
        from ddm.window_fullscreen import _dwm_get
        hwnd = int(self.dialog.winId())
        editor = self.page(1).material_editor
        for enabled, backdrop in ((False, 1), (True, 3)):
            editor.controls['settings_glass_enabled'].setChecked(enabled)
            settle()
            self.assertEqual(_dwm_get(hwnd, 38), backdrop)
            self.assertEqual(self.dialog._native_glass, enabled)
            self.assertTrue(self.dialog.isVisible())
            self.assertEqual(int(self.dialog.winId()), hwnd)

    def test_native_material_has_no_second_inner_corner_and_stays_dark(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        from ddm.settings_window import SettingsWindow
        shell = SettingsWindow()
        shell.resize(240, 180)
        shell.set_material(dict(settings_glass_opacity=88))
        try:
            with patch('ddm.settings_window.apply_backdrop', return_value=True), \
                    patch('ddm.skin_parts.values_for', return_value={}):
                shell.show()
                settle()
                surface = shell.grab().toImage()
            scale = surface.devicePixelRatio()
            self.assertGreater(surface.pixelColor(round(3 * scale), round(3 * scale)).alpha(), 200,
                               'DWM owns the outer curve; the client must not expose another cutout')
            for background in ('#ffffff', '#000000'):
                composed = QImage(surface.size(), QImage.Format_ARGB32_Premultiplied)
                composed.fill(QColor(background))
                painter = QPainter(composed)
                painter.drawImage(composed.rect(), surface)
                painter.end()
                color = composed.pixelColor(composed.width() // 2, composed.height() // 2)
                for actual, reference in zip((color.red(), color.green(), color.blue()), (51, 55, 59)):
                    expected = reference * .88 + QColor(background).red() * .12
                    self.assertLessEqual(abs(actual - expected), 4,
                                         'Glass must layer the reference base tint over the backdrop')
            shell._native_glass = False
            with patch('ddm.skin_parts.values_for', return_value={}):
                fallback = shell.grab().toImage()
            self.assertEqual(fallback.pixelColor(round(3 * scale), round(3 * scale)).alpha(), 0,
                             'The software fallback still owns its rounded transparent corners')
        finally:
            shell.close()
            shell.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    @unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows'
                         and sys.getwindowsversion().build >= 22621, 'Windows 11 system backdrop only')
    def test_native_system_material_and_caption(self):
        import ctypes
        from ctypes import wintypes
        from ddm.window_fullscreen import _dwm_get
        hwnd = int(self.dialog.winId())
        self.assertTrue(self.dialog._native_glass)
        self.assertEqual(_dwm_get(hwnd, 38), 3)
        self.assertEqual(_dwm_get(hwnd, 33), 2)
        self.assertTrue(self.dialog.mask().isEmpty(), 'Keep native antialiasing at fractional DPI')
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        get_style.argtypes = (wintypes.HWND, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        self.assertEqual(get_style(hwnd, -16) & 0x00c00000, 0)



if __name__ == '__main__':
    unittest.main()
