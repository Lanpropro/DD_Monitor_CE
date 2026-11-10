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
            self.assertTrue(page.sections.section('extensions').isAncestorOf(check))
        self.assertLess(checks[0].geometry().bottom(), checks[1].y())
        page.volume_slider.setValue(19)
        page.poll_spin.setValue(8)
        self.assertEqual(self.dialog.settings()['default_volume'], 19)
        self.dialog._reset_current()
        self.assertEqual(page.volume_slider.value(), config.DEFAULT_SETTINGS['default_volume'])
        self.assertEqual(page.poll_spin.value(), config.DEFAULT_SETTINGS['poll_minutes'])
        self.assertIsNotNone(grid.itemAt(grid.indexOf(anchor)))

    def test_show_event_plugin_hook_keeps_identity_on_reopen(self):
        from PySide6.QtCore import QObject
        page = self.page(0)
        class Hook(QObject):
            def eventFilter(self, watched, event):
                if watched is self.parent() and event.type() == QEvent.Show:
                    if page.findChild(QCheckBox, 'fixture_show') is None:
                        check = QCheckBox('显示插件标记', page)
                        check.setObjectName('fixture_show')
                        grid = page.layout().itemAt(1).layout()
                        anchor = page._checks['sidebar_platform_logos']
                        row = grid.getItemPosition(grid.indexOf(anchor))[0] + 1
                        grid.addWidget(check, row, 0, 1, 2)
                return False
        hook = Hook(self.dialog)
        APP.installEventFilter(hook)
        try:
            self.dialog.hide()
            self.dialog.show()
            settle()
            check = page.plugin_controls()['fixture_show']
            check.setChecked(True)
            self.assertTrue(page.sections.section('extensions').isAncestorOf(check))
            self.dialog.hide()
            self.dialog.show()
            settle()
            self.assertIs(page.plugin_controls()['fixture_show'], check)
            self.assertTrue(check.isChecked())
            self.assertEqual(len(page.findChildren(QCheckBox, 'fixture_show')), 1)
        finally:
            APP.removeEventFilter(hook)

    def test_late_plugin_widgets_and_layouts_share_a_card_without_duplication(self):
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit
        page = self.page(0)
        grid = page.layout().itemAt(1).layout()
        row = QHBoxLayout()
        label, edit = QLabel('插件输入'), QLineEdit('保留值')
        row.addWidget(label)
        row.addWidget(edit)
        grid.addLayout(row, grid.rowCount(), 0, 1, 2)
        settle()
        card = page.sections.section('extensions')
        self.assertTrue(card.isAncestorOf(edit))
        self.assertEqual(edit.text(), '保留值')
        hidden = QLineEdit('条件选项', page)
        hidden.hide()
        grid.addWidget(hidden, grid.rowCount(), 0, 1, 2)
        page.plugin_controls()
        self.assertTrue(card.isAncestorOf(hidden))
        self.assertTrue(hidden.isHidden())
        check = QCheckBox('稍后追加', page)
        check.setObjectName('fixture_late')
        grid.addWidget(check, grid.rowCount(), 0, 1, 2)
        settle()
        self.assertIs(page.plugin_controls()['fixture_late'], check)
        from PySide6.QtWidgets import QSpinBox
        from ddm.ui import StepperControl
        stepper = StepperControl(QSpinBox())
        grid.addWidget(stepper, grid.rowCount(), 1, Qt.AlignRight)
        page.plugin_controls()
        self.assertTrue(card.grid.itemAt(card.grid.indexOf(stepper)).alignment() & Qt.AlignRight)
        self.assertTrue(card.isAncestorOf(check))
        for width in (760, 1200):
            self.dialog.resize(width, 800)
            settle()
            self.assertEqual(sum(key == 'extensions' for key, *_ in page.sections.entries), 1)
            self.assertEqual(self.dialog.general_scroll.horizontalScrollBar().maximum(), 0)
        self.assertLess(card.width(), page.sections.width() * .6)
        self.assertLess(card.height(), page.sections.section('codecs').height())

    def test_settings_sliders_use_one_compact_width(self):
        from PySide6.QtWidgets import QSlider
        for index in (0, 1, 2, 4):
            page = self.page(index)
            sliders = page.findChildren(QSlider)
            self.assertTrue(sliders, index)
            for slider in sliders:
                self.assertEqual(slider.minimumWidth(), theme.SETTINGS_SLIDER_WIDTH)
                self.assertEqual(slider.maximumWidth(), theme.SETTINGS_SLIDER_WIDTH)

    def test_numeric_selection_clears_on_blank_and_other_control_clicks(self):
        APP.setActiveWindow(self.dialog)  # The isolated shell uses WA_DontShowOnScreen.
        page = self.page(0)
        first = page.poll_spin
        second = page.compact_threshold_spin
        self.dialog.general_scroll.ensureWidgetVisible(first)
        settle()
        QTest.mouseClick(first.lineEdit(), Qt.LeftButton)
        first.lineEdit().selectAll()
        self.assertTrue(first.lineEdit().hasSelectedText())
        QTest.mouseClick(page.sections.section('playback'), Qt.LeftButton)
        self.assertFalse(first.lineEdit().hasSelectedText())
        first.setFocus()
        first.lineEdit().selectAll()
        QTest.mouseClick(second.lineEdit(), Qt.LeftButton)
        self.assertFalse(first.lineEdit().hasSelectedText())
        self.assertTrue(second.hasFocus())

    def test_normalization_uses_the_shared_switch_and_preserves_values(self):
        from ddm.ui import ToggleSwitch
        page = self.page(0)
        switch = page._checks['volume_normalization']
        self.assertIsInstance(switch, ToggleSwitch)
        self.assertFalse(switch.isChecked())
        QTest.mouseClick(switch, Qt.LeftButton)
        self.assertTrue(page.values()['volume_normalization'])
        self.dialog._reset_current()
        self.assertFalse(page.values()['volume_normalization'])

    def test_general_steppers_share_one_surface_and_respect_auto_compact(self):
        page = self.page(0)
        from ddm.ui import StepperControl
        self.assertIsInstance(page.poll_stepper, StepperControl)
        self.assertIs(page.poll_stepper.spin, page.poll_spin)
        self.assertEqual(page.poll_stepper.width(), theme.SETTINGS_STEPPER_WIDTH)
        self.assertEqual(page.compact_threshold_stepper.width(), theme.SETTINGS_STEPPER_WIDTH)
        self.assertEqual(page.poll_stepper.geometry().right(), page.compact_threshold_stepper.geometry().right())
        page.poll_stepper.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH - 24)
        settle()
        self.assertEqual(page.poll_stepper.geometry().right(), page.compact_threshold_stepper.geometry().right())
        page.poll_stepper.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH)
        settle()
        before = page.poll_spin.value()
        QTest.mouseClick(page.poll_stepper.plus, Qt.LeftButton)
        self.assertEqual(page.poll_spin.value(), before + 1)
        page._checks['sidebar_auto_compact'].setChecked(False)
        value = page.compact_threshold_spin.value()
        self.assertFalse(page.compact_threshold_stepper.isEnabled())
        QTest.mouseClick(page.compact_threshold_stepper.plus, Qt.LeftButton)
        self.assertEqual(page.compact_threshold_spin.value(), value)
        page._checks['sidebar_auto_compact'].setChecked(True)
        QTest.mouseClick(page.compact_threshold_stepper.plus, Qt.LeftButton)
        self.assertEqual(page.compact_threshold_spin.value(), value + 1)
        self.assertEqual(page.values()['poll_minutes'], before + 1)
        self.assertEqual(page.values()['sidebar_compact_threshold'], value + 1)

    def test_general_volume_value_uses_readable_theme_text(self):
        from PySide6.QtGui import QPalette
        before = theme.mode()
        try:
            for mode in ('light', 'dark'):
                theme.apply(mode)
                self.dialog.setStyleSheet(theme.qss())
                settle()
                label = self.dialog.general_page.volume_label
                self.assertEqual(label.palette().color(QPalette.WindowText).name(), theme.qcolor(theme.TEXT1).name())
                self.assertEqual(label.text(), '40')
                self.assertTrue(label.font().bold())
        finally:
            theme.apply(before)
            self.dialog.setStyleSheet(theme.qss())

    def test_general_codecs_have_a_compact_card_and_keep_edits_across_widths(self):
        page = self.page(0)
        card = page.sections.section('codecs')
        playback = page.sections.section('playback')
        self.assertTrue(card.isAncestorOf(page.codec_editor))
        self.assertTrue(page.codec_editor.isVisible())
        self.assertLess(playback.height(), page.sections.section('following').height())
        with patch('ddm.dialogs.CodecSettingsDialog') as factory:
            page.codec_editor.source_buttons['hevc'].click()
            page.codec_editor.decode_control.setCurrentIndex(page.codec_editor.decode_control.findData('none'))
            factory.assert_not_called()
        for width in (760, 1200):
            self.dialog.resize(width, 800)
            settle()
            self.assertTrue(page.codec_editor.isVisible())
            self.assertEqual(self.dialog.general_scroll.horizontalScrollBar().maximum(), 0)
            self.assertEqual(self.dialog.settings()['bili_codec'], 'hevc')
            self.assertEqual(self.dialog.settings()['decode_mode'], 'none')
            select = page.codec_editor.decode_control
            self.assertLessEqual(select.geometry().right(), page.codec_editor.width())
            self.assertEqual(page.codec_editor.decode_hint.text(), config.DECODE_HINTS['none'])
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
            self.assertFalse(restored.general_page.codec_editor.isHidden())
        finally:
            for dialog in (draft, restored):
                if dialog is not None:
                    dialog.close()
                    dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    @unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows'
                         and sys.getwindowsversion().build >= 22621, 'Windows 11 system backdrop only')
    def test_theme_switches_reuse_the_solid_frame_on_the_same_native_window(self):
        import ctypes
        from ctypes import wintypes
        extend = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
        extend.argtypes = (wintypes.HWND, ctypes.c_void_p)
        self.dialog._frame_hwnd = None
        hwnd = int(self.dialog.winId())
        geometry = self.dialog.geometry()
        try:
            with patch.object(ctypes.windll.dwmapi, 'DwmExtendFrameIntoClientArea', wraps=extend) as applied:
                for mode in ('light', 'dark', 'light'):
                    theme.apply(mode)
                    settle()
                    self.assertTrue(self.dialog.isVisible())
                    self.assertTrue(self.dialog._native_corners)
                    self.assertEqual(int(self.dialog.winId()), hwnd)
                    self.assertEqual(self.dialog.geometry(), geometry)
                self.assertEqual(applied.call_count, 1, 'Theme changes must not recreate the native frame')
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

    def test_codec_popup_does_not_move_cards_or_leading_controls(self):
        page = self.page(0)
        geometries = [card.geometry() for _key, card, _wide in page.sections.entries]
        select = page.codec_editor.decode_control
        select.showPopup()
        settle()
        self.assertEqual([card.geometry() for _key, card, _wide in page.sections.entries], geometries)
        select.hidePopup()
        settle()
        self.assertEqual([card.geometry() for _key, card, _wide in page.sections.entries], geometries)

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
        self.assertTrue(normalize({'settings_glass_enabled': True})['settings_glass_enabled'])
        self.assertEqual(normalize(dict(settings_glass_enabled='bad', settings_glass_blur=99,
                                        settings_glass_opacity=-10, settings_no_shadows=None)),
                         {**DEFAULTS, 'settings_glass_blur': 40, 'settings_glass_opacity': 0})
        editor = self.page(1).material_editor
        self.assertEqual(set(editor.controls), {'settings_no_shadows', 'settings_glass_enabled', 'settings_segment_motion'})
        editor.controls['settings_no_shadows'].setChecked(True)
        self.assertTrue(self.dialog.property('settings_no_shadows'))
        self.assertFalse(self.dialog.property('settings_glass_enabled'))
        self.assertEqual(self.dialog.windowOpacity(), 1.0)
        self.dialog.reset_button.click()
        self.assertEqual(editor.values(), DEFAULTS)
        self.page(0)
        button = self.dialog.general_page.codec_editor.source_buttons['avc']
        before = button.grab().toImage()
        self.dialog.set_material(dict(settings_no_shadows=True))
        after = button.grab().toImage()
        self.assertNotEqual(before, after, 'The shadow preference must change actual selection pixels')


    def test_appearance_cards_and_compact_theme_preserve_mode_signals(self):
        from ddm.ui import SegmentedControl
        page = self.page(1)
        self.assertIsInstance(page.mode_control, SegmentedControl)
        modes = []
        page.modeChanged.connect(modes.append)
        page.buttons['light'].click()
        self.assertEqual(modes, ['light'])
        self.assertEqual(page.values()['appearance_mode'], 'light')
        page.sync('dark')
        self.assertEqual(modes, ['light'], 'Theme synchronization must not trigger another save')
        self.assertEqual(page.mode_control.value(), 'dark')
        for width, columns in ((1200, 2), (760, 1)):
            self.dialog.resize(width, 800)
            settle()
            self.assertEqual(page.sections.columns, columns)
            theme_card = page.sections.section('theme')
            material_card = page.sections.section('material')
            self.assertTrue(theme_card.isAncestorOf(page.mode_control))
            self.assertLessEqual(page.mode_control.width(), 260)
            if columns == 2:
                self.assertEqual(theme_card.y(), material_card.y())
                self.assertLess(theme_card.geometry().right(), material_card.x())
            else:
                self.assertLess(theme_card.geometry().bottom(), material_card.y())
            self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)

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
    def test_glass_keeps_native_backdrop_disabled(self):
        from ddm.window_fullscreen import _dwm_get
        hwnd = int(self.dialog.winId())
        for enabled in (True, False, True):
            self.dialog.set_material({'settings_glass_enabled': enabled, 'settings_glass_opacity': 0})
            settle()
            self.assertEqual(self.dialog.property('settings_glass_enabled'), enabled)
            self.assertEqual(_dwm_get(hwnd, 38), 1)
            self.assertTrue(self.dialog.isVisible())
            self.assertEqual(int(self.dialog.winId()), hwnd)


    def test_native_frame_has_no_second_inner_corner_and_is_opaque(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        from ddm.settings_window import SettingsWindow
        shell = SettingsWindow()
        shell.resize(240, 180)
        shell.set_material(dict(settings_glass_enabled=True, settings_glass_opacity=0))
        try:
            with patch('ddm.settings_window.apply_frame', return_value=True), \
                    patch('ddm.skin_parts.values_for', return_value={}):
                shell.show()
                settle()
                surface = shell.grab().toImage()
            scale = surface.devicePixelRatio()
            self.assertEqual(surface.pixelColor(round(3 * scale), round(3 * scale)).alpha(), 255,
                             'DWM owns the outer curve; the client must not expose another cutout')
            for background in ('#ffffff', '#000000'):
                composed = QImage(surface.size(), QImage.Format_ARGB32_Premultiplied)
                composed.fill(QColor(background))
                painter = QPainter(composed)
                painter.drawImage(composed.rect(), surface)
                painter.end()
                color = composed.pixelColor(composed.width() // 2, composed.height() // 2)
                self.assertEqual(color.name(), '#33373b', 'The base must be independent of desktop colours')
            shell._native_corners = False
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
    def test_native_solid_frame_and_caption(self):
        import ctypes
        from ctypes import wintypes
        from ddm.window_fullscreen import _dwm_get
        hwnd = int(self.dialog.winId())
        self.assertTrue(self.dialog._native_corners)
        self.assertEqual(_dwm_get(hwnd, 38), 1)
        self.assertEqual(_dwm_get(hwnd, 33), 2)
        self.assertTrue(self.dialog.mask().isEmpty(), 'Keep native antialiasing at fractional DPI')
        get_style = ctypes.windll.user32.GetWindowLongPtrW
        get_style.argtypes = (wintypes.HWND, ctypes.c_int)
        get_style.restype = ctypes.c_ssize_t
        self.assertEqual(get_style(hwnd, -16) & 0x00c00000, 0)




class AppearanceEditorTests(unittest.TestCase):
    def test_embedded_controls_keep_values_scene_links_and_narrow_geometry(self):
        from copy import deepcopy
        from types import SimpleNamespace
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QWidget
        from ddm.dialogs import AppearanceSettingsPage
        from ddm.skin_preview import SkinPreview
        from ddm.ui import SelectControl, SettingsSlider, SettingsSurface, SettingsValueLabel, ToggleSwitch

        class Layer(QObject):
            frameReady = Signal()
            path, image, mask = 'fixture.mp4', None, 35

        class Controller(QObject):
            changed = Signal()
            override, error = None, ''

        owner = QWidget()
        owner.settings = deepcopy(config.DEFAULT_SETTINGS)
        owner.settings['skin_background'] = 'fixture.mp4'
        owner.skin_controller = Controller(owner)
        owner.skin_controller.window = owner
        owner.skin_controller.layer = Layer(owner)

        def set_skin(values):
            owner.settings.update(values)
            owner.skin_controller.layer.mask = values['skin_mask']
            owner.skin_controller.layer.path = values['skin_background']
            owner.skin_controller.changed.emit()

        owner.set_skin = set_skin
        owner.set_skin_parts = lambda values: owner.settings.update(skin_parts=values)
        # Native playback and recursive screenshots are outside this layout check.
        with patch.object(SkinPreview, 'capture_interface'):
            page = AppearanceSettingsPage(owner.settings, skin_controller=owner.skin_controller)
            page.setProperty('settingsGlassWindow', True)
            page.setStyleSheet(theme.qss())
            page.show()
            try:
                editor = page.parts_editor
                background = editor.background_controls
                self.assertEqual(editor.findChildren(SettingsSurface), [editor.editor_card])
                self.assertTrue(editor.editor_card.isAncestorOf(editor.preview))
                self.assertTrue(editor.editor_card.isAncestorOf(background.choose))
                self.assertIsInstance(editor.scenes, SelectControl)
                self.assertIsInstance(background.video_toggle, ToggleSwitch)
                self.assertIsInstance(background.mask_slider, SettingsSlider)
                self.assertIsInstance(background.mask_label, SettingsValueLabel)
                for mode in ('light', 'dark'):
                    theme.apply(mode)
                    for width, columns in ((1100, 2), (540, 1)):
                        page.resize(width, 850)
                        settle()
                        self.assertEqual(editor.sections.columns, columns)
                        self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                        preview = editor.sections.section('preview')
                        controls = editor.sections.section('controls')
                        if columns == 2:
                            self.assertEqual(preview.y(), controls.y())
                            self.assertLess(preview.geometry().right(), controls.x())
                        else:
                            self.assertLess(preview.geometry().bottom(), controls.y())
                        for index, part in enumerate(('background', 'settings', 'layout_menu')):
                            editor.scenes.setCurrentIndex((index + 1) % 3)
                            editor.scenes.setCurrentIndex(index)
                            settle()
                            self.assertEqual(editor.part.currentData(), part)
                            self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                            reset = background.clear if part == 'background' else editor.builtin_button
                            self.assertTrue(reset.isVisible())
                            self.assertTrue(editor.scenes.parentWidget() is reset.parentWidget())
                            self.assertLess(reset.geometry().right(), editor.scenes.x())
                            self.assertEqual(reset.geometry().center().y(), editor.scenes.geometry().center().y())
                            self.assertEqual(reset.width(), 180)
                            self.assertEqual(background.clear.isVisible(), part == 'background')
                            self.assertEqual(editor.builtin_button.isVisible(), part != 'background')
                        editor._select_part('buttons.settings')
                        self.assertEqual(editor.scenes.currentIndex(), 0)
                editor._select_part('background')
                self.assertTrue(background.video_toggle.isVisible())
                background.video_toggle.click()
                self.assertFalse(owner.settings['skin_video_enabled'])
                background.mask_slider.setValue(47)
                self.assertEqual(owner.settings['skin_mask'], 47)
                self.assertEqual(background.mask_label.text(), '47%')
                self.assertEqual(background.mask_slider.width(), theme.SETTINGS_SLIDER_WIDTH)
                background.clear.click()
                self.assertEqual(owner.settings['skin_background'], '')
                self.assertEqual(owner.settings['skin_mask'], 35)
                self.assertTrue(owner.settings['skin_video_enabled'])
                owner.settings['skin_parts'] = {'settings': {'radius': 13}, 'layout_menu': {'radius': 12}}
                editor._select_part('settings')
                editor.builtin_button.click()
                self.assertEqual(owner.settings['skin_parts'], {
                    'settings': {'radius': 13, 'builtin': True}, 'layout_menu': {'radius': 12}})
                owner.skin_controller.layer.path = 'fixture.png'
                background.sync()
                self.assertTrue(background.video_row.isHidden())
                self.assertTrue(background.video_toggle.isHidden())
            finally:
                page.close()
                page.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                owner.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
