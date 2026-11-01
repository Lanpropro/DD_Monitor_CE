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
from PySide6.QtGui import QColor, QImage
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
        preview.resize(420, 190)
        preview.show()
        APP.processEvents()
        for width, height in ((480, 640), (640, 360), (640, 240)):
            frame = QImage(width, height, QImage.Format_RGB32)
            frame.fill(QColor('#204080'))
            preview.set_frame(frame)
            stage = preview.stage_rect()
            self.assertAlmostEqual(stage.width() / stage.height(), width / height)
            point = preview.card_rect().center().toPoint()
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

    def test_expanded_cards_grow_for_all_text_and_reflow_after_selection(self):
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
        small_height = stack.height()
        stack.select_chat('1')
        APP.processEvents()
        self.assertGreater(stack.height(), small_height)
        self.assertEqual(stack._cards[0].message.text(), message)
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        sc.select_chat('1')
        tall = sc.card_rects()[0].height()
        self.assertGreater(tall, 100)
        window.sc_scale.setValue(150)
        self.assertGreater(sc.card_rects()[0].height(), tall)
        sc.presentation.collapse()
        self.assertAlmostEqual(sc.card_rects()[0].height(), 54)
        sc.presentation.expand()
        self.assertGreater(sc.card_rects()[0].height(), tall)
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

    def test_price_order_threshold_selection_and_dismiss_reveal(self):
        window = self.window
        window.number.setValue(2)
        window.price.setValue(50)
        self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        self.assertEqual([chat['id'] for chat in stack._events], ['2', '1'])
        self.assertFalse(stack._cards[0].geometry().intersects(stack._cards[1].geometry()))
        self.assertFalse(stack.more.isVisible())
        for number, price in ((3, 100), (4, 70)):
            window.number.setValue(number)
            window.price.setValue(price)
            self.click(window.add_button)
        self.assertEqual([chat['id'] for chat in stack._events], ['3', '4', '2', '1'])
        self.assertTrue(stack._cards[0].geometry().intersects(stack._cards[1].geometry()))
        QTest.mouseClick(stack._cards[1], Qt.LeftButton, pos=QPoint(24, 8))
        APP.processEvents()
        self.assertEqual(stack._cards[0].chat_id, '4')
        window.publish()
        self.assertEqual(stack._cards[0].chat_id, '4', 'Selection must survive the next event/timer update')
        self.click(stack.more)
        self.assertEqual(stack._cards[0].chat_id, '2')
        window.layout_choice.setCurrentIndex(1)
        sc = window.tile.video_danmaku.super_chat_overlay
        self.assertEqual(sc.chats[0]['id'], '3')
        point = sc.card_rects()[1].topLeft().toPoint() + QPoint(24, 8) - sc._content_origin
        QTest.mouseClick(sc, Qt.LeftButton, pos=point)
        self.assertEqual(sc.chats[0]['id'], '4')
        self.click(sc.close_button)
        self.assertEqual([chat['id'] for chat in sc.chats], ['3', '2', '1'])
        self.assertEqual(sc.presentation.progress, 1.0)
        self.assertEqual(sc.chats[0]['id'], '3')

        self.click(sc.close_button)
        QTest.qWait(300)
        self.assertEqual([chat['id'] for chat in sc.chats], ['2', '1'])
        self.assertFalse(sc.card_rects()[0].intersects(sc.card_rects()[1]))
        self.click(sc.close_buttons[1])
        QTest.qWait(300)
        self.assertEqual([chat['id'] for chat in sc.chats], ['2'])

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

    def test_stack_switch_moves_cards_in_both_renderers(self):
        window = self.window
        for number in (2, 3):
            window.number.setValue(number)
            self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        with patch.object(motion, 'enabled', return_value=True):
            before = {str(event['id']): card.geometry() for event, card in zip(stack._events, stack._cards)}
            stack.select_chat('2')
            stack.switch_animation.setCurrentTime(90)
            middle = stack._cards[0].geometry()
            stack.switch_animation.setCurrentTime(180)
            self.assertNotEqual(middle, stack._cards[0].geometry())
            self.assertNotEqual(before['2'], stack._cards[0].geometry())
            window.layout_choice.setCurrentIndex(1)
            sc = window.tile.video_danmaku.super_chat_overlay
            sc.select_chat('2')
            sc.switch_animation.setCurrentTime(90)
            middle = sc.card_rects()[0]
            sc.switch_animation.setCurrentTime(180)
            self.assertNotEqual(middle, sc.card_rects()[0])
            # A second selection during motion must start from the displayed positions.
            sc.select_chat('3')
            sc.switch_animation.setCurrentTime(60)
            visible = {str(chat['id']): rect for chat, rect in zip(sc.chats, sc.card_rects())}
            sc.select_chat('1')
            self.assertEqual(sc.card_rects()[0], visible['1'])
            sc.switch_animation.setCurrentTime(180)
        with patch.object(motion, 'enabled', return_value=False):
            stack.select_chat('3')
            self.assertNotEqual(stack.switch_animation.state(), stack.switch_animation.State.Running)

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
