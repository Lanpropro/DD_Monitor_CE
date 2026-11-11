"""Exercise the manual simulator buttons and timer with temporary data only."""
from pathlib import Path
import sys
import unittest
import subprocess
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev.sc_simulator import ScSimulator, config, theme
from ddm import motion
from ddm.super_chat import SC_PRICE_TIERS, sc_message_document, super_chat_palette
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtCore import QRectF
from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])


@unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows', 'Native Windows SC surface')
class NativeSurfaceTests(unittest.TestCase):
    def test_left_card_pixels_and_owner_lifecycle(self):
        from ddm.widgets import Tile
        from dev.selfcheck_fullscreen_controls import native_bar_image
        class SettingsMask(QObject):
            occlusionChanged = Signal()
            occlusion = QRect()
        host = QWidget()
        host.setAttribute(Qt.WA_ShowWithoutActivating)
        host.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        host.setGeometry(-10000, -10000, 1240, 760)
        host._settings_process = SettingsMask(host)
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        tile = Tile({'room_id': '1', 'uname': 'Native title', 'live': True}, host)
        tile.setGeometry(0, 0, 1200, 700)
        host.show()
        tile.set_video_active(True)
        tile.danmaku_button.setChecked(True)
        tile.video_danmaku.set_native_video(True)
        tile.set_controls_visible(True)
        owner = tile.video_danmaku
        owner.apply_settings({'super_chat_opacity': 100, 'super_chat_collapse_delay': 60})
        now = int(time.time())
        owner.set_super_chats([dict(kind='super_chat', id='native', uid='1', uname='Native SC', price=30,
            message='SC body pixels', start_time=now, end_time=now + 120)])
        sc = owner.super_chat_overlay
        sc.presentation.entrance.stop()
        sc.presentation.progress = 1.0
        for position in ([0, 0], [1, 0], [0, .5], [0, 0]):
            owner.settings['super_chat_position'] = position
            sc._refresh()
            QTest.qWait(60)
            image = native_bar_image(sc)
            expected = sc.render_image()
            scale = sc.devicePixelRatioF()
            for x, y in ((80, 5), (80, 75), (200, 75), (310, 75)):
                point = QPoint(round(x * scale), round(y * scale))
                self.assertEqual(image.pixelColor(point), expected.pixelColor(point),
                                 f'Native SC pixels must match their own source at {position}, {point}')
        self.assertTrue(sc.isWindow())
        geometry = tile.geometry()
        for fullscreen in (True, False):
            tile.hide()
            tile.setWindowFlags((Qt.Window | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
                                if fullscreen else Qt.Widget)
            tile.setGeometry(QRect(-9000, -9000, 1200, 700) if fullscreen else geometry)
            tile.show()
            QTest.qWait(60)
            self.assertEqual(sc.pos(), owner.mapToGlobal(sc._content_origin))
            self.assertIs(sc.windowHandle().transientParent(), tile.window().windowHandle())
        for move in (lambda: host.move(host.pos() + QPoint(70, 40)),
                     lambda: tile.move(15, 10)):
            move()
            QTest.qWait(60)
            self.assertEqual(sc.pos(), owner.mapToGlobal(sc._content_origin))
        region = QRect(sc.pos(), sc.size())
        host._settings_process.occlusion = region
        host._settings_process.occlusionChanged.emit()
        QTest.qWait(60)
        self.assertFalse(sc.isVisible(), 'External settings must cover the SC surface')
        host._settings_process.occlusion = QRect()
        host._settings_process.occlusionChanged.emit()
        QTest.qWait(60)
        self.assertTrue(sc.isVisible())
        host.hide()
        QTest.qWait(60)
        self.assertFalse(sc.isVisible())
        host.show()
        QTest.qWait(60)
        self.assertTrue(sc.isVisible())
        self.assertIs(sc.windowHandle().transientParent(), host.windowHandle())
        from PySide6.QtWidgets import QDialog
        dialog = QDialog(host)
        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.setGeometry(-9900, -9900, 700, 500)
        dialog.show()
        sc._refresh()
        self.assertFalse(sc.isVisible(), 'SC must stay behind modal settings')
        dialog.close()
        sc._refresh()
        self.assertTrue(sc.isVisible())
        start = sc.card_rects()[0].topLeft().toPoint() + QPoint(60, 16) - sc._content_origin
        QTest.mousePress(sc, Qt.LeftButton, pos=start)
        QTest.mouseMove(sc, start + QPoint(70, 35))
        QTest.mouseRelease(sc, Qt.LeftButton, pos=start + QPoint(70, 35))
        self.assertNotEqual(owner.settings['super_chat_position'], [0, 0])
        corner = sc.card_rects()[0].bottomRight().toPoint() - sc._content_origin - QPoint(3, 3)
        QTest.mousePress(sc, Qt.LeftButton, pos=corner)
        QTest.mouseMove(sc, corner + QPoint(45, 0))
        QTest.mouseRelease(sc, Qt.LeftButton, pos=corner + QPoint(45, 0))
        self.assertGreater(owner.settings['super_chat_scale'], 100)
        sc.presentation.collapse()
        point = sc.card_rects()[0].center().toPoint() - sc._content_origin
        QTest.mouseClick(sc, Qt.LeftButton, pos=point)
        self.assertFalse(sc.presentation.collapsed)
        dismissed = []
        sc.dismissed.connect(dismissed.append)
        QTest.mouseClick(sc.close_button, Qt.LeftButton)
        self.assertEqual(dismissed, [])
        self.assertTrue(sc.presentation.is_collapsed('native'))
        QTest.mouseClick(sc.close_button, Qt.LeftButton)
        self.assertEqual(dismissed, ['native'])

    def test_diagnostic_capture_does_not_change_sc_geometry(self):
        from contextlib import ExitStack
        import json
        import tempfile
        from dev.diagnose_super_chat import SuperChatTrace
        from ddm.video_danmaku import SuperChatOverlay
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for name in ('sync', 'paintEvent', '_paint_layered', '_render_layered'):
                stack.enter_context(patch.object(SuperChatOverlay, name, getattr(SuperChatOverlay, name)))
            trace = SuperChatTrace(Path(directory))
            trace.install()
            self.test_left_card_pixels_and_owner_lifecycle()
            rows = [json.loads(line) for line in (Path(directory) / 'events.jsonl').read_text().splitlines()]
            images = [Path(directory) / row['sourceImage'] for row in rows if 'sourceImage' in row]
            self.assertTrue(images)
            self.assertTrue(all(not QImage(str(path)).isNull() for path in images))
            self.assertLessEqual(len(rows), 300)


class SimulatorTests(unittest.TestCase):
    def test_sc_auto_scale_preserves_proportions_and_manual_size(self):
        from ddm.video_danmaku import VideoDanmaku
        owner = VideoDanmaku()
        self.addCleanup(owner.close)
        event = dict(kind='super_chat', id='scale', uname='Scale', price=30, message='Short')
        for manual in (75, 100, 150):
            # Direct proportion is one selectable curve, rather than the default.
            owner.apply_settings(dict(config.DEFAULT_SETTINGS, super_chat_scale=manual,
                                      super_chat_scale_with_video=True,
                                      super_chat_scale_curve=[[0, .1], [.1, .1], [1, 1], [2, 2]]))
            owner.super_chat_overlay.chats = [event]
            sizes = []
            for width, height in ((1280, 720), (640, 360), (320, 180)):
                owner.resize(width, height)
                rect = owner.super_chat_overlay.card_rects()[0]
                sizes.append((rect.width(), rect.height(), owner.super_chat_overlay._paint_scale))
                self.assertAlmostEqual(owner.super_chat_overlay._paint_scale, manual / 100 * height / 720)
                self.assertLessEqual(rect.right(), width)
                self.assertLessEqual(rect.bottom(), height)
            self.assertAlmostEqual(sizes[1][0], sizes[0][0] / 2)
            self.assertAlmostEqual(sizes[2][0], sizes[0][0] / 4)
            self.assertLessEqual(abs(sizes[1][1] - sizes[0][1] / 2), 2)
        owner.apply_settings(dict(config.DEFAULT_SETTINGS, super_chat_scale_with_video=False))
        owner.resize(640, 360)
        owner.super_chat_overlay.card_rects()
        self.assertEqual(owner.super_chat_overlay._paint_scale, 1)

    def test_default_sc_curve_keeps_small_cards_larger_than_linear(self):
        from ddm.video_danmaku import VideoDanmaku
        owner = VideoDanmaku()
        self.addCleanup(owner.close)
        owner.apply_settings(dict(config.DEFAULT_SETTINGS, super_chat_scale_with_video=True))
        owner.super_chat_overlay.chats = [dict(kind='super_chat', id='default-scale',
                                              uname='Scale', price=30, message='Short')]
        for height, expected in ((720, 1), (360, .7845840978967508), (180, .6155722066724582)):
            owner.resize(1280, height)
            owner.super_chat_overlay.card_rects()
            self.assertAlmostEqual(owner.super_chat_overlay._paint_scale, expected)

    def test_default_video_danmaku_curve_preserves_small_pane_readability(self):
        from ddm.video_danmaku import VideoDanmaku
        owner = VideoDanmaku()
        self.addCleanup(owner.close)
        owner.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_size=28,
                                  video_danmaku_outline_width=2))
        for height, expected in ((180, 17), (360, 22), (540, 25), (720, 28), (1080, 32), (1440, 36)):
            owner.resize(1280, height)
            self.assertEqual(owner.font_pixels(), expected, height)
            self.assertAlmostEqual(owner.outline_width(), 2 * expected / 28)
        values = []
        for height in range(120, 1450):
            owner.resize(1280, height)
            values.append(owner.font_pixels())
        self.assertEqual(values, sorted(values))
        self.assertLessEqual(max(b - a for a, b in zip(values, values[1:])), 1)
        owner.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_size=28, video_danmaku_scale=False))
        owner.resize(320, 180)
        self.assertEqual(owner.font_pixels(), 28)

    def test_sc_auto_scale_setting_updates_preview_roundtrips_and_resets(self):
        from ddm.dialogs import DanmakuSettingsPage
        points = [[0, .3], [.5, .8], [1, 1], [2, 1.5]]
        page = DanmakuSettingsPage(dict(config.DEFAULT_SETTINGS, super_chat_scale_curve=points))
        self.addCleanup(page.close)
        preview = page.super_chat_placement
        self.assertFalse(page.super_chat_scale_with_video.isChecked())
        page.super_chat_scale_with_video.click()
        self.assertTrue(page.values()['super_chat_scale_with_video'])
        preview.set_preview_context({'video': {'size': [640, 360],
                                              'cards': [{'message': '', 'collapsed': False}]}})
        stage = preview.stage_rect()
        factor = stage.width() / 640
        self.assertAlmostEqual(preview.card_rect().width() / factor, 272)
        preview.set_layout_mode(1)
        before = preview.card_rect()
        page.super_chat_scale_with_video.click()
        self.assertEqual(preview.card_rect(), before, 'Video scale must not change chat-panel SC size')
        restored = DanmakuSettingsPage(dict(page.values(), super_chat_scale_with_video=True))
        self.addCleanup(restored.close)
        self.assertTrue(restored.super_chat_scale_with_video.isChecked())
        self.assertEqual(restored.values()['super_chat_scale_curve'], points)
        restored.reset()
        self.assertFalse(restored.values()['super_chat_scale_with_video'])

    def test_auto_scale_controls_update_live_cards_and_resize(self):
        window = self.window
        window.layout_choice.setCurrentIndex(1)
        for control in (window.sc_scale_with_video, window.danmaku_scale):
            QTest.mouseClick(control, Qt.LeftButton, pos=QPoint(8, control.height() // 2))
            APP.processEvents()
        self.assertTrue(window.tile.video_danmaku.settings['super_chat_scale_with_video'])
        self.assertTrue(window.tile.video_danmaku.settings['video_danmaku_scale'])
        window.change_sc_settings({'super_chat_position': [.4, .6],
                                   'super_chat_scale_curve': [[0, .6], [1, 1], [2, 1.3]]})
        owner = window.tile.video_danmaku
        sc = owner.super_chat_overlay
        for size in ((1200, 760), (900, 600), (1600, 1000)):
            window.resize(*size)
            APP.processEvents()
            rects = sc.card_rects()
            self.assertTrue(rects)
            ratio = owner.height() / 720
            expected = .6 + .4 * ratio if ratio <= 1 else 1 + .3 * (ratio - 1)
            self.assertAlmostEqual(sc._paint_scale, expected)
            self.assertTrue(sc.isVisible())
            self.assertEqual(owner.settings['super_chat_position'], [.4, .6])
        window.sc_scale.setValue(150)
        self.assertAlmostEqual(sc._paint_scale, 1.5 * expected)
        self.assertTrue(window.sc_scale_with_video.isChecked())

    def test_restored_danmaku_toggle_does_not_mask_an_unfinished_tile(self):
        from ddm.widgets import Tile
        with patch('sys.excepthook') as errors:
            tile = Tile({'room_id': 'fixture', 'video_danmaku_enabled': True})
            try:
                self.assertTrue(tile.video_danmaku.enabled)
                self.assertFalse(errors.called, 'SC must not access controls before Tile finishes construction')
            finally:
                tile.close()

    def test_schematic_preview_opacity_and_compact_controls(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage(dict(config.DEFAULT_SETTINGS))
        self.addCleanup(page.close)
        page.resize(700, 900)
        page.show()
        APP.processEvents()
        preview = page.super_chat_placement
        def colour_at(point):
            image = preview.grab().toImage()
            ratio = image.devicePixelRatio()
            return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))
        self.assertFalse(hasattr(preview, 'frame'))
        self.assertLessEqual(page.super_chat_opacity.width(), 240)
        self.assertLessEqual(page.super_chat_scale.width(), 240)
        self.assertEqual(page.super_chat_collapse_stepper.width(), theme.SETTINGS_STEPPER_WIDTH)
        self.assertEqual(page.super_chat_collapse_delay.suffix(), ' 秒')
        self.assertLess(page.super_chat_opacity.width(), preview.width())
        self.assertTrue(preview.rect().contains(preview.video_rect().toAlignedRect()))
        video_size = preview.preview_context['video']['size']
        self.assertAlmostEqual(preview.video_rect().width() / preview.video_rect().height(),
                               video_size[0] / video_size[1])
        for index in (0, 1):
            button = page.super_chat_preview_layout.button(index)
            self.assertIs(button, list(page.super_chat_layout_control.buttons.values())[index])
            button.click()
            self.assertTrue(button.isChecked())
            self.assertFalse(page.super_chat_preview_layout.button(1 - index).isChecked())
            rect = preview.card_rect()
            point = QPoint(round(rect.center().x()), round(rect.bottom()) - 2)
            preview.opacity = 0
            base = colour_at(point)
            page.super_chat_opacity.setValue(100)
            solid = colour_at(point)
            page.super_chat_opacity.setValue(35)
            faded = colour_at(point)
            self.assertNotEqual(faded, solid)
            for component in ('red', 'green', 'blue'):
                expected = getattr(solid, component)() * .35 + getattr(base, component)() * .65
                self.assertLessEqual(abs(getattr(faded, component)() - expected), 2)
        self.assertNotIn('sc_preview_frame', page.values())
        page.reset()
        self.assertEqual(preview.opacity, config.DEFAULT_SETTINGS['super_chat_opacity'])

    def test_preview_matches_live_renderers_at_all_scales(self):
        from types import SimpleNamespace
        from ddm.app import MainWindow
        from ddm.super_chat import SuperChatPlacementPreview
        window = self.window
        preview = SuperChatPlacementPreview()
        preview.resize(700, 300)
        self.addCleanup(preview.close)
        window.message.setPlainText('用于排版测量的多行正文。' * 8)
        self.click(window.add_button)
        window.number.setValue(2)
        window.message.setPlainText('短正文')
        self.click(window.add_button)
        source = SimpleNamespace(wall=window.wall, _fullscreen_tile=None)
        from ddm.settings_control import SettingsControl
        source.settings_control = SettingsControl(source)
        for window_size in ((1000, 700), (1600, 900)):
            window.resize(*window_size)
            for mode in (0, 1):
                window.layout_choice.setCurrentIndex(1 if mode == 0 else 0)
                preview.set_layout_mode(mode)
                renderer = (window.tile.video_danmaku.super_chat_overlay if mode == 0
                            else window.wall.danmaku.super_chats)
                for collapsed in (False, True):
                    renderer.presentation.collapse() if collapsed else renderer.presentation.expand()
                    for scale in (75, 100, 150, 200):
                        for position in (None, [0, 0], [.4, .6], [1, 1]):
                            window.change_sc_settings({'super_chat_scale': scale, 'super_chat_position_sync': False,
                                'super_chat_panel_position' if mode == 1 else 'super_chat_position': position})
                            APP.processEvents()
                            context = MainWindow._sc_preview_context(source)
                            preview.set_preview_context(context)
                            preview.apply_settings(window.sc_settings)
                            key = 'panel' if mode == 1 else 'video'
                            stage = preview.stage_rect()
                            factor = stage.width() / context[key]['size'][0]
                            if mode == 0:
                                actual = renderer.card_rects()
                            else:
                                viewport = window.wall.danmaku.body.viewport()
                                actual = [QRectF(card.mapToGlobal(QPoint()) - viewport.mapToGlobal(QPoint()), card.size())
                                          for card in renderer._cards[:len(renderer._events)]]
                                self.assertAlmostEqual(preview._panel_rect().width() / preview._panel_rect().height(),
                                                       window.wall.danmaku.width() / window.wall.danmaku.height())
                            self.assertEqual(len(actual), len(preview.card_rects()))
                            for real, shown in zip(actual, preview.card_rects()):
                                restored = QRectF((shown.x() - stage.x()) / factor,
                                    (shown.y() - stage.y()) / factor, shown.width() / factor, shown.height() / factor)
                                for field in ('x', 'y', 'width', 'height'):
                                    self.assertAlmostEqual(getattr(restored, field)(), getattr(real, field)(), delta=1.01,
                                        msg=str((mode, scale, position, collapsed, field, context[key]['size'],
                                                 renderer._video_danmaku.size() if mode == 0 else viewport.size())))

    def test_sc_header_and_body_opacity_do_not_overlap(self):
        from ddm.super_chat import paint_sc_background, SC_BODY_PADDING, sc_card_height, sc_message_document
        base, header, body = QColor('#204080'), QColor('#edf5ff'), QColor('#2a60b2')
        image = QImage(340, 160, QImage.Format_RGB32)
        image.fill(base)
        painter = QPainter(image)
        painter.setOpacity(.5)
        paint_sc_background(painter, QRectF(0, 0, 340, 160), body, header, 56)
        painter.end()
        for y, colour in ((20, header), (80, body)):
            actual = image.pixelColor(170, y)
            for component in ('red', 'green', 'blue'):
                expected = (getattr(base, component)() + getattr(colour, component)()) / 2
                self.assertLessEqual(abs(getattr(actual, component)() - expected), 1)
        event = {'message': '第一行\n第二行'}
        for scale in (.75, 1, 1.5, 2):
            height = sc_card_height(event, 340 * scale, scale)
            text_height = sc_message_document(event, 340 * scale, scale).size().height()
            self.assertGreaterEqual(height, 56 * scale + 2 * SC_BODY_PADDING * scale + text_height)

    def test_layout_previews_keep_independent_positions_and_shared_scale_opacity(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage(dict(config.DEFAULT_SETTINGS, super_chat_position_sync=False))
        self.addCleanup(page.close)
        page.resize(700, 900)
        page.show()
        APP.processEvents()
        preview = page.super_chat_placement
        page.super_chat_preview_layout.button(1).click()
        self.assertEqual(preview.layout_mode, 'panel')
        stage = preview.stage_rect()
        main_area = preview._scene_rect(preview.VIDEO_AREA)
        self.assertGreater(stage.left(), main_area.right())
        self.assertGreater(stage.top(), main_area.center().y())
        self.assertGreater(main_area.width(), stage.width() * 2)
        rect = preview.card_rect()
        self.assertTrue(stage.contains(rect))
        before = preview.values()
        start = rect.center().toPoint()
        QTest.mousePress(preview, Qt.LeftButton, pos=start)
        QTest.mouseMove(preview, start + QPoint(-15, 30))
        QTest.mouseRelease(preview, Qt.LeftButton, pos=start + QPoint(-15, 30))
        self.assertNotEqual(before['super_chat_panel_position'], preview.position)
        self.assertEqual(before['super_chat_position'], preview.values()['super_chat_position'])
        changed = preview.values()
        page.super_chat_preview_layout.button(0).click()
        self.assertEqual(preview.layout_mode, 'video')
        self.assertEqual(preview.values(), changed)
        page.super_chat_opacity.setValue(45)
        page.super_chat_preview_layout.button(1).click()
        self.assertEqual(preview.opacity, 45)
        page.reset()
        self.assertIsNone(preview.position)

    def setUp(self):
        self.motion_patch = patch.object(motion, 'enabled', return_value=False)
        self.motion_patch.start()
        self.addCleanup(self.motion_patch.stop)
        self.window = ScSimulator()
        self.window.show()
        APP.processEvents()
        self.addCleanup(self.window.close)

    def click(self, button):
        QTest.mouseClick(button, Qt.LeftButton)
        APP.processEvents()

    def test_add_update_multiple_delete_and_clear(self):
        window = self.window
        self.assertEqual(len(window.store.active()), 1)
        window.message.setPlainText('updated fixture')
        window.price.setValue(50)
        self.click(window.add_button)
        self.assertEqual(len(window.store.active()), 1)
        self.assertEqual(window.wall.danmaku.super_chats._cards[0].message.text(), 'updated fixture')
        self.assertEqual(window.tile.video_danmaku.super_chats[0]['price'], 50)
        window.number.setValue(2)
        self.click(window.add_button)
        self.assertEqual(len(window.store.active()), 2)
        self.click(window.delete_button)
        self.assertEqual([item['id'] for item in window.store.active()], ['1'])
        self.assertEqual(window.number.value(), 3)
        self.click(window.clear_button)
        self.assertFalse(window.store.active())
        self.assertTrue(window.wall.danmaku.super_chats.isHidden())
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())

    def test_official_tiers_follow_amount_and_update_both_surfaces(self):
        window = self.window
        for index, (price, header, body, _) in enumerate(SC_PRICE_TIERS):
            window.tier.setCurrentIndex(index)
            self.assertEqual(window.price.value(), price)
            self.click(window.add_button)
            event = window.store.active()[0]
            self.assertEqual(event['background_color'], header)
            self.assertEqual(event['background_bottom_color'], body)
            card = window.wall.danmaku.super_chats._cards[0]
            self.assertEqual(card._colours, (body, header))
            self.assertEqual(window.tile.video_danmaku.super_chats[0]['background_color'], header)
        window.price.setValue(999)
        self.assertEqual(window.tier.currentData(), 500)
        self.assertEqual(window.price.value(), 999)

    def test_expanded_cards_grow_for_all_text_and_reflow_in_list(self):
        window = self.window
        short = window.wall.danmaku.super_chats.height()
        message = '长文本、中文与 English mixed words 应当完整显示。' * 6 + '\n末尾 END gypq'
        window.message.setPlainText(message)
        self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        card = stack._cards[0]
        self.assertGreater(stack.height(), short)
        self.assertEqual(card.message.text(), message)
        self.assertLessEqual(card.message.document().size().height(), card.message.viewport().height())
        window.number.setValue(2)
        window.price.setValue(50)
        window.message.setPlainText('short')
        self.click(window.add_button)
        first, second = stack._cards[:2]
        self.assertGreater(second.height(), first.height())
        self.assertGreater(second.y(), first.geometry().bottom())
        window.number.setValue(3)
        window.price.setValue(100)
        self.click(window.add_button)
        APP.processEvents()
        self.assertEqual(stack._cards[2].message.text(), message)
        self.assertGreater(stack._cards[2].height(), stack._cards[0].height())
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        self.assertEqual(len(sc.card_rects()), 3)
        self.assertGreater(sc.card_rects()[2].height(), sc.card_rects()[0].height())
        sc.presentation.collapse()
        collapsed_height = sc.card_rects()[2].height()
        sc.presentation.expand('1')
        self.assertGreater(sc.card_rects()[2].height(), collapsed_height)
        sc.presentation.expand()
        for size in ((200, 120), (420, 240), (1000, 700)):
            window.tile.video_danmaku.resize(*size)
            rect = sc.card_rects()[0]
            self.assertTrue(window.tile.video_danmaku.rect().contains(rect.toAlignedRect()))
            document = sc_message_document(sc.chats[0], rect.width(), sc._paint_scale)
            self.assertLessEqual(document.size().height() + 61 * sc._paint_scale, rect.height() + 1)

    def test_visibility_opacity_and_isolated_data(self):
        window = self.window
        self.assertNotEqual(Path(config.data_root()), Path(config.REPO))
        self.assertTrue(Path(config.CONFIG_PATH).is_relative_to(Path(config.data_root())))
        window.visible_box.setChecked(False)
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())
        self.assertTrue(window.wall.danmaku.super_chats.isVisible())
        window.visible_box.setChecked(True)
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())
        window.opacity.setValue(35)
        self.assertEqual(window.tile.video_danmaku.super_chat_overlay.opacity, 0.35)
        window.change_theme('light')
        self.assertEqual(window.wall.danmaku.property('appearanceLight'), True)
        window.change_theme('dark')

    def test_expiry_is_driven_by_the_window_timer(self):
        window = self.window
        window.duration.setValue(1)
        self.click(window.add_button)
        QTest.qWait(1400)
        self.assertFalse(window.store.active())
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())

    def test_price_order_and_individual_dismiss_in_list(self):
        window = self.window
        for number, price in ((2, 50), (3, 100), (4, 70), (5, 30), (6, 60)):
            window.number.setValue(number)
            window.price.setValue(price)
            self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        expected = ['3', '4', '6', '2', '1', '5']
        self.assertEqual([chat['id'] for chat in stack._events], expected)
        self.assertEqual(len(stack._cards), 6)
        for first, second in zip(stack._cards, stack._cards[1:]):
            self.assertLess(first.geometry().bottom(), second.y())
            self.assertTrue(first.close_button.isVisible())
        self.click(stack._cards[3].close_button)
        self.assertEqual([chat['id'] for chat in stack._events], expected)
        self.assertEqual(stack.presentation.collapsed_ids, {'2'})
        self.assertEqual(stack._cards[3].close_button.toolTip(), '关闭这条醒目留言')
        self.click(stack._cards[3].close_button)
        expected.remove('2')
        self.assertEqual([chat['id'] for chat in stack._events], expected)
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        self.assertEqual([chat['id'] for chat in sc.chats], expected)
        self.assertEqual(len(sc.card_rects()), 5)
        self.assertTrue(all(button.isVisible() for button in sc.close_buttons[:5]))
        for first, second in zip(sc.card_rects(), sc.card_rects()[1:]):
            self.assertLess(first.bottom(), second.top())
        self.click(sc.close_buttons[3])
        self.assertEqual([chat['id'] for chat in sc.chats], expected)
        self.assertEqual(sc.presentation.collapsed_ids, {'1'})
        self.assertEqual(sc.close_buttons[3].toolTip(), '关闭这条醒目留言')
        self.click(sc.close_buttons[3])
        expected.remove('1')
        self.assertEqual([chat['id'] for chat in sc.chats], expected)

    def test_close_is_local_shared_and_survives_late_update(self):
        window = self.window
        window.number.setValue(2)
        self.click(window.add_button)
        self.click(window.wall.danmaku.super_chats._cards[0].close_button)
        self.assertEqual(len(window.store.active()), 2)
        window.publish()
        self.assertTrue(window.wall.danmaku.super_chats.presentation.is_collapsed('1'))
        self.click(window.wall.danmaku.super_chats._cards[0].close_button)
        self.assertIn('1', window.store.items)
        self.assertEqual([chat['id'] for chat in window.store.active()], ['2'])
        self.assertEqual(window.tile.video_danmaku.super_chats[0]['id'], '2')
        window.number.setValue(1)
        self.click(window.add_button)
        self.assertEqual([chat['id'] for chat in window.store.active()], ['2'])
        QTest.qWait(300)
        window.layout_choice.setCurrentIndex(1)
        self.click(window.tile.video_danmaku.super_chat_overlay.close_button)
        self.assertEqual(len(window.store.active()), 1)
        self.click(window.tile.video_danmaku.super_chat_overlay.close_button)
        self.assertFalse(window.store.active())

    def test_sc_settings_hide_both_surfaces_without_hiding_comments(self):
        window = self.window
        window.sc_enabled.setChecked(False)
        self.assertTrue(window.wall.danmaku.super_chats.isHidden())
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())
        self.assertTrue(window.tile.video_danmaku.enabled)
        self.assertEqual(len(window.store.active()), 1)
        window.sc_enabled.setChecked(True)
        self.assertTrue(window.wall.danmaku.super_chats.isVisible())
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())

    def test_entrance_and_animated_dismiss(self):
        window = self.window
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        with patch.object(motion, 'enabled', return_value=True):
            window.number.setValue(2)
            self.click(window.add_button)
            self.assertEqual(sc.presentation.entrance.duration(), 180)
            sc.presentation.entrance.setCurrentTime(90)
            self.assertGreater(sc.presentation.progress, 0)
            self.assertLess(sc.presentation.progress, 1)
            sc.presentation.entrance.setCurrentTime(180)
            self.assertEqual(sc.presentation.progress, 1)
            self.click(sc.close_buttons[1])
            self.assertIsNone(sc._paper, 'Collapse must not dismiss or animate removal')
            self.assertEqual(len(window.store.active()), 2)
            self.click(sc.close_buttons[1])
            self.assertIsNotNone(sc._paper)
            sc.animation.setCurrentTime(120)
            self.assertGreater(sc._progress, 0)
            sc.animation.setCurrentTime(240)
            APP.processEvents()
            self.assertEqual([chat['id'] for chat in sc.chats], ['1'])
            self.click(sc.close_button)
            self.click(sc.close_button)
            sc.animation.setCurrentTime(240)
            self.assertTrue(sc.isHidden())
            self.assertFalse(sc.presentation.timer.isActive())
        window.layout_choice.setCurrentIndex(0)
        window.number.setValue(3)
        self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        self.assertEqual(stack.presentation.progress, 1)
        self.click(stack._cards[0].close_button)
        self.click(stack._cards[0].close_button)
        stack._cards[0].animation.setCurrentTime(240)
        self.assertTrue(stack.isHidden())

    def test_panel_sc_stays_fixed_while_messages_scroll(self):
        window = self.window
        panel = window.wall.danmaku
        stack = panel.super_chats
        self.assertIs(stack.parentWidget(), panel)
        origin = stack.mapToGlobal(QPoint())
        for index in range(150):
            panel.add_event({'kind': 'danmaku', 'uname': 'fixture', 'text': str(index) * 10})
            self.assertEqual(stack.mapToGlobal(QPoint()).y(), origin.y())
        APP.processEvents()
        origin = stack.mapToGlobal(QPoint())
        bar = panel.body.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        for value in (0, bar.maximum() // 2, bar.maximum()):
            bar.setValue(value)
            APP.processEvents()
            self.assertEqual(stack.mapToGlobal(QPoint()), origin)

    def test_only_clicked_sc_expands_and_new_arrival_is_independent(self):
        window = self.window
        window.number.setValue(2)
        self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        sc = window.tile.video_danmaku.super_chat_overlay
        stack.presentation.collapse()
        self.click(stack._cards[0].name)
        self.assertFalse(stack._cards[0].message.isHidden())
        self.assertTrue(stack._cards[1].message.isHidden())
        self.assertTrue(stack.presentation.is_collapsed('2'))
        window.layout_choice.setCurrentIndex(1)
        sc.presentation.collapse()
        point = sc.card_rects()[1].center().toPoint() - sc._content_origin
        QTest.mouseClick(sc, Qt.LeftButton, pos=point)
        self.assertTrue(sc.presentation.is_collapsed('1'))
        self.assertFalse(sc.presentation.is_collapsed('2'))
        self.assertLess(sc.card_rects()[0].height(), sc.card_rects()[1].height())
        window.number.setValue(3)
        self.click(window.add_button)
        self.assertTrue(sc.presentation.is_collapsed('1'))
        self.assertFalse(sc.presentation.is_collapsed('3'))
        self.assertTrue(stack.presentation.is_collapsed('2'))
        self.assertFalse(stack.presentation.is_collapsed('3'))

    def test_independent_collapse_deadlines_do_not_restart_on_refresh(self):
        from ddm.super_chat import SuperChatPresentation
        from PySide6.QtCore import QObject
        parent = QObject()
        presentation = SuperChatPresentation(parent)
        presentation.configure({'super_chat_collapse_delay': 1})
        with patch('ddm.super_chat.time.monotonic', return_value=100):
            presentation.set_events([{'id': 'a'}])
        with patch('ddm.super_chat.time.monotonic', return_value=100.6):
            presentation.set_events([{'id': 'a'}, {'id': 'b'}])
        with patch('ddm.super_chat.time.monotonic', return_value=101.1):
            presentation._expire()
            self.assertTrue(presentation.is_collapsed('a'))
            self.assertFalse(presentation.is_collapsed('b'))
            presentation.expand('a')
            self.assertEqual(presentation.deadlines['b'], 101.6)
            presentation.set_events([{'id': 'a'}, {'id': 'b'}])
            self.assertEqual(presentation.deadlines['a'], 102.1)
        with patch('ddm.super_chat.time.monotonic', return_value=101.7):
            presentation._expire()
            self.assertFalse(presentation.is_collapsed('a'))
            self.assertTrue(presentation.is_collapsed('b'))
        presentation.set_events([])
        self.assertFalse(presentation.timer.isActive())

    def test_many_cards_expand_independently_without_reordering(self):
        window = self.window
        for number in (2, 3, 4):
            window.number.setValue(number)
            self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        order = [event['id'] for event in stack._events]
        stack.presentation.collapse()
        self.click(stack._cards[2].name)
        self.assertFalse(stack.presentation.is_collapsed(order[2]))
        self.assertTrue(all(stack.presentation.is_collapsed(chat_id) for chat_id in order if chat_id != order[2]))
        self.assertEqual([event['id'] for event in stack._events], order)
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        sc.presentation.collapse()
        sc._activate(sc.card_rects()[2].center())
        self.assertFalse(sc.presentation.is_collapsed(order[2]))
        self.assertTrue(all(sc.presentation.is_collapsed(chat_id) for chat_id in order if chat_id != order[2]))
        self.assertEqual([event['id'] for event in sc.chats], order)
        window.publish()
        self.assertEqual([event['id'] for event in sc.chats], order)
        # Closing a card beyond the old three-card limit still animates.
        with patch.object(motion, 'enabled', return_value=True):
            sc.animate_dismiss(order[3])
            self.assertIsNotNone(sc._paper)
            self.assertEqual(sc._closing_index, 3)
            sc.animation.setCurrentTime(240)

    def test_settings_thumbnail_edits_position_scale_and_resets(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage({'super_chat_position': [.8, .2], 'super_chat_scale': 100})
        page.resize(700, 800)
        page.show()
        APP.processEvents()
        try:
            preview = page.super_chat_placement
            rect = preview.card_rect()
            start = rect.center().toPoint()
            QTest.mousePress(preview, Qt.LeftButton, pos=start)
            QTest.mouseMove(preview, start - QPoint(70, 0))
            QTest.mouseRelease(preview, Qt.LeftButton, pos=start - QPoint(70, 0))
            self.assertLess(page.values()['super_chat_position'][0], .8)
            corner = preview.card_rect().bottomRight().toPoint() - QPoint(2, 2)
            QTest.mousePress(preview, Qt.LeftButton, pos=corner)
            QTest.mouseMove(preview, corner + QPoint(25, 0))
            QTest.mouseRelease(preview, Qt.LeftButton, pos=corner + QPoint(25, 0))
            self.assertGreater(page.values()['super_chat_scale'], 100)
            self.assertEqual(page.super_chat_scale.value(), page.values()['super_chat_scale'])
            restored = DanmakuSettingsPage(page.values())
            self.assertEqual(restored.super_chat_placement.values(), preview.values())
            page.reset()
            self.assertIsNone(page.values()['super_chat_position'])
            self.assertEqual(page.values()['super_chat_scale'], 100)
        finally:
            page.close()

    def test_video_and_panel_positions_are_independent_and_roundtrip(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage({'super_chat_position': [0, .1], 'super_chat_position_sync': False})
        self.addCleanup(page.deleteLater)
        preview = page.super_chat_placement
        self.assertEqual(preview.values()['super_chat_position'], [0, .1])
        self.assertIsNone(preview.values()['super_chat_panel_position'])
        preview.set_layout_mode(1)
        self.assertIsNone(preview.position)
        preview.position = [1, .3]
        preview.set_layout_mode(0)
        self.assertEqual(preview.position, [0, .1])
        preview.position = [.2, .6]
        saved = page.values()
        self.assertEqual(saved['super_chat_panel_position'], [1, .3])
        restored = DanmakuSettingsPage(saved)
        self.addCleanup(restored.deleteLater)
        self.assertEqual(restored.values(), saved)
        preview.set_layout_mode(1)
        QTest.mouseDClick(preview, Qt.LeftButton, pos=preview.card_rect().center().toPoint())
        self.assertIsNone(preview.values()['super_chat_panel_position'])
        self.assertEqual(preview.values()['super_chat_position'], [.2, .6])
        preview.position = [.8, .7]
        page.reset()
        self.assertIsNone(page.values()['super_chat_position'])
        self.assertIsNone(page.values()['super_chat_panel_position'])

    def test_panel_position_does_not_follow_video_position(self):
        window = self.window
        window.change_sc_settings({'super_chat_position': [0, .1], 'super_chat_position_sync': False})
        self.assertIsNone(window.wall.danmaku.super_chats._position)
        window.change_sc_settings({'super_chat_position': [0, .1],
                                   'super_chat_panel_position': [1, .2]})
        self.click(window.add_button)
        APP.processEvents()
        panel = window.wall.danmaku
        self.assertEqual(panel.super_chats._position, [1, .2])
        viewport = panel.body.viewport()
        origin = panel.body.mapTo(panel, viewport.pos())
        self.assertEqual(viewport.width() - (panel.super_chats.x() - origin.x())
                         - panel.super_chats.width(), 8)
        window.change_sc_settings({'super_chat_position': [.4, .8]})
        self.assertEqual(panel.super_chats._position, [1, .2])
        self.assertEqual(window.tile.video_danmaku.settings['super_chat_position'], [.4, .8])
        window.change_sc_settings({'super_chat_panel_position': [0, .5]})
        self.assertEqual(window.tile.video_danmaku.settings['super_chat_position'], [.4, .8])
        self.assertEqual(panel.super_chats._position, [0, .5])
        window.wall.set_fullscreen_tile(window.tile)
        APP.processEvents()
        self.assertEqual(window.tile.video_danmaku.settings['super_chat_position'], [.4, .8])
        window.wall.set_fullscreen_tile(None)
        APP.processEvents()
        self.assertEqual(panel.super_chats._position, [0, .5])

    def test_position_sync_uses_selected_layout_and_can_be_disabled(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage({'super_chat_position': [0, .1],
                                   'super_chat_panel_position': [1, .4], 'super_chat_position_sync': False})
        self.addCleanup(page.deleteLater)
        page.resize(700, 900)
        page.move(-13000, -13000)
        page.show()
        APP.processEvents()
        preview = page.super_chat_placement
        self.assertFalse(page.super_chat_position_sync.isChecked())
        page.super_chat_preview_layout.button(1).click()
        page.super_chat_position_sync.click()
        self.assertTrue(page.values()['super_chat_position_sync'])
        self.assertEqual(page.values()['super_chat_position'], [1, .4])
        preview.position = [.2, .8]
        self.assertEqual(page.values()['super_chat_position'], [.2, .8])
        self.assertEqual(page.values()['super_chat_panel_position'], [.2, .8])
        start = preview.card_rect().center().toPoint()
        QTest.mousePress(preview, Qt.LeftButton, pos=start)
        QTest.mouseMove(preview, start + QPoint(12, -12))
        QTest.mouseRelease(preview, Qt.LeftButton, pos=start + QPoint(12, -12))
        self.assertEqual(page.values()['super_chat_position'], page.values()['super_chat_panel_position'])
        self.assertNotEqual(page.values()['super_chat_position'], [.2, .8])
        restored = DanmakuSettingsPage(page.values())
        self.addCleanup(restored.deleteLater)
        self.assertTrue(restored.super_chat_position_sync.isChecked())
        QTest.mouseDClick(preview, Qt.LeftButton, pos=preview.card_rect().center().toPoint())
        self.assertIsNone(page.values()['super_chat_position'])
        self.assertIsNone(page.values()['super_chat_panel_position'])
        page.super_chat_preview_layout.button(0).click()
        preview.position = [.7, .1]
        self.assertEqual(page.values()['super_chat_panel_position'], [.7, .1])
        page.super_chat_position_sync.click()
        preview.position = [.5, .5]
        self.assertEqual(page.values()['super_chat_panel_position'], [.7, .1])
        page.reset()
        self.assertTrue(page.values()['super_chat_position_sync'])

    def test_sync_defaults_on_and_respects_explicit_saved_off(self):
        from ddm.dialogs import DanmakuSettingsPage
        from ddm.widgets import SuperChatStack
        self.assertTrue(config.DEFAULT_SETTINGS['super_chat_position_sync'])
        settings = {'super_chat_position': [0, .1], 'super_chat_panel_position': [1, .4]}
        for values, enabled in (({}, True), (settings, True),
                                ({**settings, 'super_chat_position_sync': False}, False)):
            page = DanmakuSettingsPage(values)
            self.addCleanup(page.deleteLater)
            self.assertEqual(page.super_chat_position_sync.isChecked(), enabled)
            stack = SuperChatStack()
            self.addCleanup(stack.deleteLater)
            stack.configure(values)
            self.assertEqual(stack._position, values.get('super_chat_position' if enabled
                                                        else 'super_chat_panel_position'))
            if not enabled:
                self.assertEqual(page.values()['super_chat_panel_position'], [1, .4])
                restored = DanmakuSettingsPage(page.values())
                self.addCleanup(restored.deleteLater)
                self.assertFalse(restored.super_chat_position_sync.isChecked())
            page.reset()
            self.assertTrue(page.super_chat_position_sync.isChecked())

    def test_synced_runtime_follows_video_position_and_independent_mode_restores_panel(self):
        window = self.window
        window.change_sc_settings({'super_chat_position': [0, .1],
            'super_chat_panel_position': [1, .4], 'super_chat_position_sync': True})
        self.assertEqual(window.wall.danmaku.super_chats._position, [0, .1])
        window.change_sc_settings({'super_chat_position': [.3, .6]})
        self.assertEqual(window.wall.danmaku.super_chats._position, [.3, .6])
        window.change_sc_settings({'super_chat_position_sync': False})
        self.assertEqual(window.wall.danmaku.super_chats._position, [1, .4])

    def test_collapse_timer_survives_refresh_and_click_reopens(self):
        window = self.window
        stack = window.wall.danmaku.super_chats
        sc = window.tile.video_danmaku.super_chat_overlay
        self.assertGreater(stack.presentation.timer.remainingTime(), 6500)
        self.assertLessEqual(stack.presentation.timer.interval(), 7000)
        window.collapse_delay.setValue(1)
        QTest.qWait(400)
        window.publish()
        QTest.qWait(700)
        self.assertTrue(stack.presentation.collapsed)
        self.assertTrue(sc.presentation.collapsed)
        self.assertLessEqual(stack._cards[0].height(), 37)
        self.assertTrue(stack._cards[0].message.isHidden())
        self.assertEqual(stack._cards[0].price.text(), '¥30')
        self.click(window.add_button)
        self.assertTrue(stack.presentation.collapsed, 'Duplicate updates must not restart the timer')
        self.click(stack._cards[0].name)
        self.assertFalse(stack.presentation.collapsed)
        self.assertFalse(stack._cards[0].message.isHidden())
        window.layout_choice.setCurrentIndex(1)
        point = sc.card_rects()[0].center().toPoint() - sc._content_origin
        QTest.mouseClick(sc, Qt.LeftButton, pos=point)
        self.assertFalse(sc.presentation.collapsed)
        sc.presentation.collapse()
        window.number.setValue(2)
        self.click(window.add_button)
        self.assertFalse(sc.presentation.collapsed, 'A new SC must expand the cards')
        self.assertFalse(stack.presentation.collapsed)

    def test_drag_snap_resize_and_restore(self):
        window = self.window
        window.layout_choice.setCurrentIndex(1)
        overlay = window.tile.video_danmaku
        sc = overlay.super_chat_overlay
        start = sc.card_rects()[0].topLeft().toPoint() + QPoint(60, 16) - sc._content_origin
        origin = sc.card_rects()[0].topLeft().toPoint()
        delta = QPoint(12, 12) - origin
        QTest.mousePress(sc, Qt.LeftButton, pos=start)
        QTest.mouseMove(sc, start + delta)
        QTest.mouseRelease(sc, Qt.LeftButton, pos=start + delta)
        APP.processEvents()
        self.assertEqual(window.sc_settings['super_chat_position'], [0.0, 0.0])
        self.assertAlmostEqual(sc.card_rects()[0].left(), 10)
        self.assertAlmostEqual(sc.card_rects()[0].top(), 10)
        window.resize(1000, 700)
        APP.processEvents()
        self.assertAlmostEqual(sc.card_rects()[0].left(), 10)
        old_width = sc.card_rects()[0].width()
        corner = sc.card_rects()[0].bottomRight().toPoint() - sc._content_origin - QPoint(3, 3)
        QTest.mousePress(sc, Qt.LeftButton, pos=corner)
        QTest.mouseMove(sc, corner + QPoint(50, 0))
        QTest.mouseRelease(sc, Qt.LeftButton, pos=corner + QPoint(50, 0))
        APP.processEvents()
        self.assertGreater(window.sc_settings['super_chat_scale'], 100)
        self.assertEqual(window.sc_scale.value(), window.sc_settings['super_chat_scale'])
        self.assertGreater(sc.card_rects()[0].width(), old_width)
        window.sc_scale.setValue(150)
        self.assertEqual(overlay.settings['super_chat_scale'], 150)
        sc.presentation.collapse()
        for size in ((200, 100), (1200, 700)):
            overlay.resize(*size)
            for rect in sc.card_rects():
                self.assertTrue(overlay.rect().contains(rect.toAlignedRect()))
        saved = dict(window.sc_settings)
        window.change_sc_settings({'super_chat_position': None})
        self.assertGreater(sc.card_rects()[0].left(), 10)
        window.change_sc_settings(saved)
        self.assertAlmostEqual(sc.card_rects()[0].left(), 10)

    def test_expiry_during_drag_releases_the_gesture(self):
        window = self.window
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        point = sc.card_rects()[0].center().toPoint() - sc._content_origin
        QTest.mousePress(sc, Qt.LeftButton, pos=point)
        window.store.expire(now=time.time() + 1000)
        window.publish()
        self.assertTrue(sc.isHidden())
        self.assertIsNone(sc._gesture)
        QTest.mouseMove(sc, point + QPoint(50, 0))
        QTest.mouseRelease(sc, Qt.LeftButton, pos=point)
        self.assertIsNone(window.sc_settings['super_chat_position'])

    def test_master_toggle_controls_comments_and_sc_without_panel(self):
        window = self.window
        window.layout_choice.setCurrentIndex(1)
        APP.processEvents()
        self.assertFalse(window.wall.has_danmaku)
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isVisible())
        window.visible_box.setChecked(False)
        self.assertFalse(window.tile.video_danmaku.enabled)
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())
        window.visible_box.setChecked(True)
        self.assertTrue(window.tile.video_danmaku.enabled)
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isVisible())
        window.layout_choice.setCurrentIndex(0)
        APP.processEvents()
        self.assertTrue(window.wall.danmaku.super_chats.isVisible())

    def test_main_sc_moves_to_panel_and_returns_for_fullscreen(self):
        window = self.window
        window.layout_choice.setCurrentIndex(2)
        small = window.wall._make_tile({'room_id': '2', 'uname': 'Small', 'live': True})
        small.set_video_active(True)
        small.danmaku_button.setChecked(True)
        small.video_danmaku.set_super_chats(window.store.active())
        window.wall.relayout(force=True)
        APP.processEvents()
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())
        self.assertTrue(window.wall.danmaku.super_chats.isVisible())
        self.assertTrue(small.video_danmaku.super_chat_overlay.isVisible())
        window.wall.set_fullscreen_tile(window.tile)
        APP.processEvents()
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isVisible())
        window.wall.set_fullscreen_tile(None)
        APP.processEvents()
        self.assertTrue(window.tile.video_danmaku.super_chat_overlay.isHidden())
        self.assertTrue(window.wall.danmaku.super_chats.isVisible())


