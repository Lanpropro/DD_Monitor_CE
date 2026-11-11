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
                    DanmakuToggleButton, ElidedLabel, BarIconButton, ToggleSwitch, SegmentedControl, SelectControl, SettingsSurface, DisclosureButton)
assert not any(name in sys.modules for name in (
    'ddm.widgets', 'ddm.player', 'ddm.app', 'ddm.dialogs',
    'PySide6.QtWebEngineWidgets', 'mpv'))
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_settings_base_colors_match_light_and_dark_video_reference(self):
        from PySide6.QtWidgets import QLineEdit, QSpinBox
        from ddm.settings_window import SettingsWindow
        references = {
            'light': ('#eeedf4', '#ffffff', '#edecef'),
            'dark': ('#33373b', '#3c4044', '#43444b'),
        }
        try:
            for mode, (background, card_color, control_color) in references.items():
                theme.apply(mode)
                for embedded in (False, True):
                    with self.subTest(mode=mode, embedded=embedded):
                        window = QWidget() if embedded else SettingsWindow()
                        if embedded:
                            window.setProperty('settingsGlassContent', True)
                            window.setProperty('settings_glass_enabled', False)
                            box = QVBoxLayout(window)
                            theme.refresh_theme_properties(window)
                        else:
                            window.set_material({'settings_glass_enabled': False})
                            box = window.body_layout
                        window.setAttribute(Qt.WA_DontShowOnScreen)
                        card = ui.SettingsSurface(window)
                        layout = QVBoxLayout(card)
                        layout.setContentsMargins(18, 24, 18, 24)
                        select = ui.SelectControl(card)
                        select.addItem('自动解码')
                        disclosure = ui.DisclosureButton(card)
                        disclosure.setText('编解码')
                        controls = [select, disclosure, QLineEdit('示例', card), QSpinBox(card)]
                        for control in controls:
                            control.setFocusPolicy(Qt.NoFocus)
                            control.setFixedHeight(theme.CONTROL_HEIGHT)
                            layout.addWidget(control)
                        segment = ui.SegmentedControl((('a', 'A'), ('b', 'B')), parent=card)
                        layout.addWidget(segment)
                        box.addWidget(card)
                        window.resize(480, 420)
                        window.show()
                        for _ in range(4):
                            self.app.processEvents()
                        def pixel(widget, x, y):
                            image = widget.grab().toImage()
                            scale = image.devicePixelRatio()
                            return image.pixelColor(round(x * scale), round(y * scale)).name()
                        if not embedded:
                            self.assertEqual(pixel(window, 4, window.height() // 2), background)
                        self.assertEqual(pixel(card, 10, 10), card_color)
                        for control in controls:
                            self.assertEqual(pixel(control, 5, control.height() // 2), control_color,
                                             type(control).__name__)
                        self.assertEqual(pixel(segment, segment.width() // 2, 2), control_color)
                        before = (window.size(), card.geometry())
                        select.showPopup()
                        self.app.processEvents()
                        popup = select.view().window()
                        self.assertEqual(pixel(popup, popup.width() // 2, popup.height() - 6), card_color)
                        self.assertEqual((window.size(), card.geometry()), before)
                        select.hidePopup()
                        outside = QLineEdit('设置外的输入框')
                        outside.resize(240, theme.CONTROL_HEIGHT)
                        self.assertEqual(pixel(outside, 5, outside.height() // 2), theme.qcolor(theme.CONTENT).name())
                        outside.deleteLater()
                        window.close()
                        window.deleteLater()
                        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        finally:
            theme.apply('dark')

    def test_live_card_shadow_does_not_tint_its_translucent_fill(self):
        from ddm.settings_window import SettingsWindow
        window = SettingsWindow()
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.set_material({'settings_glass_enabled': True, 'settings_glass_opacity': 0})
        window.resize(360, 270)
        card = ui.SettingsSurface(window)
        card.setGeometry(24, 80, 300, 160)
        try:
            with patch('ddm.settings_window.apply_blur', return_value=True):
                window.show()
                self.app.processEvents()
                colors = []
                for disabled in (False, True):
                    window.set_material({'settings_glass_enabled': True, 'settings_glass_opacity': 0,
                                         'settings_no_shadows': disabled})
                    surface = card.grab().toImage()
                    colors.append(surface.pixelColor(surface.width() // 2, surface.height() // 2))
                self.assertEqual(colors[0], colors[1], 'Only the outside shadow changes')
                self.assertTrue(window._native_glass)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_glass_groups_follow_reference_surface_contrast_in_both_themes(self):
        from PySide6.QtGui import QColor, QImage, QPainter
        from ddm.settings_window import SettingsWindow
        window = SettingsWindow()
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.set_material({'settings_glass_enabled': True, 'settings_glass_opacity': 68})
        window.resize(360, 270)
        card = ui.SettingsSurface(window)
        card.setGeometry(24, 80, 300, 160)
        try:
            with patch('ddm.settings_window.apply_blur', return_value=True):
                window.show()
                for mode in ('dark', 'light'):
                    theme.apply(mode)
                    self.app.processEvents()
                    surface = window.grab().toImage()
                    composed = QImage(surface.size(), QImage.Format_ARGB32_Premultiplied)
                    composed.fill(QColor('#65686c'))
                    painter = QPainter(composed)
                    painter.drawImage(0, 0, surface)
                    painter.end()
                    ratio = surface.devicePixelRatio()
                    shell = composed.pixelColor(round(12*ratio), round(150*ratio))
                    inside = composed.pixelColor(round(174*ratio), round(150*ratio))
                    if mode == 'dark':
                        self.assertGreater(inside.lightnessF(), shell.lightnessF(),
                                           'The glass group should lift the dark shell, not darken it')
                    else:
                        self.assertLess(inside.lightnessF(), shell.lightnessF())
                    edge = [composed.pixelColor(round(174*ratio), round(y*ratio))
                            for y in (81, 82, 83, 84)]
                    self.assertGreater(max(color.lightnessF() for color in edge), inside.lightnessF(),
                                       'The group retains a fine highlight along its top edge')
                    self.assertEqual(window.property('settings_glass_opacity'), 68)
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            theme.apply('dark')

    def test_switch_restores_silent_values_without_emitting_business_signals(self):
        from PySide6.QtTest import QSignalSpy
        switch = ui.ToggleSwitch('Fixture')
        spy = QSignalSpy(switch.toggled)
        try:
            for checked in (True, False, True):
                previous = switch.blockSignals(True)
                switch.setChecked(checked)
                switch.blockSignals(previous)
                self.assertEqual(switch.isChecked(), checked)
                self.assertEqual(switch._position, float(checked))
            self.assertEqual(spy.count(), 0)
            switch.setChecked(False)
            self.assertEqual(spy.count(), 1)
            self.assertEqual(switch._position, 0.)
        finally:
            switch.deleteLater()

    def test_live_glass_text_contrast_is_local_and_follows_mode(self):
        from PySide6.QtWidgets import QLabel, QGraphicsDropShadowEffect
        from ddm.settings_window import SettingsWindow
        window = SettingsWindow()
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.resize(400, 280)
        card = ui.SettingsSurface(window)
        card.setGeometry(20, 70, 360, 190)
        layout = QVBoxLayout(card)
        label = QLabel('Bright video behind white text')
        label.setObjectName('SettingsHint')
        layout.addWidget(label)
        original = label.sizeHint()
        try:
            with patch('ddm.settings_backdrop.blur_available', return_value=True), \
                    patch('ddm.settings_window.apply_blur', return_value=True):
                theme.apply('dark')
                window.set_material({'settings_glass_enabled': True})
                window.show()
                self.app.processEvents()
                effect = label.graphicsEffect()
                self.assertIsInstance(effect, QGraphicsDropShadowEffect)
                self.assertEqual(effect.objectName(), 'SettingsTextContrast')
                from PySide6.QtGui import QPalette
                self.assertEqual(label.palette().color(QPalette.WindowText).name(), '#d9dde4')
                protected = window.grab().toImage()
                effect.setEnabled(False)
                unprotected = window.grab().toImage()
                effect.setEnabled(True)
                self.assertNotEqual(protected, unprotected, 'The local text halo must actually render')
                self.assertIsNone(card.graphicsEffect())
                self.assertIsNone(window.graphicsEffect())
                self.assertEqual(label.sizeHint(), original)
                theme.apply('light')
                self.assertIsNone(label.graphicsEffect())
                theme.apply('dark')
                self.assertIsInstance(label.graphicsEffect(), QGraphicsDropShadowEffect)
                window.set_material({'settings_glass_enabled': False})
                self.assertIsNone(label.graphicsEffect())
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            theme.apply('dark')

    def test_settings_cards_keep_uniform_fill_and_separate_outer_shadow(self):
        from ddm.settings_window import SettingsWindow
        window = SettingsWindow()
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.set_material({'settings_glass_enabled': False, 'settings_glass_opacity': 0})
        card = ui.SettingsSurface(window)
        card.setGeometry(24, 80, 300, 160)
        window.resize(360, 270)
        window.show()
        try:
            for mode, expected in (('dark', '#3c4044'), ('light', '#ffffff')):
                theme.apply(mode)
                for _ in range(4):
                    self.app.processEvents()
                window.set_material({'settings_no_shadows': False})
                shadow = card.grab().toImage()
                scale = shadow.devicePixelRatio()
                x = shadow.width() // 2
                top = shadow.pixelColor(x, round(12 * scale))
                bottom = shadow.pixelColor(x, shadow.height() - round(14 * scale))
                self.assertEqual(top.name(), expected)
                self.assertEqual(bottom, top, 'A shadow must not fade the card fill from top to bottom')
                under_card = shadow.pixelColor(x, shadow.height() - round(4 * scale))
                window.set_material({'settings_no_shadows': True})
                plain = card.grab().toImage()
                self.assertLess(under_card.lightnessF(),
                                plain.pixelColor(x, plain.height() - round(4 * scale)).lightnessF())
                self.assertEqual(plain.pixelColor(x, round(12 * scale)), top)
                self.assertIsNone(card.graphicsEffect(), 'Draw the shadow without capturing controls')
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            theme.apply('dark')

    def test_exports_reuse_original_classes_and_keep_old_imports(self):
        from ddm import avatar_widgets, motion, widgets
        from ddm.ui import labels, toolbar
        self.assertIs(widgets.ElidedLabel, labels.ElidedLabel)
        self.assertIs(widgets.BarIconButton, toolbar.BarIconButton)
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

    def test_aggregate_keeps_original_qt_subclass_loading_order(self):
        code = '''
import builtins
seen = []
original = builtins.__build_class__
def record(function, name, *bases, **keywords):
    seen.append(name)
    return original(function, name, *bases, **keywords)
builtins.__build_class__ = record
try:
    import ddm.widgets
finally:
    builtins.__build_class__ = original
for before, component, after in (
        ('DanmakuPanel', 'ElidedLabel', 'AccountPopupMenu'),
        ('CarouselScroll', 'BarIconButton', 'AppearanceButton')):
    assert seen.index(before) < seen.index(component) < seen.index(after), seen
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

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


    def test_switch_preserves_mouse_keyboard_disabled_and_legacy_behavior(self):
        from ddm.settings_notifications import NotificationSwitch
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

    def test_switch_mouse_feedback_is_immediate_reversible_and_respects_motion(self):
        from PySide6.QtCore import QAbstractAnimation
        from ddm import motion
        switch = ui.ToggleSwitch('Enable')
        switch.show()
        self.app.processEvents()
        events = []
        switch.toggled.connect(events.append)
        try:
            with patch.object(motion, 'enabled', return_value=True):
                size = switch.size()
                QTest.mouseClick(switch, Qt.LeftButton)
                self.assertTrue(switch.isChecked())
                self.assertEqual(events, [True])
                self.assertEqual(switch._transition.state(), QAbstractAnimation.Running)
                switch._transition.setCurrentTime(80)
                halfway = switch._position
                self.assertNotEqual(halfway, 0.)
                self.assertNotEqual(halfway, 1.)
                QTest.mouseClick(switch, Qt.LeftButton)
                self.assertFalse(switch.isChecked())
                self.assertAlmostEqual(switch._transition.startValue(), halfway)
                switch._transition.setCurrentTime(motion.SWITCH_TRANSITION_MS)
                self.assertEqual(switch._position, 0.)
                QTest.keyClick(switch, Qt.Key_Space)
                self.assertEqual(switch._position, 1.)
                self.assertEqual(switch._transition.state(), QAbstractAnimation.Stopped)
                self.assertEqual(switch.size(), size)
            with patch.object(motion, 'enabled', return_value=False):
                QTest.mouseClick(switch, Qt.LeftButton)
                self.assertEqual(switch._position, 0.)
                self.assertEqual(switch._transition.state(), QAbstractAnimation.Stopped)
            with patch.object(motion, 'enabled', return_value=True):
                QTest.mouseClick(switch, Qt.LeftButton)
                switch.hide()
                self.assertEqual(switch._position, 1.)
                self.assertEqual(switch._transition.state(), QAbstractAnimation.Stopped)
        finally:
            switch.deleteLater()
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

    def test_stepper_keeps_native_numeric_input_limits_and_disabled_state(self):
        from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox
        for factory in (QSpinBox, QDoubleSpinBox):
            spin = factory()
            spin.setRange(1, 3)
            spin.setValue(2)
            spin.setSuffix(' s')
            control = ui.StepperControl(spin)
            control.show()
            self.app.processEvents()
            events = []
            spin.valueChanged.connect(events.append)
            try:
                QTest.mouseClick(control.plus, Qt.LeftButton)
                self.assertEqual(spin.value(), 3)
                self.assertFalse(control.plus.isEnabled())
                QTest.mouseClick(control.minus, Qt.LeftButton)
                spin.setFocus()
                QTest.keyClick(spin, Qt.Key_Down)
                self.assertEqual(spin.value(), 1)
                self.assertFalse(control.minus.isEnabled())
                spin.lineEdit().selectAll()
                QTest.keyClicks(spin.lineEdit(), '2')
                QTest.keyClick(spin, Qt.Key_Return)
                self.assertEqual(spin.value(), 2)
                self.assertTrue(control.minus.isEnabled())
                self.assertEqual(events[:3], [3, 2, 1])
                self.assertTrue(events[3:])
                self.assertTrue(all(value == 2 for value in events[3:]))
                control.setEnabled(False)
                QTest.mouseClick(control.plus, Qt.LeftButton)
                self.assertEqual(spin.value(), 2)
                self.assertFalse(spin.isEnabled())
                for mode in ('light', 'dark'):
                    theme.apply(mode)
                    self.assertFalse(control.grab().isNull())
                    self.assertEqual(spin.value(), 2)
            finally:
                control.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_stepper_selection_is_limited_to_active_edit_and_shadow_is_optional(self):
        from PySide6.QtWidgets import QDoubleSpinBox, QLabel
        from ddm.settings_focus import SettingsInputFocus
        self.addCleanup(theme.apply, theme.mode())
        theme.apply('dark')
        root = QWidget()
        root.setStyleSheet(theme.qss())
        focus = SettingsInputFocus(root)
        layout = QVBoxLayout(root)
        spin = QDoubleSpinBox()
        spin.setRange(-30, -10)
        spin.setValue(-18)
        spin.setSuffix(' LUFS')
        control = ui.StepperControl(spin)
        blank = QLabel('Outside the editor')
        layout.addWidget(control)
        layout.addWidget(blank)
        root.show()
        self.app.processEvents()
        try:
            spin.setFocus()
            spin.lineEdit().selectAll()
            self.assertTrue(spin.lineEdit().hasSelectedText())
            QTest.mouseClick(blank, Qt.LeftButton)
            self.assertFalse(spin.lineEdit().hasSelectedText())
            self.assertFalse(spin.hasFocus())
            spin.lineEdit().selectAll()
            self.assertFalse(spin.lineEdit().hasSelectedText())
            spin.setFocus()
            spin.lineEdit().selectAll()
            QTest.mouseClick(control.plus, Qt.LeftButton)
            self.assertEqual(spin.value(), -17)
            self.assertFalse(spin.lineEdit().hasSelectedText())
            self.assertTrue(spin.lineEdit().font().bold())
            self.assertEqual(spin.lineEdit().palette().text().color().name(), theme.qcolor(theme.TEXT1).name())
            first = control.grab().toImage()
            root.setProperty('settings_no_shadows', True)
            second = control.grab().toImage()
            self.assertNotEqual(first, second)
            self.assertEqual(first.size(), second.size())
            with patch('ddm.motion.enabled', return_value=False):
                control._transition_hover(1.)
                self.assertEqual(control._hover, 1.)
            control.hide()
            self.assertEqual(control._hover, 0.)
        finally:
            root.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_curve_editor_has_distinct_panel_plot_grid_and_white_nodes(self):
        from ddm.settings_material import BASE_COLORS
        root = QWidget()
        root.setProperty('settingsGlassWindow', True)
        curve = ui.ScaleCurveControl(parent=root)
        QVBoxLayout(root).addWidget(curve)
        root.resize(400, 310)
        root.show()
        self.app.processEvents()
        before = curve.curve()
        self.addCleanup(theme.apply, theme.mode())
        try:
            for mode in ('dark', 'light'):
                theme.apply(mode)
                self.app.processEvents()
                graph = curve.graph
                picture = graph.grab().toImage()
                scale = picture.devicePixelRatio()
                def pixel(x, y):
                    return picture.pixelColor(round(x * scale), round(y * scale)).name()
                colors = BASE_COLORS[mode == 'light']
                self.assertEqual(pixel(2, 30), colors['control'])
                plot = graph.plot_rect()
                self.assertEqual(pixel(plot.left() + 3, plot.top() + 3), colors['card'])
                self.assertNotEqual(pixel(plot.left() + plot.width()/2, plot.top() + 3), colors['card'])
                point = graph.point_position(graph.points[0])
                self.assertEqual(pixel(point.x(), point.y()), '#ffffff')
                self.assertEqual(curve.curve(), before)
        finally:
            root.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_font_selector_preserves_family_api_and_emits_edits(self):
        from PySide6.QtGui import QFont
        from PySide6.QtTest import QSignalSpy
        from ddm.ui import FontSelectControl, SelectControl
        with patch('ddm.ui.select.QFontDatabase.families', return_value=['Arial', 'Consolas']):
            control = FontSelectControl()
        try:
            self.assertIsInstance(control, SelectControl)
            self.assertGreater(control.count(), 0)
            spy = QSignalSpy(control.currentFontChanged)
            family = control.itemText(control.count() - 1)
            control.setCurrentFont(QFont(family))
            self.assertEqual(control.currentFont().family(), family)
            self.assertGreater(spy.count(), 0)
        finally:
            control.deleteLater()

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

    def test_selectors_keep_content_width_in_wide_layouts(self):
        parent = QWidget()
        box = QVBoxLayout(parent)
        segments = ui.SegmentedControl((('a', 'H.264'), ('b', 'HEVC'), ('c', 'AV1')))
        select = ui.SelectControl()
        for label, value in config.DECODE_MODES:
            select.addItem(label, value)
        box.addWidget(segments)
        box.addWidget(select)
        parent.show()
        try:
            widths = []
            for width in (640, 900):
                parent.resize(width, 150)
                self.app.processEvents()
                widths.append((segments.width(), select.width()))
                self.assertLess(segments.width(), 320)
                self.assertLess(select.width(), 340)
                for button in segments.buttons.values():
                    self.assertGreaterEqual(button.width(), button.sizeHint().width())
                self.assertGreaterEqual(select.width() - 46, max(
                    select.fontMetrics().horizontalAdvance(select.itemText(i)) for i in range(select.count())))
            self.assertEqual(widths[0], widths[1])
        finally:
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_disclosure_keeps_rounded_corners_during_focus_and_press(self):
        parent = QWidget()
        box = QVBoxLayout(parent)
        button = ui.DisclosureButton()
        button.setObjectName('IconButton')
        button.setText('编解码设置')
        box.addWidget(button)
        parent.resize(360, 100)
        parent.show()
        try:
            for mode in ('dark', 'light'):
                theme.apply(mode)
                button.setFocus()
                self.app.processEvents()
                before = button.geometry()
                idle = button.grab().toImage()
                QTest.mousePress(button, Qt.LeftButton)
                self.app.processEvents()
                held = button.grab().toImage()
                self.assertEqual(button.geometry(), before)
                scale = held.devicePixelRatio()
                self.assertEqual(held.pixelColor(round(scale), round(scale)),
                                 idle.pixelColor(round(scale), round(scale)))
                QTest.mouseRelease(button, Qt.LeftButton)
                self.assertEqual(button.height(), theme.CONTROL_HEIGHT)
                self.assertTrue(button.property('customControlSurface'))
                self.assertFalse(button.autoDefault())
                button.setChecked(False)
        finally:
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_settings_material_uses_cached_backdrop_and_keeps_children_sharp(self):
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QLabel
        from ddm.ui.settings_surface import _frosted_image
        from ddm import skin_parts
        with tempfile.TemporaryDirectory(prefix='ddm-settings-glass-') as root:
            image = QImage(400, 240, QImage.Format_RGB32)
            image.fill(QColor('#cc573c'))
            for x in range(200, 400):
                for y in range(240):
                    image.setPixelColor(x, y, QColor('#287ecb'))
            path = str(Path(root) / 'background.png')
            image.save(path)
            parent = QWidget()
            parent.setProperty('skinPart', 'settings.content')
            parent.resize(400, 240)
            card = ui.SettingsSurface(parent)
            card.setGeometry(20, 20, 360, 200)
            label = QLabel('Clear text', card)
            label.move(20, 70)
            parent.show()
            _frosted_image.cache_clear()
            try:
                with patch.object(skin_parts, 'values_for', return_value={'image': path}):
                    for mode in ('dark', 'light'):
                        theme.apply(mode)
                        self.app.processEvents()
                        before = _frosted_image.cache_info().misses
                        first = card.grab().toImage()
                        self.assertEqual(first, card.grab().toImage())
                        self.assertEqual(_frosted_image.cache_info().misses, before)
                        scale = first.devicePixelRatio()
                        left = first.pixelColor(round(60 * scale), round(150 * scale))
                        right = first.pixelColor(round(300 * scale), round(150 * scale))
                        self.assertGreater(left.red(), right.red())
                        self.assertGreater(right.blue(), left.blue())
                        self.assertIsNone(card.graphicsEffect())
                        self.assertIsNone(label.graphicsEffect())
                    with patch.object(card, 'update') as refresh:
                        parent.resize(440, 240)
                        self.app.processEvents()
                        refresh.assert_called()
                    self.assertEqual(_frosted_image.cache_info().misses, 1)
                    # A separate opaque content background blocks the outer wallpaper.
                    with patch.object(skin_parts, 'values_for', return_value={'background': '#333333'}):
                        self.assertIsNone(card._backdrop())
                        parent._settings_material_preview = ({'settings.content': {'image': path}}, theme.is_light())
                        self.assertIs(card._backdrop()[0], parent)
                        del parent._settings_material_preview
            finally:
                parent.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                _frosted_image.cache_clear()


if __name__ == '__main__':
    unittest.main()
