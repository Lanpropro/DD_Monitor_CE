"""Offline regressions for badge edges, history navigation, scaling and tile menus."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionButton, QWidget
from ddm import config, theme
from ddm.dialogs import DanmakuSettingsPage, TraySettingsPage
from ddm.playback_badges import StreamBadge, TitleBadge
from ddm.playback_controls import TileButton
from ddm.super_chat import sc_placement_rects
from ddm.tile_menu import MENU_ITEMS, menu_choices
from ddm.video_danmaku import VideoDanmaku
from ddm.viewport_scale import viewport_scale
from ddm.widgets import DanmakuPanel, Tile

APP = QApplication.instance() or QApplication([])


class UiPolishTests(unittest.TestCase):
    def test_badges_keep_alpha_edges_without_integer_masks(self):
        owner = QWidget()
        self.addCleanup(owner.deleteLater)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            for badge in (StreamBadge(owner), TitleBadge(owner)):
                if isinstance(badge, TitleBadge):
                    badge.set_text('Fixture', 'Title')
                badge.refresh_theme()
                self.assertTrue(badge.mask().isEmpty())
                for dpr in (1, 1.25, 1.5, 2):
                    image = QImage(round(badge.width()*dpr), round(badge.height()*dpr), QImage.Format_ARGB32_Premultiplied)
                    image.setDevicePixelRatio(dpr)
                    image.fill(Qt.transparent)
                    painter = QPainter(image)
                    badge._render_badge(painter)
                    painter.end()
                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                    self.assertTrue(any(0 < image.pixelColor(x, y).alpha() < 255
                                        for x in range(round(8*dpr)) for y in range(round(8*dpr))))

    def test_bottom_button_hover_is_one_symmetric_surface(self):
        button = TileButton('')
        self.addCleanup(button.deleteLater)
        button.setObjectName('TileCtrl')
        button.setProperty('tileButton', True)
        button.setProperty('hovered', True)
        button.setFixedSize(26, 26)
        button.ensurePolished()
        option = QStyleOptionButton()
        button.initStyleOption(option)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            for dpr in (1, 1.5, 2):
                image = QImage(round(26*dpr), round(26*dpr), QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(dpr)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                button._paint_button(painter, option)
                painter.end()
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertGreater(image.pixelColor(image.width()//2, image.height()//2).alpha(), 200)
                for x in range(image.width()//2):
                    for y in range(image.height()):
                        self.assertLessEqual(abs(image.pixelColor(x, y).alpha() -
                                                 image.pixelColor(image.width()-x-1, y).alpha()), 6)

    @unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows',
                         'Windows child-window alpha uploads required')
    def test_native_badge_alpha_in_both_themes(self):
        owner = QWidget()
        owner.setAttribute(Qt.WA_ShowWithoutActivating)
        owner.setGeometry(-10000, -10000, 600, 100)
        self.addCleanup(owner.deleteLater)
        self.addCleanup(owner.close)
        badges = [StreamBadge(owner), TitleBadge(owner)]
        badges[1].set_text('Fixture', 'Antialiased title')
        for index, badge in enumerate(badges):
            badge.move(index * 200, 20)
            badge.setAttribute(Qt.WA_NativeWindow)
        owner.show()
        for mode in ('dark', 'light', 'dark'):
            theme.apply(mode)
            APP.processEvents()
            for badge in badges:
                badge.refresh_theme()
                badge._paint_layered()
                self.assertTrue(badge._alpha_uploaded)
                self.assertTrue(badge.mask().isEmpty())

    def test_history_button_stays_in_view_after_refresh_and_scroll(self):
        panel = DanmakuPanel()
        self.addCleanup(panel.deleteLater)
        panel.resize(360, 280)
        panel.show()
        APP.processEvents()
        for i in range(70):
            panel.add_message('reader', f'{i} reading history ' * 3)
        APP.processEvents()
        bar = panel.body.verticalScrollBar()
        panel._on_scroll_pressed()
        bar.setValue(bar.maximum() // 2)
        panel._on_scroll_released()
        for i in range(12):
            panel.add_message('new', str(i))
            if i % 3 == 0:
                panel._render_all()  # The same document replacement as an emote arriving.
            APP.processEvents()
            self.assertFalse(panel._follow_tail)
            self.assertTrue(panel.bottom_button.isVisible())
            viewport = panel.body.viewport()
            self.assertTrue(viewport.rect().contains(panel.bottom_button.geometry()))
            self.assertEqual(viewport.height() - panel.bottom_button.geometry().bottom(), 11)
        panel.jump_to_bottom()
        APP.processEvents()
        self.assertTrue(panel.bottom_button.isHidden())

    def test_curve_endpoints_and_live_redraw(self):
        for strength in (0, 35, 50, 100):
            self.assertEqual(viewport_scale(720, strength), 1)
            self.assertLessEqual(viewport_scale(180, strength), viewport_scale(360, strength))
        self.assertEqual(viewport_scale(180, 0), 1)
        self.assertEqual(viewport_scale(180, 100), .25)
        self.assertGreater(viewport_scale(180, 35), .6)
        overlay = VideoDanmaku()
        self.addCleanup(overlay.deleteLater)
        overlay.resize(1280, 180)
        settings = {**config.DEFAULT_SETTINGS, 'video_danmaku_size': 40}
        overlay.apply_settings({**settings, 'video_danmaku_scale_strength': 0})
        self.assertEqual(overlay.font_pixels(), 40)
        overlay.apply_settings({**settings, 'video_danmaku_scale_strength': 100})
        self.assertEqual(overlay.font_pixels(), 10)
        overlay.apply_settings({**settings, 'video_danmaku_scale': False})
        self.assertEqual(overlay.font_pixels(), 40)
        event = {'id': 'test', 'message': 'readable', 'price': 30, 'uname': 'fixture'}
        # A collapsed card fits at all strengths, isolating video scaling from crowding.
        sizes = [sc_placement_rects([event], 1280, 360, scale_with_video=True,
                                   scale_strength=value, collapsed=True)[1] for value in (0, 35, 100)]
        self.assertEqual(sizes[0], 1)
        self.assertGreater(sizes[1], sizes[2])
        self.assertEqual(sizes[2], .5)
        self.assertIn('video_danmaku_scale_strength', config.VIDEO_DANMAKU_SETTING_KEYS)
        page = DanmakuSettingsPage(config.DEFAULT_SETTINGS)
        self.addCleanup(page.deleteLater)
        page.super_chat_scale_strength.setValue(12)
        page.video_danmaku_scale_strength.setValue(23)
        self.assertEqual(page.values()['super_chat_scale_strength'], 12)
        self.assertEqual(page.values()['video_danmaku_scale_strength'], 23)
        page.reset()
        self.assertEqual(page.values()['super_chat_scale_strength'], 35)
        self.assertEqual(page.values()['video_danmaku_scale_strength'], 35)

    def test_menu_editor_and_runtime_keep_order_callbacks_and_visibility(self):
        page = TraySettingsPage(config.DEFAULT_SETTINGS)
        self.addCleanup(page.deleteLater)
        editor = page.tile_menu
        page.resize(600, 700)
        page.show()
        APP.processEvents()
        from PySide6.QtWidgets import QPushButton
        for button in editor.findChildren(QPushButton):
            self.assertFalse(button.geometry().intersects(editor.list.geometry()))
        for mode in ('dark', 'light'):
            theme.apply(mode)
            APP.processEvents()
            viewport = editor.list.viewport()
            image = editor.list.grab().toImage()
            point = viewport.mapTo(editor.list, viewport.rect().bottomRight() - QPoint(20, 10))
            self.assertEqual(image.pixelColor(point),
                             theme.qcolor(theme.CONTENT))
        editor.list.setCurrentRow(0)
        editor.move_item(1)
        editor.list.item(0).setCheckState(Qt.Unchecked)
        choices = page.values()['tile_context_menu']
        self.assertEqual(choices[0], {'id': 'quality', 'enabled': False})
        tile = Tile({'room_id': '1'})
        self.addCleanup(tile.deleteLater)
        called = []
        tile.plugin_actions = [('Fixture plugin', lambda: called.append('plugin'))]
        tile.apply_video_danmaku_settings({**config.DEFAULT_SETTINGS, 'tile_context_menu': choices})
        menu = tile.build_menu()
        self.addCleanup(menu.deleteLater)
        actions = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(actions[0].data(), 'volume')
        self.assertNotIn('quality', [a.data() for a in actions])
        next(a for a in actions if a.data() == 'plugins').trigger()
        self.assertEqual(called, ['plugin'])
        muted = tile.muted
        next(a for a in actions if a.data() == 'mute').trigger()
        self.assertEqual(tile.muted, not muted)
        page.reset()
        self.assertEqual([x['id'] for x in page.values()['tile_context_menu']], [x[0] for x in MENU_ITEMS])
        self.assertEqual(len(menu_choices([{'id': 'bad'}, {'id': 'close'}, {'id': 'close'}])), len(MENU_ITEMS))
        tile.setProperty('fullscreen', True)
        fullscreen_menu = tile.build_menu()
        self.addCleanup(fullscreen_menu.deleteLater)
        self.assertNotIn('switch_danmaku', [a.data() for a in fullscreen_menu.actions()])
        tile.apply_video_danmaku_settings({'tile_context_menu': [
            {'id': key, 'enabled': False} for key, _label in MENU_ITEMS]})
        empty_menu = tile.build_menu()
        self.addCleanup(empty_menu.deleteLater)
        self.assertTrue(empty_menu.isEmpty())

    def test_menu_and_curves_round_trip_without_touching_real_settings(self):
        settings = {**config.DEFAULT_SETTINGS,
                    'tile_context_menu': list(reversed(menu_choices(None))),
                    'super_chat_scale_strength': 17, 'video_danmaku_scale_strength': 29}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(config, 'CONFIG_PATH', str(Path(directory)/'config.json')), patch.dict(os.environ):
                os.environ.pop('DDM_NO_SAVE', None)
                config.save({'version': 1, 'settings': settings})
                loaded = config.load()['settings']
        for key in ('tile_context_menu', 'super_chat_scale_strength', 'video_danmaku_scale_strength'):
            self.assertEqual(loaded[key], settings[key])


if __name__ == '__main__':
    APP.setStyleSheet(theme.qss())
    unittest.main()
