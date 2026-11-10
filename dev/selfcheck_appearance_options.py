"""Appearance preferences, saved card layout, static glass and local gallery; isolated data."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_layout import SettingsColumns, SettingsSection
from ddm.settings_window import SettingsWindow
from ddm.ui import SegmentedControl

APP = QApplication.instance() or QApplication([])
for filename in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/segoeui.ttf'):
    if Path(filename).is_file():
        QFontDatabase.addApplicationFont(filename)


def settle():
    for _ in range(8):
        APP.processEvents()


def dispose(widget):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class AppearanceOptionsTests(unittest.TestCase):
    def tearDown(self):
        theme.configure_appearance({**config.DEFAULT_SETTINGS})
        theme.set_skin_active(False)
        theme.apply('dark')

    def test_preferences_validation_and_accent_survive_mode_changes(self):
        from ddm.appearance_preferences import DEFAULTS, normalize
        self.assertEqual(normalize({'appearance_accent': 'red; color: black',
                                    'appearance_font': 'font"; color:red'}), DEFAULTS)
        theme.configure_appearance({'appearance_accent': '#fff000', 'appearance_font': 'Segoe UI'})
        for mode in ('dark', 'light', 'system', 'dark'):
            theme.apply(mode)
            self.assertNotEqual(theme.ACCENT, '#007BA8' if theme.is_light() else '#00a1d6')
            self.assertIn('"Segoe UI"', theme.FONT_FAMILY)
            self.assertTrue(QColor(theme.ACCENT).isValid())

    def test_auto_save_and_reopen_theme_material_and_card_layout(self):
        settings = deepcopy(config.DEFAULT_SETTINGS)
        dialog = SettingsDialog(settings, {}, preview=True)
        dialog._auto_save_enabled = True
        dialog.resize(1400, 850)
        dialog.show()
        settle()
        def save(changes):
            settings.update(changes.get('settings', {}))
            dialog.auto_save.acknowledge()
        dialog.auto_save.requested.connect(save)
        try:
            dialog.nav.setCurrentRow(1)
            settle()
            page = dialog.appearance_page
            hwnd = int(dialog.winId())
            page.theme_editor.set_accent('#8866ee')
            blue = page.theme_editor.swatches['#00a1d6']
            self.assertEqual(blue.grab().toImage().pixelColor(blue.rect().center()), QColor('#00a1d6'))
            fonts = QFontDatabase.families()
            family = 'Segoe UI' if 'Segoe UI' in fonts else fonts[0]
            page.theme_editor.font.setCurrentIndex(page.theme_editor.font.findData(family))
            material = page.material_editor
            material.controls['settings_glass_enabled'].setChecked(True)
            material.controls['settings_segment_motion'].setChecked(True)
            material.sliders['settings_glass_blur'][0].setValue(13)
            material.sliders['settings_glass_opacity'][0].setValue(52)
            material.card_layout.setCurrentIndex(1)
            settle()
            self.assertEqual(int(dialog.winId()), hwnd)
            self.assertTrue(dialog.isVisible())
            for index in (0, 1, 2, 3, 4, 5, 6):
                dialog.nav.setCurrentRow(index)
                settle()
                current = dialog.general_page if index == 0 else dialog._loaded_pages[index]
                if hasattr(current, 'sections'):
                    self.assertEqual(current.sections.columns, 1)
            dialog.auto_save.flush()
            self.assertEqual(settings['settings_card_layout'], 'vertical')
            self.assertEqual(settings['appearance_accent'], '#8866ee')
            self.assertEqual(settings['appearance_font'], family)
            self.assertTrue(settings['settings_segment_motion'])
            self.assertTrue(settings['settings_glass_enabled'])
        finally:
            dispose(dialog)
        reopened = SettingsDialog(settings, {}, preview=True)
        reopened.resize(1400, 850)
        reopened.show()
        try:
            reopened.nav.setCurrentRow(1)
            settle()
            page = reopened.appearance_page
            self.assertEqual(page.sections.columns, 1)
            self.assertEqual(page.theme_editor.values()['appearance_accent'], '#8866ee')
            self.assertEqual(page.theme_editor.values()['appearance_font'], family)
            self.assertEqual(page.material_editor.sliders['settings_glass_blur'][0].value(), 13)
            self.assertEqual(page.material_editor.sliders['settings_glass_opacity'][0].value(), 52)
            page.material_editor.card_layout.setCurrentIndex(0)
            settle()
            self.assertEqual(page.sections.columns, 2)
        finally:
            dispose(reopened)

    def test_static_glass_changes_pixels_and_keeps_window_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wallpaper.png'
            image = QImage(400, 240, QImage.Format_RGB32)
            image.fill(QColor('#0640cc'))
            painter = QPainter(image)
            painter.fillRect(200, 0, 200, 240, QColor('#ffb020'))
            painter.end()
            image.save(str(path))
            window = SettingsWindow()
            window.resize(400, 240)
            card = SettingsSection('Fixture')
            window.body_layout.addWidget(card)
            window.show()
            try:
                hwnd = int(window.winId())
                samples = []
                for mode in ('dark', 'light'):
                    theme.apply(mode)
                    for enabled, opacity, blur in ((False, 70, 0), (True, 20, 0), (True, 20, 30), (True, 90, 30)):
                        window.set_material(dict(settings_glass_enabled=enabled, settings_glass_opacity=opacity,
                                                 settings_glass_blur=blur, settings_backdrop_path=str(path)))
                        samples.append(window.grab().toImage())
                        self.assertEqual(int(window.winId()), hwnd)
                        self.assertTrue(window.isVisible())
                        self.assertEqual(window.windowOpacity(), 1)
                    self.assertNotEqual(samples[-4], samples[-3])
                    self.assertNotEqual(samples[-3].pixelColor(199, 180), samples[-2].pixelColor(199, 180))
                    self.assertNotEqual(samples[-2], samples[-1])
            finally:
                dispose(window)

    def test_segment_motion_interrupts_and_keyboard_reduced_motion_snap(self):
        root = QWidget()
        root.setProperty('settings_segment_motion', True)
        row = QVBoxLayout(root)
        control = SegmentedControl((('a', '甲'), ('b', '乙'), ('c', '丙')))
        control.setFixedWidth(260)
        row.addWidget(control)
        root.show()
        settle()
        try:
            with patch('ddm.motion.enabled', return_value=True):
                QTest.mouseClick(control.buttons['c'], Qt.LeftButton)
                self.assertEqual(control.value(), 'c')
                self.assertEqual(control._indicator_animation.state(), QAbstractAnimation.Running)
                QTest.qWait(40)
                interrupted = control._indicator
                QTest.mouseClick(control.buttons['a'], Qt.LeftButton)
                self.assertEqual(control._indicator_animation.startValue(), interrupted)
                control.buttons['b'].setFocus()
                QTest.keyClick(control.buttons['b'], Qt.Key_Space)
                self.assertEqual(control.value(), 'b')
                self.assertEqual(control._indicator, control._target_rect())
                self.assertEqual(control._indicator_animation.state(), QAbstractAnimation.Stopped)
                control.setValue('c')
                self.assertEqual(control._indicator, control._target_rect())
            with patch('ddm.motion.enabled', return_value=False):
                QTest.mouseClick(control.buttons['a'], Qt.LeftButton)
                self.assertEqual(control._indicator, control._target_rect())
            root.hide()
            self.assertEqual(control._indicator_animation.state(), QAbstractAnimation.Stopped)
        finally:
            dispose(root)

    def test_local_gallery_selection_and_mask_keep_saved_strength(self):
        from types import SimpleNamespace
        from ddm.skin_settings import SkinSettings
        from ddm.skins import SkinController
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'REPO', directory):
            folder = Path(directory) / 'utils/skins'
            folder.mkdir(parents=True)
            image = QImage(100, 60, QImage.Format_RGB32)
            image.fill(QColor('#cc8855'))
            image.save(str(folder / 'fixture.png'))
            owner = QMainWindow()
            owner.settings = deepcopy(config.DEFAULT_SETTINGS)
            owner.settings['skin_mask'] = 47
            owner.setCentralWidget(QWidget())
            owner.sidebar = SimpleNamespace(**{name: QPushButton() for name in (
                'refresh_button', 'appearance_button', 'toggle_button', 'settings_button',
                'layout_button', 'import_button', 'add_button')})
            controller = owner.skin_controller = SkinController(owner)
            def set_skin(values):
                owner.settings.update(values)
                controller.refresh()
            owner.set_skin = set_skin
            controller.refresh()
            editor = SkinSettings(owner.settings, controller)
            editor.show()
            settle()
            try:
                self.assertEqual(editor.gallery.count(), 2)
                item = editor.gallery.item(1)
                QTest.mouseClick(editor.gallery.viewport(), Qt.LeftButton,
                                 pos=editor.gallery.visualItemRect(item).center())
                self.assertEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
                self.assertEqual(len(list(folder.iterdir())), 1)
                self.assertIsNotNone(controller.layer.image)
                editor.mask_toggle.click()
                self.assertFalse(owner.settings['skin_mask_enabled'])
                self.assertEqual(owner.settings['skin_mask'], 47)
                self.assertEqual(controller.layer.mask, 0)
                self.assertFalse(editor.mask_slider.isEnabled())
                editor.mask_toggle.click()
                self.assertEqual(controller.layer.mask, 47)
                self.assertTrue(editor.mask_slider.isEnabled())
                editor._select_background('utils/skins/missing.png')
                self.assertEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
                package = dict(version=1, owner='fixture', name='Fixture', mask=22,
                               path=str(folder / 'fixture.png'), parts={})
                owner.plugins = SimpleNamespace(active_skin=lambda: package)
                controller.refresh()
                self.assertEqual(editor.mask_slider.value(), 22)
                self.assertFalse(editor.gallery.isEnabled())
                self.assertFalse(editor.mask_toggle.isEnabled())
                editor._select_background('')
                self.assertEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
            finally:
                dispose(editor)
                controller.stop()
                dispose(owner)

    def test_normalization_switch_stays_next_to_its_label(self):
        from PySide6.QtWidgets import QLabel
        dialog = SettingsDialog(deepcopy(config.DEFAULT_SETTINGS), {}, preview=True)
        dialog.resize(1500, 850)
        dialog.show()
        settle()
        try:
            card = dialog.general_page.sections.section('normalization')
            switch = dialog.general_page._checks['volume_normalization']
            label = next(label for label in card.findChildren(QLabel) if label.buddy() is switch)
            gap = switch.mapTo(card, QPoint()).x() - label.mapTo(card, QPoint(label.width(), 0)).x()
            self.assertLessEqual(gap, 16)
            self.assertGreaterEqual(gap, 0)
        finally:
            dispose(dialog)


if __name__ == '__main__':
    unittest.main()
