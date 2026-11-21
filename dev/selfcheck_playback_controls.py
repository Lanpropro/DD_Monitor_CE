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

    def test_zero_volume_draws_mute_icon_without_changing_explicit_mute(self):
        from ddm.tile_widgets import Tile
        tile = Tile({'room_id': 'fixture', 'volume': 40, 'muted': False}, self.owner)
        button = tile.volume_button
        tile.set_volume(0)
        self.assertFalse(tile.muted)
        self.assertFalse(button.muted)
        silent = button.grab().toImage()
        tile.set_muted(True)
        self.assertEqual(button.grab().toImage(), silent)
        tile.set_volume(40)
        self.assertFalse(tile.muted)
        self.assertNotEqual(button.grab().toImage(), silent)

    def test_selected_volume_channels_keep_theme_blue_over_video(self):
        from unittest.mock import Mock

        button = ui.VolumeButton(self.owner)
        button.setProperty('tileButton', True)
        button.setProperty('overVideo', True)
        for hovered in (False, True):
            button.setProperty('hovered', hovered)
            for channel, selected in ((0, (True, True)), (button.CHANNEL_LEFT, (True, False)),
                                      (button.CHANNEL_RIGHT, (False, True))):
                button.set_state(False, 40, channel)
                painter = Mock()
                button._paint_channel(painter, 0, 0)
                colors = tuple(call.args[1] for call in painter.fillPath.call_args_list)
                self.assertEqual(tuple(color == theme.qcolor(theme.ACCENT) for color in colors), selected)

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

    def test_tile_audio_sync_updates_all_controls_without_audio_signals(self):
        from ddm.tile_widgets import Tile
        tile = Tile({'room_id': 'fixture'}, self.owner)
        self.owner.layout().addWidget(tile)
        signals = []
        tile.muteToggled.connect(lambda *_: signals.append('mute'))
        tile.volumeChanged.connect(lambda *_: signals.append('volume'))
        for muted, volume, channel in ((True, 25, 3), (False, 70, 4)):
            tile.muted, tile.volume, tile.audio_channel = muted, volume, channel
            tile.sync_audio_ui()
            self.assertEqual((tile.volume_button.muted, tile.volume_button.level,
                              tile.volume_button.audio_channel), (muted, volume, channel))
            self.assertEqual(tile.volume_slider.value(), volume)
            self.assertEqual(tile.vertical_volume.value(), volume)
            self.assertEqual(tile.volume_label.text(), str(volume))
        self.assertFalse(signals)

    def test_host_swap_keeps_actual_volume_icons_in_sync_with_players(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ddm.tile_widgets import Tile
        from ddm.room_placement import RoomPlacement
        source = Tile({'room_id': 'fixture-live', 'live': True}, self.owner)
        target = Tile({'room_id': 'fixture-vod', 'watchlater_bvid': 'fixture-vod'}, self.owner)
        for tile in (source, target):
            self.owner.layout().addWidget(tile)
        source.set_volume(25)
        source.set_muted(True)
        target.set_volume(70)
        target.set_muted(False)
        players = {tile: SimpleNamespace(volume=tile.volume, muted=tile.muted,
                    set_volume=lambda value, t=tile: setattr(players[t], 'volume', value),
                    set_muted=lambda value, t=tile: setattr(players[t], 'muted', value),
                    set_audio_channel=Mock(), reapply_audio_channel=Mock())
                   for tile in (source, target)}
        host = SimpleNamespace(wall=SimpleNamespace(tiles=[source, target], relayout=Mock()),
                               players=players, _refresh_meta=Mock())
        self.assertTrue(RoomPlacement(host).hot_swap(source, target))
        self.assertFalse(source.muted)
        self.assertTrue(target.muted)
        for tile in (source, target):
            self.assertEqual(tile.muted, players[tile].muted)
            self.assertEqual(tile.volume_button.muted, players[tile].muted)
            self.assertEqual(tile.volume_button.level, players[tile].volume)

    def test_pause_orientation_and_toggle_states(self):
        pause = ui.PauseButton(self.owner)
        pause.set_paused(True)
        self.assertTrue(pause.paused)
        self.assertEqual(pause.toolTip(), '继续播放')
        pause.set_paused(False)
        self.assertEqual(pause.toolTip(), '暂停这一路')
        sidebar = ui.SidebarToggleButton(self.owner)
        sidebar.show()
        for portrait in (False, True):
            sidebar.set_orientation(portrait, False)
            self.assertEqual(sidebar.accessibleName(), '收起关注栏')
            before = sidebar.grab().toImage()
            sidebar.set_orientation(portrait, True)
            self.assertEqual(sidebar.accessibleName(), '展开关注栏')
            self.assertFalse(sidebar.text())
            self.assertNotEqual(sidebar.grab().toImage(), before)
        danmaku = ui.DanmakuToggleButton('弹', self.owner)
        danmaku.setCheckable(True)
        QTest.mouseClick(danmaku, Qt.LeftButton)
        self.assertTrue(danmaku.isChecked())

    def test_settings_gear_is_monochrome_and_keeps_click_behavior(self):
        from ddm.playback_controls import DanmakuSettingsButton
        button = DanmakuSettingsButton(self.owner)
        self.owner.layout().addWidget(button)
        self.owner.show()
        clicked = []
        button.clicked.connect(lambda: clicked.append(True))
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(clicked, [True])
        self.assertEqual(button.text(), '')
        self.assertEqual(button.accessibleName(), '弹幕观看设置')
        for mode in ('dark', 'light'):
            theme.apply(mode)
            image = QImage(button.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            button.render(image)
            self.assertFalse(image.isNull())

    def test_tile_uses_pause_glyph_and_settings_button_in_host(self):
        from ddm.tile_widgets import Tile
        from ddm.playback_badges import PauseIndicator
        from ddm.playback_controls import DanmakuSettingsButton
        tile = Tile({'room_id': 'fixture', 'live': False}, self.owner)
        self.owner.layout().addWidget(tile)
        self.owner.show()
        self.assertIsInstance(tile.pause_overlay, PauseIndicator)
        self.assertIsInstance(tile.danmaku_settings_button, DanmakuSettingsButton)
        tile._player_active = True
        tile.set_paused(True)
        self.assertFalse(tile.pause_overlay.isHidden())
        tile.set_paused(False)
        self.assertTrue(tile.pause_overlay.isHidden())
        with patch.object(tile.danmaku_settings_menu, 'open_at') as opened:
            QTest.mouseClick(tile.danmaku_settings_button, Qt.LeftButton)
        opened.assert_called_once()

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

    def test_live_tile_controls_use_neutral_feedback_without_moving_hit_areas(self):
        from ddm import continuous_corners
        from ddm.tile_widgets import Tile
        self.addCleanup(theme.apply, theme.mode())
        theme.apply('dark')
        self.owner.setAttribute(Qt.WA_DontShowOnScreen)
        self.owner.resize(720, 320)
        tile = Tile({'room_id': '1000', 'live': False}, self.owner)
        self.owner.layout().addWidget(tile)
        self.owner.show()
        tile.set_controls_visible(True)
        tile._control_hover_timer.stop()
        buttons = (tile.pause_button, tile.volume_button, tile.danmaku_button, tile.danmaku_settings_button,
                   tile.recording_button, tile.fullscreen_button, tile.quality_button, tile.reload_button,
                   tile.close_button)
        surfaces = continuous_corners._filter
        for mode in ('light', 'dark'):
            theme.apply(mode)
            QApplication.processEvents()
            for button in buttons:
                with self.subTest(mode=mode, tip=button.toolTip()):
                    button.setProperty('hovered', False)
                    idle = surfaces.values(button, overrides={'hover': False})
                    hover = surfaces.values(button, overrides={'hover': True})
                    pressed = surfaces.values(button, overrides={'hover': True, 'pressed': True})
                    if button.parentWidget() is tile.controls:
                        self.assertEqual(hover['background'], 'rgba(48, 51, 57, 0.89)')
                        self.assertEqual(pressed['background'], 'rgba(68, 71, 77, 0.93)')
                    else:
                        self.assertTrue(hover['background'].endswith(', 0.15)'))
                        self.assertTrue(pressed['background'].endswith(', 0.27)'))
                    self.assertNotEqual(idle['background'], hover['background'])
                    self.assertEqual(pressed['border'], 'none')
                    self.assertEqual(button.cursor().shape(), Qt.PointingHandCursor)
            tile.set_status('播放中')
            self.assertEqual(tile.status_label.text(), '')
        button = tile.pause_button
        geometry = button.geometry()
        button.setProperty('hovered', True)
        point = QPoint(button.width() - 7, button.height() // 2)
        hovered = button.grab().toImage().pixelColor(point)
        with patch.object(motion, 'enabled', return_value=True):
            QTest.mousePress(button, Qt.LeftButton)
            self.assertNotEqual(button.grab().toImage().pixelColor(point), hovered)
            animation = button._press_animation
            animation.setCurrentTime(animation.duration())
            self.assertEqual(button._press_scale, .97)
            QTest.mouseRelease(button, Qt.LeftButton)
            animation.setCurrentTime(animation.duration())
            self.assertEqual(button._press_scale, 1.)
        with patch.object(motion, 'enabled', return_value=False):
            QTest.mousePress(button, Qt.LeftButton)
            self.assertTrue(button.isDown())
            self.assertEqual(button._press_scale, 1.)
            QTest.mouseRelease(button, Qt.LeftButton)
        self.assertEqual(button.geometry(), geometry)

        tile.bottom.set_fullscreen(True)
        theme.apply('light')
        self.assertEqual(surfaces.values(tile.pause_button, overrides={'hover': True})['background'],
                         'rgba(231, 235, 240, 0.15)')
        tile.bottom.set_fullscreen(False)

        menu = tile.danmaku_settings_menu
        menu.setAttribute(Qt.WA_DontShowOnScreen)
        menu.open_at(tile.danmaku_settings_button, tile.video_danmaku.settings)
        self.assertTrue(tile.danmaku_settings_button.property('playbackPopupOpen'))
        menu.hide()
        self.assertFalse(tile.danmaku_settings_button.property('playbackPopupOpen'))
        tile.volume_menu.setAttribute(Qt.WA_DontShowOnScreen)
        tile.volume_menu.show()
        self.assertTrue(tile.volume_button.property('playbackPopupOpen'))
        tile.volume_menu.hide()
        self.assertFalse(tile.volume_button.property('playbackPopupOpen'))

    def test_playback_volume_thumbs_enlarge_without_changing_hit_geometry(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QStyle, QStyleOptionSlider
        from ddm.tile_widgets import Tile

        self.addCleanup(theme.apply, theme.mode())
        theme.apply('dark')
        self.owner.setAttribute(Qt.WA_DontShowOnScreen)
        self.owner.resize(720, 320)
        tile = Tile({'room_id': '1000'}, self.owner)
        self.owner.layout().addWidget(tile)
        self.owner.show()
        tile.volume_menu.setAttribute(Qt.WA_DontShowOnScreen)
        tile.volume_menu.show()
        QApplication.processEvents()

        def handle(slider):
            option = QStyleOptionSlider()
            slider.initStyleOption(option)
            return slider.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, slider)

        def white_pixels(slider):
            image = slider.grab().toImage()
            return sum(image.pixelColor(x, y) == QColor('white') for x in range(image.width())
                       for y in range(image.height()))

        for slider in (tile.volume_slider, tile.vertical_volume):
            with self.subTest(orientation=slider.orientation()):
                rect = handle(slider)
                value = slider.value()
                idle = white_pixels(slider)
                QTest.mousePress(slider, Qt.LeftButton, pos=rect.center())
                self.assertTrue(slider.isSliderDown())
                self.assertEqual(handle(slider), rect)
                self.assertGreater(white_pixels(slider), idle)
                QTest.mouseRelease(slider, Qt.LeftButton, pos=rect.center())
                self.assertEqual(slider.value(), value)
                self.assertEqual(white_pixels(slider), idle)

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