def check_native_alpha():
    APP.setStyleSheet(theme.qss())
    window = ScSimulator()
    window.setWindowFlag(Qt.WindowStaysOnTopHint)
    area = APP.primaryScreen().availableGeometry()
    window.setGeometry(area.x() + 20, area.y() + 20,
                       min(1240, area.width() - 40), min(760, area.height() - 40))
    window.show()
    window.layout_choice.setCurrentIndex(1)
    window.activateWindow()
    from ddm.player import TilePlayer
    from ddm.recording import ffmpeg_path
    source = Path(config.REPO) / 'work/test-artifacts/sc-simulator/alpha-blue.mp4'
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        subprocess.run([ffmpeg_path(), '-y', '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30', '-t', '15',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                        str(source)], check=True)
    player = TilePlayer(window.tile.video, window.tile, silent=True)
    try:
        player.play(str(source))
        player._set('panscan', 1.0)
        window.tick()
        QTest.qWait(1000)
        assert float(player._prop('time-pos', 0) or 0) > 0
        def capture():
            video = window.tile.video
            screen = video.screen()
            point = video.mapToGlobal(QPoint()) - screen.geometry().topLeft()
            return screen.grabWindow(0, point.x(), point.y(), video.width(), video.height()).toImage()
        window.sc_enabled.setChecked(False)
        QTest.qWait(250)
        background = capture()
        pixel = background.pixelColor(background.width() // 2, background.height() // 2)
        assert pixel.blue() > 200 and pixel.red() < 35, ('Video baseline', pixel.name())
        window.sc_enabled.setChecked(True)
        window.opacity.setValue(100)
        QTest.qWait(250)
        solid = capture()
        assert window.tile.video_danmaku.super_chat_overlay.width() <= 342
        assert window.tile.video_danmaku.super_chat_overlay.height() <= 118
        point = window.tile.video_danmaku.super_chat_overlay.card_rects()[0].bottomLeft() + QPoint(5, -12)
        scale = solid.devicePixelRatio()
        x, y = round(point.x() * scale), round(point.y() * scale)
        colour = solid.pixelColor(x, y)
        assert colour.name() == super_chat_palette(30)['background_bottom_color'].lower(), colour.name()
        row = solid.height() * 3 // 4
        assert all(solid.pixelColor(i, row) == background.pixelColor(i, row)
                   for i in range(20, solid.width() - 20)), 'SC must not alter the video background outside its cards'
        window.opacity.setValue(35)
        QTest.qWait(250)
        faded = capture().pixelColor(x, y)
        assert faded != colour and faded != background.pixelColor(x, y)
        base = background.pixelColor(x, y)
        for component in ('red', 'green', 'blue'):
            expected = getattr(colour, component)() * .35 + getattr(base, component)() * .65
            assert abs(getattr(faded, component)() - expected) < 15, \
                (component, base.name(), colour.name(), faded.name(), expected)
        output = Path(config.REPO) / 'work/test-artifacts/sc-simulator/native-stack.png'
        now = int(time.time())
        for chat_id, price, colour in (('2', 60, '#00ff00'), ('3', 100, '#ffdd00')):
            window.store.upsert({'id': chat_id, 'price': price, 'uname': 'Native stack',
                                 'message': 'Rear card repaint', 'start_time': now,
                                 'end_time': now + 30, 'background_color': colour})
        window.publish()
        QTest.qWait(100)
        sc = window.tile.video_danmaku.super_chat_overlay
        reveal = sc.card_rects()[1].topRight() + QPoint(-12, 70)
        point = window.mapToGlobal(QPoint()) - window.screen().geometry().topLeft()
        window.screen().grabWindow(0, point.x(), point.y(), window.width(), window.height()).save(str(output))
        closing = time.perf_counter()
        with patch.object(motion, 'enabled', return_value=True):
            sc.close_button.click()
            assert sc.presentation.is_collapsed(sc.chats[0]), 'First click only collapses'
            sc.close_button.click()
        close_ms = (time.perf_counter() - closing) * 1000
        for index in range(20):
            QTest.qWait(20)
            frame = capture()
            pixel = frame.pixelColor(frame.width() // 2, frame.height() // 2)
            assert pixel.blue() > 200 and pixel.red() < 35 and pixel.green() < 35, \
                ('Black flash over actual mpv video during SC close', pixel.name())
            if index >= 8:
                rear = frame.pixelColor(round(reveal.x() * scale), round(reveal.y() * scale))
                expected = QColor(super_chat_palette(60)['background_bottom_color'])
                base = background.pixelColor(round(reveal.x() * scale), round(reveal.y() * scale))
                for component in ('red', 'green', 'blue'):
                    target = getattr(expected, component)() * .35 + getattr(base, component)() * .65
                    assert abs(getattr(rear, component)() - target) < 15, ('Rear official SC colour', rear.name())
        print(f'PASS: SC alpha/close over actual mpv video; no black flash; close dispatch {close_ms:.1f} ms')
    finally:
        player.release()
        window.close()


if __name__ == '__main__':
    if '--native-visual' in sys.argv:
        check_native_alpha()
    else:
        unittest.main()
