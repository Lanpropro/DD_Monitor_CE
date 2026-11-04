"""Playback controls: imports, Qt ownership and interaction; no media or user data."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from shiboken6 import isValid
from ddm import motion, theme, ui


class PlaybackControlTests(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.setLayout(QVBoxLayout())
        self.addCleanup(self.dispose_owner)

    def dispose_owner(self):
        if isValid(self.owner):
            self.owner.close()
            self.owner.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_public_controls_import_without_player_or_widgets(self):
        code = '''
import sys
from ddm.ui import (TileButton, VolumeButton, RecordingButton, SidebarToggleButton,
                    PauseButton, RefreshButton, DanmakuToggleButton)
assert not any(name in sys.modules for name in (
    'ddm.widgets', 'ddm.player', 'ddm.app', 'ddm.video_surface',
    'PySide6.QtWebEngineWidgets', 'mpv'))
'''
        result = subprocess.run([sys.executable, '-c', code],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_exports_are_the_same_classes_and_helpers(self):
        from ddm import playback_controls, widgets
        for name in ('TileButton', 'VolumeButton', 'RecordingButton', 'SidebarToggleButton',
                     'PauseButton', 'RefreshButton', 'DanmakuToggleButton'):
            with self.subTest(name=name):
                self.assertIs(getattr(ui, name), getattr(playback_controls, name))
                self.assertIs(getattr(widgets, name), getattr(playback_controls, name))
        for name in ('VolumePopup', '_icon_color', '_draw_arrow_head'):
            self.assertIs(getattr(widgets, name), getattr(playback_controls, name))

    def test_click_keyboard_disabled_and_qt_parent(self):
        button = ui.TileButton('Play', self.owner)
        self.owner.layout().addWidget(button)
        button.setProperty('tileButton', True)
        self.owner.show()
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(button, Qt.Key_Space)
        self.assertEqual(clicked, [True])
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(clicked, [True, True])
        self.assertFalse(button._keyboard_focus)
        button.setEnabled(False)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(clicked, [True, True])
        self.assertIs(button.parentWidget(), self.owner)

    def test_volume_wheel_clamps_emits_and_keeps_channel(self):
        button = ui.VolumeButton(self.owner)
        changed = []
        button.volumeChanged.connect(changed.append)
        for initial, delta, expected in ((98, 120, 100), (2, -120, 0), (0, 120, 5)):
            button.set_state(False, initial, button.CHANNEL_LEFT)
            event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, delta),
                                Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
            QCoreApplication.sendEvent(button, event)
            self.assertEqual(button.level, expected)
            self.assertEqual(button.muted, expected == 0)
            self.assertEqual(button.audio_channel, button.CHANNEL_LEFT)
            self.assertIn('声道：左', button.toolTip())
        self.assertEqual(changed, [100, 0, 5])
        button.set_state(True, 200, button.CHANNEL_RIGHT)
        self.assertEqual(button.level, 100)
        self.assertIn('声道：右', button.toolTip())
        self.assertIn('取消静音', button.toolTip())

    def test_pause_orientation_and_toggle_states(self):
        pause = ui.PauseButton(self.owner)
        pause.set_paused(True)
        self.assertTrue(pause.paused)
        self.assertEqual(pause.toolTip(), '继续播放')
        pause.set_paused(False)
        self.assertEqual(pause.toolTip(), '暂停这一路')
        sidebar = ui.SidebarToggleButton(self.owner)
        for portrait, collapsed, text in ((False, False, '«'), (False, True, '»'),
                                           (True, False, ''), (True, True, '')):
            sidebar.set_orientation(portrait, collapsed)
            self.assertEqual(sidebar.text(), text)
        danmaku = ui.DanmakuToggleButton('弹', self.owner)
        danmaku.setCheckable(True)
        QTest.mouseClick(danmaku, Qt.LeftButton)
        self.assertTrue(danmaku.isChecked())

    def test_refresh_animation_hides_resumes_and_dies_with_owner(self):
        button = ui.RefreshButton(self.owner)
        self.owner.layout().addWidget(button)
        animation = button._spin
        self.assertIs(animation.parent(), button)
        with patch.object(motion, 'enabled', return_value=True):
            button.set_refreshing(True)
            self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
            self.owner.show()
            self.assertEqual(animation.state(), QAbstractAnimation.Running)
            animation.setCurrentTime(250)
            self.assertGreater(button._angle, 0)
            button.hide()
            self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
            button.show()
            self.assertEqual(animation.state(), QAbstractAnimation.Running)
            button.set_refreshing(False)
            self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
            self.assertEqual(button._angle, 0)
        with patch.object(motion, 'enabled', return_value=False):
            button.set_refreshing(True)
            self.assertEqual(animation.state(), QAbstractAnimation.Stopped)
        self.owner.close()
        self.owner.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(button))
        self.assertFalse(isValid(animation))

    def test_controls_paint_states_in_both_themes_and_multiple_scales(self):
        from ddm.playback_controls import VolumePopup
        buttons = [ui.VolumeButton(self.owner), ui.PauseButton(self.owner),
                   ui.RecordingButton('REC', self.owner), ui.RefreshButton(self.owner),
                   ui.DanmakuToggleButton('弹', self.owner), ui.SidebarToggleButton(self.owner)]
        for button in buttons:
            self.owner.layout().addWidget(button)
        buttons[0].set_state(True, 0)
        buttons[1].set_paused(True)
        buttons[2].setProperty('replayOnly', True)
        buttons[3].set_refreshing(True)
        buttons[4].setCheckable(True)
        buttons[4].setChecked(True)
        buttons[5].set_orientation(True, False)
        popup = VolumePopup(self.owner, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        popup.setObjectName('TileVolumePopup')
        popup.setFixedSize(180, 38)
        self.assertIs(popup.parentWidget(), self.owner)
        self.assertTrue(popup.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            QApplication.instance().setStyleSheet(theme.qss())
            for button in [*buttons, popup]:
                button.ensurePolished()
                button.resize(button.sizeHint().expandedTo(button.minimumSize()))
                for scale in (1, 1.5, 2):
                    with self.subTest(mode=mode, control=type(button).__name__, scale=scale):
                        image = QImage(round(button.width() * scale), round(button.height() * scale),
                                       QImage.Format_ARGB32_Premultiplied)
                        image.setDevicePixelRatio(scale)
                        image.fill(Qt.transparent)
                        painter = QPainter(image)
                        button.render(painter, QPoint())
                        painter.end()
                        self.assertTrue(any(image.constBits()))


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    unittest.main()
