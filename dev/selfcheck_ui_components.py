"""Shared component imports, original identities and settings integration; no user data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from ddm import config, theme, ui


class ComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_lightweight_imports_do_not_load_player_browser_or_app(self):
        code = '''
import sys
from ddm.ui import (ActionButton, Avatar, AnimatedDialog, TileButton, VolumeButton,
                    RecordingButton, SidebarToggleButton, PauseButton, RefreshButton,
                    DanmakuToggleButton, ToggleSwitch, SegmentedControl, SelectControl)
assert not any(name in sys.modules for name in (
    'ddm.widgets', 'ddm.player', 'ddm.app', 'ddm.dialogs',
    'PySide6.QtWebEngineWidgets', 'mpv'))
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exports_reuse_original_classes_and_keep_old_imports(self):
        from ddm import avatar_widgets, motion, widgets
        for module, names in (
                (avatar_widgets, ('Avatar', 'RoomStrip', 'PinnedArc', 'circular_pixmap')),
                (motion, ('AnimatedDialog', 'AnimatedMenu', 'SlidingTabs', 'SettingsStack')),
                (widgets, ('TileButton', 'VolumeButton', 'RecordingButton', 'SidebarToggleButton',
                           'PauseButton', 'RefreshButton', 'DanmakuToggleButton', 'ElidedLabel', 'BarIconButton'))):
            for name in names:
                with self.subTest(name=name):
                    self.assertIs(getattr(ui, name), getattr(module, name))
                    self.assertIn(name, dir(ui))
        with self.assertRaises(AttributeError):
            getattr(ui, 'UnknownComponent')

    def test_action_button_keeps_qt_signals_parent_and_style_role(self):
        parent = QWidget()
        button = ui.ActionButton('继续', parent)
        self.assertIs(button.parentWidget(), parent)
        self.assertIsInstance(button, QPushButton)
        self.assertEqual(button.objectName(), 'IconButton')
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(clicked, [True])
        button.setEnabled(False)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(clicked, [True])
        parent.close()

    def test_headers_and_step_buttons_keep_existing_settings_contract(self):
        from ddm import dialogs
        self.assertIs(dialogs._page_head, ui.page_header)
        self.assertIs(dialogs._step_button, ui.step_button)
        page = QWidget()
        header = ui.page_header('标题', '说明')
        page.setLayout(header)
        self.assertIsInstance(header.itemAt(0).widget(), ui.TitleLabel)
        self.assertEqual(header.itemAt(0).widget().objectName(), 'SettingsTitle')
        self.assertEqual(header.itemAt(1).widget().objectName(), 'SettingsHint')
        self.assertTrue(header.itemAt(1).widget().wordWrap())
        empty = QWidget()
        empty.setLayout(ui.page_header('只有标题', ''))
        self.assertEqual(empty.layout().count(), 1)
        changes = []
        button = ui.step_button('+', '增加', lambda: changes.append(1))
        header.addWidget(button)
        button.click()
        self.assertEqual(changes, [1])
        self.assertEqual(button.objectName(), 'StepButton')
        self.assertEqual((button.width(), button.height()), (28, 28))
        page.close()
        empty.close()

    def test_real_pages_use_shared_controls_and_follow_theme(self):
        from ddm.data_settings import DataSettingsPage
        with tempfile.TemporaryDirectory(prefix='ddm-ui-components-') as root, \
                patch.object(config, 'DATA_ROOT', root):
            page = DataSettingsPage()
            self.assertIsInstance(page.open_button, ui.ActionButton)
            self.assertIsInstance(page.move_button, ui.ActionButton)
            self.assertIsInstance(page.status, ui.HintLabel)
            self.assertIsInstance(page.image_cache.selected_button, ui.ActionButton)
            self.assertIsInstance(page.image_cache.status, ui.HintLabel)
            for mode in ('dark', 'light', 'dark'):
                theme.apply(mode)
                page.ensurePolished()
                self.assertEqual(page.open_button.objectName(), 'IconButton')
                self.assertEqual(page.image_cache.status.objectName(), 'SettingsHint')
                self.assertEqual(page.image_cache.root, root)
            page.close()


    def test_switch_preserves_mouse_keyboard_disabled_and_legacy_behavior(self):
        from ddm.dialogs import NotificationSwitch
        parent = QWidget()
        box = QVBoxLayout(parent)
        switch = ui.ToggleSwitch('Enable', parent)
        old = NotificationSwitch('Legacy', parent)
        box.addWidget(switch)
        box.addWidget(old)
        parent.show()
        self.app.processEvents()
        try:
            self.assertIsInstance(old, ui.ToggleSwitch)
            self.assertIs(switch.parentWidget(), parent)
            self.assertEqual(switch.accessibleName(), 'Enable')
            events = []
            switch.toggled.connect(events.append)
            QTest.mouseClick(switch, Qt.LeftButton)
            QTest.keyClick(switch, Qt.Key_Space)
            self.assertEqual(events, [True, False])
            switch.setEnabled(False)
            QTest.mouseClick(switch, Qt.LeftButton)
            QTest.keyClick(switch, Qt.Key_Space)
            self.assertEqual(events, [True, False])
            old.setChecked(True)
            for mode in ('dark', 'light', 'dark'):
                theme.apply(mode)
                self.app.processEvents()
                self.assertTrue(old.isChecked())
                self.assertEqual(old.size(), switch.size())
                self.assertFalse(old.grab().isNull())
        finally:
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_segmented_control_exclusivity_keyboard_signals_and_disabled_options(self):
        parent = QWidget()
        box = QVBoxLayout(parent)
        control = ui.SegmentedControl((('a', 'First'), ('b', 'Second'), ('c', 'Third')), parent=parent)
        box.addWidget(control)
        parent.resize(400, 80)
        parent.show()
        self.app.processEvents()
        try:
            events = []
            control.valueChanged.connect(events.append)
            QTest.mouseClick(control.buttons['b'], Qt.LeftButton)
            QTest.mouseClick(control.buttons['b'], Qt.LeftButton)
            self.assertEqual(events, ['b'])
            self.assertEqual(control.value(), 'b')
            QTest.keyClick(control.buttons['b'], Qt.Key_Right)
            self.assertEqual(control.value(), 'c')
            control.setValue('a')
            control.setValue('a')
            self.assertEqual(events, ['b', 'c', 'a'])
            control.buttons['b'].setEnabled(False)
            QTest.mouseClick(control.buttons['b'], Qt.LeftButton)
            self.assertEqual(control.value(), 'a')
            control.buttons['a'].setFocus(Qt.TabFocusReason)
            self.app.processEvents()
            QTest.keyClick(control.buttons['a'], Qt.Key_Right)
            self.assertEqual(control.value(), 'c')
            self.assertEqual(sum(button.isChecked() for button in control.buttons.values()), 1)
            self.assertTrue(control.buttons['a'].isVisible())
            self.assertEqual(control.height(), theme.CONTROL_HEIGHT)
            for width in (240, 460):
                parent.resize(width, 80)
                self.app.processEvents()
                self.assertEqual(control.value(), 'c')
                for button in control.buttons.values():
                    self.assertLessEqual(button.geometry().right(), control.width())
                    self.assertGreaterEqual(button.height(), 24)
        finally:
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_segmented_surface_and_selection_follow_theme_without_extra_paint(self):
        from ddm import continuous_corners
        control = ui.SegmentedControl((('a', 'First'), ('b', 'Second')))
        control.resize(320, theme.CONTROL_HEIGHT)
        control.show()
        destroyed = []
        snapshots = []
        control.destroyed.connect(lambda: destroyed.append(True))
        try:
            for mode in ('dark', 'light', 'dark'):
                theme.apply(mode)
                self.app.processEvents()
                image = control.grab().toImage()
                with patch.object(continuous_corners, '_paint'):
                    self.assertEqual(image, control.grab().toImage())
                snapshots.append(image)
                self.assertEqual(control.value(), 'a')
        finally:
            control.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(destroyed, [True])
        self.assertNotEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0], snapshots[2])


    def test_selected_segment_has_a_raised_surface_in_both_themes(self):
        control = ui.SegmentedControl((('a', 'First'), ('b', 'Second')), 'b')
        control.resize(320, theme.CONTROL_HEIGHT)
        control.show()
        try:
            for mode in ('dark', 'light'):
                theme.apply(mode)
                self.app.processEvents()
                image = control.buttons['b'].grab().toImage()
                scale = image.devicePixelRatio()
                top = image.pixelColor(image.width() // 2, round(4 * scale))
                bottom = image.pixelColor(image.width() // 2, image.height() - round(4 * scale))
                self.assertGreater(top.lightnessF(), bottom.lightnessF())
                self.assertEqual(control.value(), 'b')
        finally:
            control.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_select_popup_keeps_layout_and_native_keyboard_commit_cancel(self):
        parent = QWidget()
        box = QVBoxLayout(parent)
        select = ui.SelectControl(parent)
        select.setAccessibleName('Decode mode')
        for label, value in (('Automatic', 'auto'), ('Compatible', 'copy'), ('CPU', 'cpu')):
            select.addItem(label, value)
        box.addWidget(select)
        parent.resize(300, 100)
        parent.show()
        self.app.processEvents()
        events = []
        select.currentIndexChanged.connect(events.append)
        try:
            before = parent.size()
            select.showPopup()
            self.app.processEvents()
            self.assertTrue(select.view().isVisible())
            self.assertIsNot(select.view().window(), parent)
            self.assertEqual(parent.size(), before)
            self.assertEqual(select.height(), theme.CONTROL_HEIGHT)
            QTest.keyClick(select.view(), Qt.Key_Down)
            QTest.keyClick(select.view(), Qt.Key_Return)
            self.app.processEvents()
            self.assertEqual(select.currentData(), 'copy')
            self.assertEqual(events, [1])
            self.assertFalse(select.view().isVisible())
            select.showPopup()
            QTest.keyClick(select.view(), Qt.Key_Down)
            QTest.keyClick(select.view(), Qt.Key_Escape)
            self.app.processEvents()
            self.assertEqual(select.currentData(), 'copy')
            self.assertEqual(events, [1])
            select.setEnabled(False)
            QTest.mouseClick(select, Qt.LeftButton)
            self.assertFalse(select.view().isVisible())
            for mode in ('dark', 'light', 'dark'):
                theme.apply(mode)
                self.assertEqual(select.currentData(), 'copy')
                self.assertFalse(select.grab().isNull())
            select.setEnabled(True)
            select.showPopup()
            self.app.processEvents()
            self.assertTrue(select.view().isVisible())
        finally:
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertIsNone(QApplication.activePopupWidget())


if __name__ == '__main__':
    unittest.main()
