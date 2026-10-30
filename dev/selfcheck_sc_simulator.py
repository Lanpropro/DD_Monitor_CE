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
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])


class SimulatorTests(unittest.TestCase):
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

    def test_entrance_and_immediate_dismiss(self):
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
            self.assertEqual([chat['id'] for chat in sc.chats], ['1'])
            self.click(sc.close_button)
            self.assertTrue(sc.isHidden())
            self.assertFalse(sc.presentation.timer.isActive())
        window.layout_choice.setCurrentIndex(0)
        window.number.setValue(3)
        self.click(window.add_button)
        stack = window.wall.danmaku.super_chats
        self.assertEqual(stack.presentation.progress, 1)
        self.click(stack._cards[0].close_button)
        self.assertTrue(stack.isHidden())

    def test_collapse_timer_survives_refresh_and_click_reopens(self):
        window = self.window
        stack = window.wall.danmaku.super_chats
        sc = window.tile.video_danmaku.super_chat_overlay
        self.assertEqual(stack.presentation.timer.interval(), 7000)
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
        point = window.tile.video_danmaku.super_chat_overlay.card_rects()[0].bottomLeft() + QPoint(18, -10)
        scale = solid.devicePixelRatio()
        x, y = round(point.x() * scale), round(point.y() * scale)
        colour = solid.pixelColor(x, y)
        assert colour.red() > 220 and colour.green() > 180 and colour.blue() < 40, colour.name()
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
        reveal = sc.card_rects()[1].topLeft() + QPoint(20, 70)
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
                assert rear.green() > 60 and rear.red() < 35, ('Rear SC must reveal green, not black', rear.name())
        print(f'PASS: SC alpha/close over actual mpv video; no black flash; close dispatch {close_ms:.1f} ms')
    finally:
        player.release()
        window.close()


if __name__ == '__main__':
    if '--native-visual' in sys.argv:
        check_native_alpha()
    else:
        unittest.main()
