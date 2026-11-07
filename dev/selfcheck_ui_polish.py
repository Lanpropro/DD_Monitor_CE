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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionButton, QWidget
from ddm import config, theme
from ddm.dialogs import DanmakuSettingsPage, TraySettingsPage
from ddm.playback_badges import StreamBadge, TitleBadge
from ddm.playback_controls import TileButton
from ddm.super_chat import sc_placement_rects
from ddm.tile_menu import MENU_ITEMS, menu_choices
from ddm.video_danmaku import VideoDanmaku
from ddm.viewport_scale import scale_curve_points, viewport_scale
from ddm.ui import ScaleCurveControl
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
        points = [[0, .5], [.5, .8], [1, 1], [2, 1.4]]
        page.super_chat_scale_curve.set_curve(points)
        page.video_danmaku_scale_curve.set_curve(points)
        self.assertEqual(page.values()['super_chat_scale_curve'], points)
        self.assertEqual(page.values()['video_danmaku_scale_curve'], points)
        page.reset()
        self.assertEqual(page.values()['super_chat_scale_curve'], scale_curve_points())
        self.assertEqual(page.values()['video_danmaku_scale_curve'], scale_curve_points())
        self.assertEqual(page.super_chat_placement.scale_curve, page.super_chat_scale_curve.curve())

    def test_graph_add_drag_delete_anchor_and_runtime_curve(self):
        control = ScaleCurveControl()
        self.addCleanup(control.deleteLater)
        control.resize(380, 290)
        control.show()
        APP.processEvents()
        graph = control.graph
        points = [[0, .5], [.5, .8], [1, 1], [2, 1.4]]
        control.set_curve(points)
        changes = []
        control.curveChanged.connect(changes.append)
        self.assertEqual(viewport_scale(360, points=points), .8)
        self.assertAlmostEqual(viewport_scale(540, points=points), .9)
        self.assertEqual(viewport_scale(2000, points=points), 1.4)
        start = graph.point_position([.75, .9]).toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=start)
        QTest.mouseMove(graph, start-QPoint(0, 15))
        QTest.mouseRelease(graph, Qt.LeftButton, pos=start-QPoint(0, 15))
        self.assertEqual(len(control.curve()), 5)
        added = control.curve()[2]
        self.assertGreater(added[1], .9)
        self.assertTrue(changes)
        # A settings feedback update during dragging must not reset the gesture.
        original = graph.point_position(added).toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=original)
        control.set_curve(control.curve())
        QTest.mouseMove(graph, original-QPoint(0, 8))
        QTest.mouseRelease(graph, Qt.LeftButton, pos=original-QPoint(0, 8))
        self.assertGreater(control.curve()[2][1], added[1])
        QTest.mouseClick(graph, Qt.RightButton, pos=graph.point_position(control.curve()[2]).toPoint())
        self.assertEqual(len(control.curve()), 4)
        anchor = graph.point_position([1, 1]).toPoint()
        QTest.mousePress(graph, Qt.LeftButton, pos=anchor)
        QTest.mouseRelease(graph, Qt.LeftButton, pos=anchor+QPoint(10, 15))
        self.assertIn([1, 1], control.curve())
        QTest.mouseClick(graph, Qt.RightButton, pos=anchor)
        self.assertIn([1, 1], control.curve())
        overlay = VideoDanmaku()
        self.addCleanup(overlay.deleteLater)
        overlay.resize(1280, 360)
        overlay.apply_settings({**config.DEFAULT_SETTINGS, 'video_danmaku_size': 40,
                                'video_danmaku_scale_curve': points})
        self.assertEqual(overlay.font_pixels(), 32)
        event = {'id': 'curve', 'message': 'readable', 'price': 30, 'uname': 'fixture'}
        self.assertEqual(sc_placement_rects([event], 1280, 360, scale_with_video=True,
                                          collapsed=True, scale_curve=points)[1], .8)
        self.assertIn('video_danmaku_scale_curve', config.VIDEO_DANMAKU_SETTING_KEYS)
        tile = Tile({'room_id': 'curve-fixture'})
        self.addCleanup(tile.deleteLater)
        tile.apply_video_danmaku_settings(config.DEFAULT_SETTINGS)
        tile._set_video_danmaku_independent(True)
        tile.danmaku_settings_menu.settingsChanged.emit({'video_danmaku_scale_curve': points})
        self.assertEqual(tile.video_danmaku_overrides['video_danmaku_scale_curve'], points)
        self.assertIsNone(tile._video_danmaku_global_settings['video_danmaku_scale_curve'])
        tile._set_video_danmaku_independent(False)
        self.assertIsNone(tile.video_danmaku.settings['video_danmaku_scale_curve'])
        from ddm.video_danmaku_settings import VideoDanmakuSettings
        menu = VideoDanmakuSettings()
        self.addCleanup(menu.deleteLater)
        received = []
        menu.settingsChanged.connect(received.append)
        menu.apply_settings({**config.DEFAULT_SETTINGS, 'video_danmaku_scale_curve': points})
        self.assertEqual(menu.scale_curve.curve(), points)
        self.assertFalse(received, 'Applying stored points must not emit edits')
        menu.scale_curve.reset()
        self.assertEqual(received[-1]['video_danmaku_scale_curve'], scale_curve_points())
        menu.scale.setChecked(False)
        self.assertFalse(menu.scale_curve.isEnabled())
        control.reset()
        self.assertEqual(control.curve(), scale_curve_points())
        image = graph.grab().toImage()
        grid_point = graph.point_position([.5, .5]).toPoint()
        self.assertNotEqual(image.pixelColor(grid_point), theme.qcolor(theme.CONTENT),
                            'An open curve must not fill over the grid below it')

    def test_menu_editor_and_runtime_keep_order_callbacks_and_visibility(self):
        page = TraySettingsPage(config.DEFAULT_SETTINGS)
        self.addCleanup(page.deleteLater)
        editor = page.tile_menu
        page.resize(600, 700)
        page.show()
        APP.processEvents()
        self.assertLess(editor.preview.x(), editor.checks['volume'].mapTo(editor, QPoint()).x())
        for mode in ('dark', 'light'):
            theme.apply(mode)
            APP.processEvents()
            image = editor.preview.grab().toImage()
            self.assertGreater(image.pixelColor(editor.preview.width()//2, 5).alpha(), 0)
        rows = dict(editor.preview.rows())
        start = rows['volume'].center().toPoint()
        end = QPoint(start.x(), int(rows['quality'].bottom()-1))
        QTest.mousePress(editor.preview, Qt.LeftButton, pos=start)
        QTest.mouseMove(editor.preview, end)
        QTest.mouseRelease(editor.preview, Qt.LeftButton, pos=end)
        self.assertEqual(editor.values()[0]['id'], 'quality')
        editor.checks['quality'].setChecked(False)
        self.assertNotIn('quality', dict(editor.preview.rows()))
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
                    'super_chat_scale_strength': 17, 'video_danmaku_scale_strength': 29,
                    'super_chat_scale_curve': [[0, .4], [1, 1], [2, 1.5]],
                    'video_danmaku_scale_curve': [[0, .6], [1, 1], [2, 1.4]]}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(config, 'CONFIG_PATH', str(Path(directory)/'config.json')), patch.dict(os.environ):
                os.environ.pop('DDM_NO_SAVE', None)
                config.save({'version': 1, 'settings': settings})
                loaded = config.load()['settings']
        for key in ('tile_context_menu', 'super_chat_scale_strength', 'video_danmaku_scale_strength',
                    'super_chat_scale_curve', 'video_danmaku_scale_curve'):
            self.assertEqual(loaded[key], settings[key])


if __name__ == '__main__':
    APP.setStyleSheet(theme.qss())
    unittest.main()
