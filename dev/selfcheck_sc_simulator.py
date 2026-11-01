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
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class SimulatorTests(unittest.TestCase):
    def test_thumbnail_real_frame_ratio_and_opacity(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage(dict(config.DEFAULT_SETTINGS))
        self.addCleanup(page.close)
        preview = page.super_chat_placement
        preview.setParent(None)
        self.addCleanup(preview.close)
        preview.resize(800, 360)
        preview.show()
        APP.processEvents()
        for width, height in ((480, 640), (640, 360), (640, 240)):
            frame = QImage(width, height, QImage.Format_RGB32)
            frame.fill(QColor('#204080'))
            preview.set_frame(frame)
            stage = preview.stage_rect()
            self.assertAlmostEqual(stage.width() / stage.height(), width / height)
            rect = preview.card_rect()
            point = QPoint(round(rect.center().x()), round(rect.bottom()) - 2)
            page.super_chat_opacity.setValue(100)
            solid = preview.grab().toImage().pixelColor(point)
            page.super_chat_opacity.setValue(35)
            faded_image = preview.grab().toImage()
            faded = faded_image.pixelColor(point)
            base = QColor('#204080')
            self.assertNotEqual(faded, solid)
            for component in ('red', 'green', 'blue'):
                expected = getattr(solid, component)() * .35 + getattr(base, component)() * .65
                self.assertLessEqual(abs(getattr(faded, component)() - expected), 2)
            self.assertEqual(faded_image.pixelColor(stage.center().toPoint()), base)
        self.assertNotIn('sc_preview_frame', page.values())
        page.reset()
        self.assertEqual(preview.opacity, config.DEFAULT_SETTINGS['super_chat_opacity'])
        self.assertEqual(preview.frame.size(), frame.size())

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

    def test_layout_previews_share_position_scale_and_opacity(self):
        from ddm.dialogs import DanmakuSettingsPage
        page = DanmakuSettingsPage(dict(config.DEFAULT_SETTINGS))
        self.addCleanup(page.close)
        page.resize(700, 900)
        page.show()
        APP.processEvents()
        preview = page.super_chat_placement
        page.super_chat_preview_layout.setCurrentIndex(1)
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
        self.assertNotEqual(before['super_chat_position'], preview.position)
        changed = preview.values()
        page.super_chat_preview_layout.setCurrentIndex(0)
        self.assertEqual(preview.layout_mode, 'video')
        self.assertEqual(preview.values(), changed)
        page.super_chat_opacity.setValue(45)
        page.super_chat_preview_layout.setCurrentIndex(1)
        self.assertEqual(preview.opacity, 45)
        page.reset()
        self.assertIsNone(preview.position)

    def test_thumbnail_captures_decoded_frame_without_desktop(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from ddm.app import MainWindow
        tile = object()
        # A padded stride must not become part of the image's aspect ratio.
        pixel = bytes((128, 64, 32, 0))
        core = Mock()
        core.command.return_value = dict(format='bgr0', w=3, h=4, stride=16, data=pixel * 16)
        window = SimpleNamespace(_fullscreen_tile=None,
            wall=SimpleNamespace(danmaku_target_tile=lambda: tile),
            players={tile: SimpleNamespace(player=core)})
        image = MainWindow._sc_preview_frame(window)
        self.assertAlmostEqual(image.width() / image.height(), 3 / 4)
        self.assertEqual(image.pixelColor(0, 0), QColor('#204080'))
        core.command.assert_called_once_with('screenshot-raw', 'video')
        for error in (ValueError('No frame'), SystemError('Error running mpv command', -12)):
            core.command.side_effect = error
            self.assertTrue(MainWindow._sc_preview_frame(window).isNull())

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
        expected.remove('1')
        self.assertEqual([chat['id'] for chat in sc.chats], expected)

    def test_close_is_local_shared_and_survives_late_update(self):
        window = self.window
        window.number.setValue(2)
        self.click(window.add_button)
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
            self.assertIsNotNone(sc._paper)
            sc.animation.setCurrentTime(120)
            self.assertGreater(sc._progress, 0)
            sc.animation.setCurrentTime(240)
            APP.processEvents()
            self.assertEqual([chat['id'] for chat in sc.chats], ['1'])
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
