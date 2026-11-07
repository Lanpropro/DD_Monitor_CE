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
                    DanmakuToggleButton, ElidedLabel, BarIconButton)
assert not any(name in sys.modules for name in (
    'ddm.widgets', 'ddm.player', 'ddm.app', 'ddm.dialogs',
    'PySide6.QtWebEngineWidgets', 'mpv'))
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exports_reuse_original_classes_and_keep_old_imports(self):
        from ddm import avatar_widgets, motion, widgets
        from ddm.ui import primitives
        for name in ('ElidedLabel', 'BarIconButton', '_repolish'):
            self.assertIs(getattr(widgets, name), getattr(primitives, name))
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

    def test_elided_label_recovers_full_text_after_resize_and_update(self):
        parent = QWidget()
        label = ui.ElidedLabel('一段用于验证标签缩放后恢复的完整标题', parent)
        parent.show()
        label.resize(65, 25)
        label.show()
        self.app.processEvents()
        hint = label.sizeHint()
        self.assertNotEqual(label.text(), label._full_text)
        label.resize(hint.width() + 20, 25)
        self.app.processEvents()
        self.assertEqual(label.text(), label._full_text)
        label.setText('更新标题')
        self.assertEqual(label.text(), '更新标题')
        label.setText('')
        self.assertEqual(label.text(), '')
        self.assertIs(label.parentWidget(), parent)
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_bar_icon_button_preserves_mode_click_and_parent_lifetime(self):
        parent = QWidget()
        destroyed = []
        for kind in ('check', 'sort'):
            button = ui.BarIconButton('操作', kind, parent)
            self.assertIs(button.parentWidget(), parent)
            button.destroyed.connect(lambda: destroyed.append(True))
            clicked = []
            button.clicked.connect(lambda: clicked.append(True))
            button.set_icon_mode(True)
            self.assertEqual(button.text(), '')
            button.resize(32, 32)
            for mode in ('dark', 'light', 'dark'):
                theme.apply(mode)
                self.assertFalse(button.grab().isNull())
            QTest.mouseClick(button, Qt.LeftButton)
            self.assertEqual(clicked, [True])
            button.set_icon_mode(False)
            self.assertEqual(button.text(), '操作')
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(len(destroyed), 2)

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


if __name__ == '__main__':
    unittest.main()
