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
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter, QWheelEvent
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
            page.theme_editor.font_size.setValue(17)
            material = page.material_editor
            material.controls['settings_glass_enabled'].setChecked(True)
            material.controls['settings_segment_motion'].setChecked(True)
            material.set_values({**material.values(), 'settings_glass_blur': 13})
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
            self.assertEqual(settings['appearance_font_size'], 17)
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
            self.assertEqual(page.theme_editor.font_size.value(), 17)
            for key in ('settings_glass_enabled', 'settings_segment_motion'):
                switch = page.material_editor.controls[key]
                self.assertTrue(switch.isChecked())
                self.assertEqual(switch._position, 1., 'Reloaded enabled values must also paint as enabled')
            self.assertEqual(page.material_editor.values()['settings_glass_blur'], 13)
            self.assertEqual(page.material_editor.sliders['settings_glass_opacity'][0].value(), 52)
            page.material_editor.card_layout.setCurrentIndex(0)
            settle()
            self.assertEqual(page.sections.columns, 2)
        finally:
            dispose(reopened)

    def test_live_glass_uses_alpha_not_wallpaper_and_keeps_window_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wallpaper.png'
            image = QImage(200, 200, QImage.Format_RGB32)
            image.fill(QColor('red'))
            image.save(str(path))
            window = SettingsWindow()
            window.resize(400, 240)
            window.show()
            try:
                hwnd = int(window.winId())
                for mode in ('dark', 'light'):
                    theme.apply(mode)
                    with patch('ddm.settings_window.apply_blur', return_value=True):
                        window.set_material(dict(settings_glass_enabled=True, settings_glass_opacity=20,
                                                 settings_backdrop_path=str(path)))
                        surface = window.grab().toImage()
                        color = surface.pixelColor(surface.width() // 2, surface.height() // 2)
                        self.assertAlmostEqual(color.alpha(), 51, delta=1)
                        self.assertNotEqual(color.name(), '#ff0000')
                        window.set_material({'settings_glass_enabled': True, 'settings_glass_opacity': 80})
                        opaque = window.grab().toImage()
                        self.assertGreater(opaque.pixelColor(200, 180).alpha(), color.alpha())
                    with patch('ddm.settings_window.apply_blur', return_value=False):
                        window.set_material({'settings_glass_enabled': True, 'settings_glass_opacity': 0})
                        self.assertEqual(window.grab().toImage().pixelColor(200, 180).alpha(), 255)
                    self.assertEqual(int(window.winId()), hwnd)
                    self.assertTrue(window.isVisible())
                    self.assertEqual(window.windowOpacity(), 1)
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
                self.assertTrue(control.buttons['c']._pointer_focus)
                self.assertEqual(control.value(), 'c')
                self.assertEqual(control._indicator_animation.state(), QAbstractAnimation.Running)
                QTest.qWait(40)
                interrupted = control._indicator
                QTest.mouseClick(control.buttons['a'], Qt.LeftButton)
                self.assertEqual(control._indicator_animation.startValue(), interrupted)
                control.buttons['b'].setFocus()
                QTest.keyClick(control.buttons['b'], Qt.Key_Space)
                self.assertEqual(control.value(), 'b')
                self.assertFalse(control.buttons['b']._pointer_focus)
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
                self.assertEqual(editor.gallery.count(), 3)
                item = editor.gallery.item(1)
                self.assertEqual(editor.gallery.visualItemRect(editor.gallery.item(0)).size(),
                                 editor.gallery.visualItemRect(item).size())
                self.assertIs(editor.choose, editor.gallery.import_button)
                self.assertEqual(editor.gallery.visualItemRect(item).size(), editor.choose.size())
                self.assertGreater(editor.gallery.gridSize().width(), editor.gallery.gridSize().height())
                self.assertIn('默认背景', editor.gallery.item(0).toolTip())
                self.assertIn(str(folder.resolve()), editor.gallery_folder.toolTip())
                self.assertIn('类型：图片', item.toolTip())
                self.assertIn(str((folder / 'fixture.png').resolve()), item.toolTip())
                with patch('PySide6.QtGui.QDesktopServices.openUrl', return_value=True) as open_folder:
                    editor.gallery_folder.click()
                    self.assertEqual(Path(open_folder.call_args.args[0].toLocalFile()), folder.resolve())
                QTest.mouseClick(editor.gallery.viewport(), Qt.LeftButton,
                                 pos=editor.gallery.visualItemRect(item).center())
                self.assertEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
                self.assertEqual(len(list(folder.iterdir())), 1)
                self.assertIsNotNone(controller.layer.image)
                with patch('ddm.skin_settings.QFileDialog.getOpenFileName', return_value=('', '')) as picker:
                    QTest.mouseClick(editor.choose, Qt.LeftButton)
                    self.assertEqual(picker.call_count, 1)
                    self.assertFalse(editor.choose.hasFocus())
                self.assertEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
                choose = editor.choose
                editor.gallery.refresh()
                settle()
                self.assertIs(editor.gallery.import_button, choose)
                self.assertTrue(choose.isVisible())
                self.assertEqual(editor.gallery.currentItem().data(Qt.UserRole), 'utils/skins/fixture.png')
                with patch('ddm.skin_settings.QFileDialog.getOpenFileName', return_value=(str(folder / 'fixture.png'), '')):
                    QTest.mouseClick(choose, Qt.LeftButton)
                    for _ in range(100):
                        if editor.job is None:
                            break
                        QTest.qWait(20)
                self.assertIsNone(editor.job)
                self.assertEqual(editor.gallery.count(), 4)
                self.assertIs(editor.gallery.import_button, choose)
                self.assertNotEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
                self.assertTrue((Path(directory) / owner.settings['skin_background']).is_file())
                self.assertEqual(editor.gallery.currentItem().data(Qt.UserRole), owner.settings['skin_background'])
                editor._select_background('utils/skins/fixture.png')
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
                self.assertFalse(choose.isEnabled())
                editor._select_background('')
                self.assertEqual(owner.settings['skin_background'], 'utils/skins/fixture.png')
            finally:
                dispose(editor)
                controller.stop()
                dispose(owner)

    def test_gallery_covers_thumbnail_and_keeps_import_drop_contract(self):
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtGui import QDragEnterEvent, QDropEvent
        from PySide6.QtTest import QSignalSpy
        from ddm.skin_gallery import SkinGallery
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'REPO', directory):
            folder = Path(directory) / 'utils/skins'
            folder.mkdir(parents=True)
            image = QImage(100, 300, QImage.Format_RGB32)
            image.fill(QColor('#cc2222'))
            painter = QPainter(image)
            painter.fillRect(0, 100, 100, 100, QColor('#229944'))
            painter.end()
            source = folder / 'portrait.png'
            image.save(str(source))
            (folder / 'video.mp4').write_bytes(b'gallery listing fixture')
            gallery = SkinGallery()
            gallery.resize(480, gallery.height())
            gallery.show()
            settle()
            try:
                self.assertEqual(gallery.count(), 4)
                self.assertEqual(gallery.item(2).data(Qt.UserRole + 1), '视频')
                self.assertEqual(gallery.visualItemRect(gallery.item(2)).size(), gallery.import_button.size())
                for mode in ('dark', 'light'):
                    theme.apply(mode)
                    gallery.setStyleSheet(theme.qss())
                    settle()
                    rect = gallery.visualItemRect(gallery.item(1))
                    rendered = gallery.viewport().grab().toImage()
                    dpr = rendered.devicePixelRatio()
                    for point in (rect.topLeft() + QPoint(12, 12), rect.bottomRight() - QPoint(12, 12)):
                        self.assertEqual(rendered.pixelColor(round(point.x() * dpr), round(point.y() * dpr)).name(), '#229944')
                    QTest.mouseClick(gallery.viewport(), Qt.LeftButton, pos=rect.center())
                    rendered = gallery.viewport().grab().toImage()
                    self.assertEqual(rendered.pixelColor(round((rect.left() + 4) * dpr),
                                                        round(rect.center().y() * dpr)).name(), theme.qcolor(theme.ACCENT).name())
                mime = QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(source))])
                enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                gallery.import_button.dragEnterEvent(enter)
                self.assertTrue(enter.isAccepted())
                dropped = QSignalSpy(gallery.import_button.fileDropped)
                selected = QSignalSpy(gallery.selected)
                drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                gallery.import_button.dropEvent(drop)
                self.assertTrue(drop.isAccepted())
                self.assertEqual(dropped.count(), 1)
                self.assertEqual(Path(dropped.at(0)[0]), source)
                self.assertEqual(selected.count(), 0)
                self.assertFalse(gallery.import_button.property('dragging'))
                mime.setUrls([QUrl('https://example.invalid/image.png')])
                enter = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                gallery.import_button.dragEnterEvent(enter)
                self.assertFalse(enter.isAccepted())
            finally:
                dispose(gallery)

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

    def test_font_sizes_default_button_and_glass_group_are_readable(self):
        dialog = SettingsDialog(deepcopy(config.DEFAULT_SETTINGS), {}, preview=True)
        dialog.resize(760, 900)
        dialog.show()
        dialog.nav.setCurrentRow(1)
        settle()
        try:
            page = dialog.appearance_page
            for size in (11, 13, 20):
                page.theme_editor.font_size.setValue(size)
                settle()
                self.assertEqual(theme.FONT_CONTROL, size)
                heading = page.sections.section('theme').layout().itemAt(0).widget()
                self.assertEqual(heading.font().pixelSize(), size)
                button = page.theme_editor.swatches['']
                self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance('默认') + 8)
                self.assertGreaterEqual(button.height(), button.fontMetrics().height())
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual(dialog.width(), 760)
            editor = page.material_editor
            for slider, _label in editor.sliders.values():
                self.assertTrue(editor.glass_parameters.isAncestorOf(slider))
                self.assertFalse(slider.isEnabled())
            self.assertNotIn('settings_glass_blur', editor.sliders)
            self.assertIn('当前平台不支持', editor.background_status.text())
            editor.controls['settings_glass_enabled'].setChecked(True)
            self.assertTrue(all(slider.isEnabled() for slider, _label in editor.sliders.values()))
            with patch('ddm.settings_backdrop.blur_available', return_value=True):
                editor._sync_enabled()
                self.assertIn('背后的实时内容', editor.background_status.text())
        finally:
            dispose(dialog)

    def test_header_status_is_quiet_and_vertical_window_is_narrower(self):
        dialog = SettingsDialog(deepcopy(config.DEFAULT_SETTINGS), {}, preview=True)
        dialog.resize(1400, 900)
        dialog.show()
        try:
            for index in (0, 1, 2, 3, 4, 5, 6):
                dialog.nav.setCurrentRow(index)
                settle()
                self.assertTrue(dialog.reset_button.isHidden())
            for state in ('saving', 'saved'):
                dialog._auto_save_status(state, '')
                self.assertTrue(dialog.save_status.isHidden())
            dialog._auto_save_status('error', 'fixture failure')
            self.assertTrue(dialog.save_status.isVisible())
            self.assertTrue(dialog.retry_button.isVisible())
            dialog._auto_save_status('saved', '')
            self.assertTrue(dialog.save_status.isHidden())
            dialog.nav.setCurrentRow(1)
            dialog.appearance_page.material_editor.card_layout.setCurrentIndex(1)
            settle()
            self.assertLessEqual(dialog.width(), 1040)
            self.assertEqual(dialog.appearance_page.sections.columns, 1)
        finally:
            dispose(dialog)

    def test_wheel_changes_only_horizontal_sliders_and_chains_nested_lists(self):
        from PySide6.QtWidgets import QComboBox, QLabel, QListWidget, QScrollArea, QSlider, QSpinBox
        window = SettingsWindow()
        window.resize(620, 450)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        combo = QComboBox()
        combo.addItems(['甲', '乙', '丙'])
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setValue(50)
        horizontal, vertical = QSlider(Qt.Horizontal), QSlider(Qt.Vertical)
        for slider in (horizontal, vertical):
            slider.setRange(0, 100)
            slider.setValue(50)
        nested = QListWidget()
        nested.addItems([str(index) for index in range(30)])
        nested.setFixedHeight(90)
        for widget in (combo, spin, horizontal, vertical, nested):
            layout.addWidget(widget)
        blank = QLabel('页面末尾')
        blank.setMinimumHeight(900)
        layout.addWidget(blank)
        scroll.setWidget(content)
        window.body_layout.addWidget(scroll)
        window.show()
        settle()
        def wheel(widget, delta=-120):
            point = widget.rect().center()
            event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(),
                                QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            APP.sendEvent(widget, event)
            settle()
        try:
            for widget in (combo, spin, spin.lineEdit(), vertical):
                scroll.verticalScrollBar().setValue(0)
                wheel(widget)
                self.assertGreater(scroll.verticalScrollBar().value(), 0)
                self.assertEqual(combo.currentIndex(), 0)
                self.assertEqual(spin.value(), 50)
                self.assertEqual(vertical.value(), 50)
            scroll.verticalScrollBar().setValue(0)
            wheel(horizontal)
            self.assertNotEqual(horizontal.value(), 50)
            self.assertEqual(scroll.verticalScrollBar().value(), 0)
            nested.verticalScrollBar().setValue(nested.verticalScrollBar().maximum())
            wheel(nested.viewport())
            self.assertGreater(scroll.verticalScrollBar().value(), 0)
            scroll.verticalScrollBar().setValue(0)
            nested.verticalScrollBar().setValue(0)
            wheel(nested.viewport())
            self.assertGreater(nested.verticalScrollBar().value(), 0)
            self.assertEqual(scroll.verticalScrollBar().value(), 0)
        finally:
            dispose(window)


if __name__ == '__main__':
    unittest.main()
