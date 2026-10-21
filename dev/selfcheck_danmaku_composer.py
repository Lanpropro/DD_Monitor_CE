"""真实 Qt 控件回归：逐房间草稿、表情分流、异步失败和过期请求隔离。"""
import importlib.util
import os
from pathlib import Path
import sys
import threading
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent, QInputMethodEvent, QKeyEvent, QPixmap, QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QToolButton
from ddm import bili, config, images, theme

APP = QApplication.instance() or QApplication([])


def settle(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError("后台请求未在限时内完成")


class ComposerTests(unittest.TestCase):
    def test_emoticon_launcher_color_only_tracks_open_menu(self):
        with patch.object(bili, 'get_emoticons', return_value=[]):
            button = self.composer.emote_button
            self.assertEqual(button.focusPolicy(), Qt.NoFocus)
            button.setProperty('hovered', False)
            closed = button.grab().toImage()
            button.setProperty('hovered', True)
            self.assertEqual(button.grab().toImage(), closed)
            self.composer.open_emoticons()
            self.assertTrue(button.property('menuOpen'))
            self.assertNotEqual(button.grab().toImage(), closed)
            self.composer.popup.hide()
            self.assertFalse(button.property('menuOpen'))
            self.assertEqual(button.grab().toImage(), closed)
            # Keep the API stub alive until the catalog worker has finished.
            settle(lambda: self.composer._catalog_pending is None)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cache_root = patch.object(config, 'REPO', directory.name)
        cache_root.start()
        self.addCleanup(cache_root.stop)
        self.assertIsNotNone(importlib.util.find_spec("ddm.danmaku_send"), "缺少独立的弹幕输入控件")
        from ddm.danmaku_send import DanmakuComposer
        self.saved = (bili.SESSION_DATA, bili.BILI_JCT, bili.BUVID3)
        bili.set_login_cookies("test-session", "test-csrf", "device-test")
        self.composer = DanmakuComposer()
        self.composer.set_room("101")
        self.composer.resize(360, self.composer.HEIGHT)
        self.composer.show()
        APP.processEvents()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        from ddm.danmaku_send import _active_requests
        for worker in list(_active_requests):
            worker.wait(3000)
        APP.processEvents()
        self.composer.close()
        bili.set_login_cookies(*self.saved)
        APP.processEvents()

    def test_success_clears_only_the_sending_rooms_draft(self):
        from ddm.danmaku_send import DanmakuComposer
        other = DanmakuComposer()
        other.set_room("202")
        other.edit.setText("房间二的草稿")
        self.composer.edit.setText("房间一")
        with patch.object(bili, "send_danmaku", return_value={"code": 0}) as send:
            QTest.keyClick(self.composer.edit, Qt.Key_Return)
            settle(lambda: not self.composer.busy)
        self.assertEqual(self.composer.edit.text(), "")
        self.assertEqual(other.edit.text(), "房间二的草稿")
        self.assertEqual(send.call_args.args, ("101", "房间一"))
        other.close()

    def test_catalog_survives_new_tile_and_restart_and_refresh_replaces_it(self):
        from ddm.danmaku_send import DanmakuComposer, _catalog_path
        packs = [{'pkg_type': 3, 'pkg_name': '表情', 'emoticons': []}]
        with patch.object(bili, 'get_emoticons', return_value=packs) as fetch:
            self.composer.open_emoticons()
            settle(lambda: self.composer._packages is not None)
            self.composer.popup.hide()
            for _ in range(2):
                other = DanmakuComposer()
                other.set_room('101')
                try:
                    other.open_emoticons()
                    self.assertEqual(other._packages, packs)
                    self.assertEqual(fetch.call_count, 1)
                finally:
                    other.shutdown()
                    other.close()
            self.assertNotIn('test-session', _catalog_path('101', self.composer._auth).read_text())
            self.composer._reload_emoticons()
            settle(lambda: self.composer._catalog_pending is None)
            self.assertEqual(fetch.call_count, 2)

    def test_catalog_isolated_by_account_and_corrupt_cache_is_refetched(self):
        from ddm.danmaku_send import _catalog_path, _save_catalog, _load_catalog
        packs = [{'pkg_type': 3, 'pkg_name': '表情', 'emoticons': []}]
        _save_catalog('101', self.composer._auth, packs)
        self.assertIsNone(_load_catalog('101', ('other-account', 'other-csrf')))
        self.assertIsNone(_load_catalog('202', self.composer._auth))
        _catalog_path('101', self.composer._auth).write_text('{broken', encoding='utf-8')
        with patch.object(bili, 'get_emoticons', return_value=packs) as fetch:
            self.composer.open_emoticons()
            settle(lambda: self.composer._packages is not None)
            fetch.assert_called_once()

    def test_failure_retains_draft_and_shows_reason(self):
        self.composer.edit.setText("保留我")
        with patch.object(bili, "send_danmaku", side_effect=ValueError("发送频率过快")):
            self.composer.send_button.click()
            settle(lambda: not self.composer.busy)
        self.assertEqual(self.composer.edit.text(), "保留我")
        self.assertIn("发送频率过快", self.composer.feedback.text())
        self.assertTrue(self.composer.send_button.isEnabled())

    def test_small_emoticon_inserts_emoji_at_cursor(self):
        self.composer.edit.setText("前后")
        self.composer.edit.setCursorPosition(1)
        with patch.object(bili, "send_danmaku") as send:
            self.composer.choose_emoticon(3, {"emoji": "[doge]", "emoticon_unique": "emoji_9", "perm": 1})
        self.assertEqual(self.composer.edit.text(), "前[doge]后")
        send.assert_not_called()

    def test_emoticon_icon_is_legible_without_a_font_glyph_in_both_themes(self):
        button = self.composer.emote_button
        original_font = button.font()
        try:
            tiny_font = button.font()
            tiny_font.setPixelSize(1)
            button.setFont(tiny_font)
            for mode in ("dark", "light"):
                theme.apply(mode)
                button.clearFocus()
                APP.processEvents()
                image = button.grab().toImage()
                scale = image.devicePixelRatioF()
                ink = []
                foreground = theme.qcolor(theme.TEXT2)
                background = image.pixelColor(round(2*scale), round(14*scale))
                alpha = foreground.alphaF()
                expected = QColor(*(round(foreground.getRgb()[i]*alpha + background.getRgb()[i]*(1-alpha))
                                    for i in range(3)))
                for y in range(image.height()):
                    for x in range(image.width()):
                        pixel = image.pixelColor(x, y)
                        if max(abs(pixel.red()-expected.red()), abs(pixel.green()-expected.green()),
                               abs(pixel.blue()-expected.blue())) < 12:
                            ink.append((x/scale, y/scale))
                self.assertTrue(ink)
                left, right = min(x for x, y in ink), max(x for x, y in ink)
                top, bottom = min(y for x, y in ink), max(y for x, y in ink)
                self.assertGreaterEqual(right-left, 15, "表情图标不能退化成很小的字体字符")
                self.assertGreaterEqual(bottom-top, 15)
                self.assertGreater(left, 2)
                self.assertLess(right, button.width()-2)
                self.assertEqual(button.accessibleName(), "选择直播间表情")
        finally:
            button.setFont(original_font)
            theme.apply("dark")

    def test_large_emoticons_send_full_unique_without_touching_draft(self):
        for pkg_type in (1, 2, 5):
            with self.subTest(pkg_type=pkg_type):
                self.composer.edit.setText("文字草稿")
                with patch.object(bili, "send_danmaku", return_value={"code": 0}) as send:
                    self.composer.choose_emoticon(pkg_type, {
                        "emoji": "好", "emoticon_unique": "room_101_123456", "perm": 1})
                    settle(lambda: not self.composer.busy)
                self.assertEqual(send.call_args.args, ("101", "room_101_123456"))
                self.assertEqual(send.call_args.kwargs["dm_type"], 1)
                self.assertEqual(self.composer.edit.text(), "文字草稿")

    def test_locked_unknown_or_incomplete_emoticons_never_send(self):
        with patch.object(bili, "send_danmaku") as send:
            for pkg, emote in ((2, {"emoji": "锁定", "perm": 0, "emoticon_unique": "room_101_3"}),
                               (8, {"emoji": "未知", "perm": 1, "emoticon_unique": "a"}),
                               (1, {"emoji": "缺标识", "perm": 1})):
                self.composer.choose_emoticon(pkg, emote)
        send.assert_not_called()

    def test_pending_send_blocks_duplicates_and_keeps_ui_responsive(self):
        entered, release = threading.Event(), threading.Event()
        def send(*args, **kwargs):
            entered.set()
            release.wait(2)
            return {"code": 0}
        self.composer.edit.setText("发送中")
        with patch.object(bili, "send_danmaku", side_effect=send) as sending:
            self.composer.send_button.click()
            settle(entered.is_set)
            self.assertTrue(self.composer.busy)
            self.assertFalse(self.composer.send_button.isEnabled())
            self.composer.send_text()
            self.composer.choose_emoticon(1, {"perm": 1, "emoticon_unique": "official_1"})
            self.composer.edit.setText("下一条草稿")
            release.set()
            settle(lambda: not self.composer.busy)
        self.assertEqual(sending.call_count, 1)
        self.assertEqual(self.composer.edit.text(), "下一条草稿")

    def test_room_or_account_change_ignores_old_send_completion(self):
        for changed in ("room", "account"):
            with self.subTest(changed=changed):
                self.composer.set_room("101")
                bili.set_login_cookies("test-session", "test-csrf", "device-test")
                release = threading.Event()
                self.composer.edit.setText("旧消息")
                with patch.object(bili, "send_danmaku", side_effect=lambda *a, **kw: release.wait(2)):
                    self.composer.send_text()
                    if changed == "room":
                        self.composer.set_room("202")
                    else:
                        bili.set_sessdata("other-session")
                    self.composer.edit.setText("新的草稿")
                    release.set()
                    settle(lambda: not self.composer.busy)
                self.assertEqual(self.composer.edit.text(), "新的草稿")

    def test_ime_and_text_shortcuts_do_not_trigger_player_actions(self):
        edit = self.composer.edit
        event = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_F, Qt.NoModifier, "f")
        event.ignore()
        APP.sendEvent(edit, event)
        self.assertTrue(event.isAccepted())
        with patch.object(bili, "send_danmaku") as send:
            edit.setText("已有草稿")
            APP.sendEvent(edit, QInputMethodEvent("拼音", []))
            QTest.keyClick(edit, Qt.Key_Return)
            APP.processEvents()
        send.assert_not_called()

    def test_tile_composer_layout_platform_switch_and_theme(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "主播", "live": True})
        tile.show()
        try:
            for mode in ("dark", "light"):
                theme.apply(mode)
                for width, height in ((900, 520), (360, 230), (200, 200)):
                    tile.resize(width, height)
                    APP.processEvents()
                    if width >= 600:
                        self.assertTrue(tile.composer.isVisible())
                    elif width < 280:
                        self.assertFalse(tile.composer.isVisible())
                    self.assertLess(tile.video.geometry().bottom(), tile.bottom.y())
                    self.assertIs(tile.composer.parent(), tile.bottom)
                    if tile.composer.isVisible():
                        self.assertTrue(tile.bottom.rect().contains(tile.composer.geometry()))
                        self.assertLess(tile.composer.geometry().bottom(), tile.height())
                        self.assertGreater(tile.composer.edit.width(), 40)
                    self.assertEqual(tile.composer.emote_button.size().toTuple(),
                                     (theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT))
                    self.assertEqual(tile.composer.send_button.size().toTuple(),
                                     (52, theme.TILE_CONTROL_HEIGHT))
                    self.assertEqual(tile.pause_button.width(), 26 if width < 260 else 34)
                    for control in (tile.composer, tile.composer.edit,
                                    tile.composer.emote_button, tile.composer.send_button):
                        self.assertEqual(control.height(), tile.pause_button.height())
                    self.assertEqual(tile.bottom.layout().contentsMargins().top(), 4)
                    self.assertTrue(tile.composer.feedback.isHidden())
            tile.set_room({"room_id": "douyu:1", "uname": "斗鱼"})
            APP.processEvents()
            self.assertFalse(tile.composer.isVisible())
            tile.set_room(None)
            APP.processEvents()
            self.assertFalse(tile.composer.isVisible())
        finally:
            theme.apply("dark")
            tile.close()

    def test_send_accent_tracks_text_and_compact_volume_opens_upward(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "Test"})
        tile.resize(1280, 500)
        tile.show()
        APP.processEvents()
        try:
            composer = tile.composer
            self.assertEqual(composer.width(), 520)
            self.assertLessEqual(abs(composer.geometry().center().x() - tile.bottom.width() / 2), 2)
            geometry = composer.geometry()
            for status in ("未开播", "缓冲中…", "断流，准备重连"):
                tile.set_status(status)
                self.assertEqual(tile.status_label.text(), "")
                self.assertEqual(tile._status_text, status)
                self.assertEqual(composer.geometry(), geometry)
            tile.set_buffering(True)
            self.assertTrue(tile._buffering)
            self.assertEqual(tile.status_label.text(), "")
            tile.set_buffering(False)
            for text, active in (("", False), ("   ", False), ("hello", True), ("", False)):
                composer.edit.setText(text)
                self.assertEqual(composer.send_button.property("hasText"), active)
                self.assertEqual(composer.send_button.isEnabled(), active)
            for mode in ("dark", "light"):
                theme.apply(mode)
                composer.edit.setText("hello")
                composer.send_button.setAttribute(Qt.WA_UnderMouse, False)
                APP.processEvents()
                button_image = composer.send_button.grab().toImage()
                scale = button_image.devicePixelRatioF()
                self.assertEqual(button_image.pixelColor(round(8 * scale), round(13 * scale)),
                                 theme.qcolor(theme.ACCENT))
            tile.resize(360, 240)
            APP.processEvents()
            self.assertTrue(tile.volume_slider.isHidden())
            self.assertTrue(tile.volume_label.isHidden())
            self.assertTrue(tile.danmaku_settings_button.isVisible())
            self.assertTrue(tile.recording_button.isVisible())
            tile.set_volume(100)
            APP.sendEvent(tile.volume_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            APP.processEvents()
            anchor = tile.volume_button.mapToGlobal(tile.volume_button.rect().topLeft())
            self.assertLess(tile.volume_menu.geometry().bottom(), anchor.y())
            self.assertEqual(tile.vertical_volume.orientation(), Qt.Vertical)
            self.assertLessEqual(tile.volume_menu.width(), 50)
            self.assertLessEqual(tile.volume_menu.height(), 128)
            self.assertLessEqual(tile.vertical_volume_label.fontMetrics().horizontalAdvance("100"),
                                 tile.vertical_volume_label.width())
            self.assertTrue(tile.volume_menu.testAttribute(Qt.WA_TranslucentBackground))
            self.assertLess(tile.volume_menu.grab().toImage().pixelColor(0, 0).alpha(), 30)
            popup_image = tile.volume_menu.grab().toImage()
            scale = popup_image.devicePixelRatioF()
            self.assertGreater(popup_image.pixelColor(round(6 * scale), round(20 * scale)).alpha(), 240)
            self.assertEqual(tile.vertical_volume_label.font().pixelSize(), theme.FONT_CAPTION)
            tile.vertical_volume.setValue(73)
            self.assertEqual(tile.volume, 73)
            self.assertEqual(tile.volume_slider.value(), 73)
            tile.set_volume(28)
            self.assertEqual(tile.vertical_volume.value(), 28)
            self.assertEqual(tile.vertical_volume_label.text(), "28")
            for width in (280, 420, 599, 600, 720):
                tile.resize(width, 300)
                APP.processEvents()
                self.assertEqual(tile.volume_label.isHidden(), tile.volume_slider.isHidden())
                self.assertEqual(tile.volume_label.isHidden(), width < 600)
            self.assertFalse(tile.volume_menu.isVisible())
            self.assertEqual(tile.volume, 28)
        finally:
            tile.volume_menu.close()
            tile.close()
            theme.apply("dark")

    def test_compact_volume_hover_does_not_replace_mute_or_steal_focus(self):
        from ddm.widgets import Tile
        tile = Tile({'room_id': '101', 'muted': True})
        tile.resize(360, 240)
        tile.show()
        APP.processEvents()
        changes = []
        tile.muteToggled.connect(lambda room, muted: changes.append(muted))
        try:
            tile.composer.edit.setFocus()
            APP.processEvents()
            focus = APP.focusWidget()
            APP.sendEvent(tile.volume_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            self.assertTrue(tile.volume_menu.isVisible())
            self.assertIsNone(APP.activePopupWidget())
            self.assertIs(APP.focusWidget(), focus)
            self.assertTrue(tile.muted)
            self.assertIn('悬停', tile.volume_button.toolTip())
            QTest.mouseClick(tile.volume_button, Qt.LeftButton)
            self.assertFalse(tile.muted)
            QTest.mouseClick(tile.volume_button, Qt.LeftButton)
            self.assertTrue(tile.muted)
            self.assertEqual(changes, [False, True])
            APP.sendEvent(tile.volume_button, QEvent(QEvent.Leave))
            APP.sendEvent(tile.volume_menu, QEnterEvent(QPointF(), QPointF(), QPointF()))
            QTest.qWait(180)
            self.assertTrue(tile.volume_menu.isVisible())
            outside = tile.mapToGlobal(tile.rect().topRight())
            with patch('ddm.widgets.QCursor.pos', return_value=outside):
                tile.vertical_volume.setSliderDown(True)
                tile._hide_volume_popup_if_outside()
                self.assertTrue(tile.volume_menu.isVisible())
                tile.vertical_volume.setSliderDown(False)
                QTest.qWait(180)
                self.assertFalse(tile.volume_menu.isVisible())
        finally:
            tile.close()

    def test_hover_volume_popup_closes_with_its_controls_and_owner(self):
        from ddm.widgets import Tile
        tile = Tile({'room_id': '101'})
        tile.resize(360, 240)
        tile.show()
        APP.processEvents()
        try:
            APP.sendEvent(tile.volume_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            self.assertTrue(tile.volume_menu.isVisible())
            tile.bottom.hide()
            self.assertFalse(tile.volume_menu.isVisible())
            tile.bottom.show()
            APP.sendEvent(tile.volume_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            self.assertTrue(tile.volume_menu.isVisible())
            tile.hide()
            self.assertFalse(tile.volume_menu.isVisible())
            tile.show()
            tile.resize(720, 300)
            APP.processEvents()
            APP.sendEvent(tile.volume_button, QEnterEvent(QPointF(), QPointF(), QPointF()))
            self.assertFalse(tile.volume_menu.isVisible())
            tile.set_muted(True)
            QTest.mouseClick(tile.volume_button, Qt.LeftButton)
            self.assertFalse(tile.muted)
        finally:
            tile.close()

    def test_expired_emoticon_login_uses_notice_without_floating_feedback(self):
        notices = []
        self.composer.noticeRequested.connect(lambda text, login: notices.append((text, login)))
        with patch.object(bili, "get_emoticons", side_effect=ValueError("账号未登录")):
            self.composer.open_emoticons()
            settle(lambda: bool(notices))
        self.assertEqual(notices, [("账号未登录", True)])
        self.assertFalse(self.composer.popup.isVisible())
        self.assertTrue(self.composer.feedback.isHidden())

    def test_own_uid_marks_message_and_white_frame_survives_resize(self):
        from types import SimpleNamespace
        from ddm.danmaku import _Handler
        from ddm.widgets import Tile, DanmakuPanel
        received = []
        handler = _Handler(received.append)
        message = SimpleNamespace(dm_type=0, mode_info={}, uname="Test", msg="same text", uid=42)
        for uid, expected in ((42, True), (43, False), (0, False)):
            handler._on_danmaku(SimpleNamespace(uid=uid), message)
            self.assertEqual(received[-1]["self_sent"], expected)
        tile = Tile({"room_id": "101"})
        tile.resize(900, 400)
        tile.show()
        APP.processEvents()
        overlay = tile.video_danmaku
        panel = DanmakuPanel()
        try:
            for dpr in (1, 1.75, 2):
                with patch.object(overlay, "devicePixelRatioF", return_value=dpr):
                    image = overlay._render_text("Test", QColor("#ff0000"), True).toImage()
                    scale = image.devicePixelRatioF()
                    border = image.pixelColor(image.width() // 2, round(1.6 * scale))
                    self.assertGreater(border.alpha(), 100)
                    self.assertGreater(border.green(), 220)
            emote = QPixmap(24, 24)
            emote.fill(QColor("#00a1d6"))
            overlay._images["fixture-emote"] = emote.toImage()
            framed = overlay._render_content("[e]", QColor("#ffffff"),
                                             [("[e]", "fixture-emote")], True).toImage()
            self.assertGreater(framed.pixelColor(framed.width() // 2,
                               round(1.6 * framed.devicePixelRatioF())).alpha(), 100)
            tile.set_video_active(True)
            tile.danmaku_button.setChecked(True)
            self.assertTrue(overlay.add_event({"text": "own", "self_sent": True}))
            overlay._resize_comments()
            self.assertTrue(overlay.comments[0].self_sent)
            panel.add_event({"uname": "Test", "text": "own", "self_sent": True})
            self.assertTrue(panel._blocks[-1]["self_sent"])
            self.assertIn(theme.PINK, panel._block_html(panel._blocks[-1]))
            panel.add_event({"uname": "Other", "text": "same text"})
            self.assertNotIn("▍", panel._block_html(panel._blocks[-1]))
        finally:
            panel.close()
            tile.close()

    def test_existing_composer_and_popup_follow_theme_without_losing_draft(self):
        from ddm.danmaku_send import EmoticonPopup
        popup = EmoticonPopup(self.composer)
        popup.set_packages([{"pkg_type": 3, "pkg_name": "小表情", "emoticons": [
            {"emoji": "[微笑]", "perm": 1}]}])
        self.composer.edit.setText("保留草稿")
        popup.show()
        try:
            settle(lambda: bool(popup.scroll.findChildren(QToolButton)))
            for mode in ("dark", "light", "dark", "light"):
                theme.apply(mode)
                APP.processEvents()
                self.assertEqual(self.composer.edit.text(), "保留草稿")
                self.assertEqual(self.composer.edit.font().pixelSize(), theme.FONT_CAPTION)
                self.assertEqual(self.composer.edit.palette().color(QPalette.PlaceholderText),
                                 theme.qcolor(theme.TEXT3))
                self.assertIn(f"#EmoticonStatus {{color: {theme.TEXT3};", popup.styleSheet())
                button = popup.scroll.findChildren(QToolButton)[0]
                self.assertEqual(button.font().pixelSize(), theme.FONT_CAPTION)
                self.assertEqual(button.size().toTuple(), (56, 56))
                self.assertEqual(popup.tabs.tabRect(0).size().toTuple(), (40, 40))
                self.assertEqual(popup.retry_button.height(), theme.TILE_CONTROL_HEIGHT)
        finally:
            popup.close()
            theme.apply("dark")

    def test_room_switch_preserves_codec_reset_and_danmaku_tooltips(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "First"})
        try:
            tile.codec_probe_note = "previous codec"
            tile.codec_reconnect_pending = True
            tile.danmaku_button.setChecked(True)
            self.assertTrue(tile.room["video_danmaku_enabled"])
            self.assertIn("关闭", tile.danmaku_button.toolTip())
            tile.set_room({"room_id": "202", "uname": "Second"})
            self.assertEqual(tile.codec_probe_note, "")
            self.assertFalse(tile.codec_reconnect_pending)
            self.assertEqual(tile.composer._room_id, "202")
            self.assertFalse(tile.danmaku_button.isChecked())
            self.assertIn("开启", tile.danmaku_button.toolTip())
        finally:
            tile.close()

    def test_popup_renders_packages_permissions_empty_error_and_real_selection(self):
        packs = [{"pkg_type": 3, "pkg_name": "小表情", "emoticons": [
            {"emoji": "[doge]", "perm": 1, "url": "https://example.com/emote.png"}]},
            {"pkg_type": 2, "pkg_name": "主播表情", "emoticons": [
                {"emoji": "锁定", "perm": 0, "emoticon_unique": "room_101_4", "unlock_show_text": "粉丝团"}]}]
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor("#00a1d6"))
        with patch.object(bili, "get_emoticons", return_value=packs), patch.object(images, "load_pixmap", return_value=pixmap):
            self.composer.emote_button.click()
            popup = self.composer.popup
            settle(lambda: any(b.text() == "[doge]" for b in popup.findChildren(QToolButton)))
            self.assertEqual([popup.tabs.tabText(i) for i in range(popup.tabs.count())], ["小表情", "主播表情"])
            popup.tabs.setCurrentIndex(1)
            settle(lambda: any(b.text() == "锁定" for b in popup.findChildren(QToolButton)))
            buttons = popup.findChildren(QToolButton)
            locked = next(b for b in buttons if b.text() == "锁定")
            self.assertFalse(locked.isEnabled())
            self.assertIn("粉丝团", locked.toolTip())
            self.assertTrue(self.composer.emote_button.screen().availableGeometry().contains(popup.geometry()))
            popup.tabs.setCurrentIndex(0)
            settle(lambda: any(b.text() == "[doge]" for b in popup.findChildren(QToolButton)))
            next(b for b in popup.findChildren(QToolButton) if b.text() == "[doge]").click()
            self.assertEqual(self.composer.edit.text(), "[doge]")
        popup.close()
        popup.set_packages([])
        self.assertIn("暂无", popup.status.text())
        popup.set_error("网络不可用")
        self.assertIn("网络不可用", popup.status.text())
        self.assertFalse(popup.retry_button.isHidden())

    def test_catalog_timeout_shows_retry_without_claiming_a_send(self):
        import requests
        with patch.object(bili, "get_emoticons", side_effect=requests.Timeout()):
            self.composer.open_emoticons()
            settle(lambda: "超时" in self.composer.popup.status.text())
        self.assertNotIn("发送", self.composer.popup.status.text())
        self.assertFalse(self.composer.popup.retry_button.isHidden())

    def test_first_catalog_survives_lazy_device_cookie_initialization(self):
        bili.set_login_cookies("test-session", "test-csrf", "")
        packs = [{"pkg_type": 3, "pkg_name": "小表情", "emoticons": [{"emoji": "[好]", "perm": 1}]}]
        def load(*args, **kwargs):
            bili.set_login_cookies("test-session", "test-csrf", "new-device")
            return packs
        with patch.object(bili, "get_emoticons", side_effect=load):
            self.composer.open_emoticons()
            settle(lambda: any(b.text() == "[好]" for b in self.composer.popup.findChildren(QToolButton)))
        self.assertTrue(self.composer.popup.retry_button.isEnabled())

    def test_account_change_discards_permissions_and_releases_pending_catalog(self):
        entered, release = threading.Event(), threading.Event()
        def load(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [{"pkg_type": 2, "emoticons": [{"emoji": "旧账号表情", "perm": 1,
                                                       "emoticon_unique": "room_101_99"}]}]
        with patch.object(bili, "get_emoticons", side_effect=load):
            self.composer.open_emoticons()
            settle(entered.is_set)
            bili.set_login_cookies("other-session", "other-csrf")
            self.composer.sync_credentials()
            self.assertFalse(self.composer.popup.isVisible())
            release.set()
            from ddm.danmaku_send import _active_requests
            settle(lambda: not _active_requests)
        with patch.object(bili, "get_emoticons", return_value=[]):
            self.composer.open_emoticons()
            settle(lambda: "暂无" in self.composer.popup.status.text())
        self.assertFalse(any(b.text() == "旧账号表情" for b in self.composer.popup.findChildren(QToolButton)))

    def test_manual_refresh_replaces_cached_catalog_after_error_and_empty_result(self):
        with patch.object(bili, "get_emoticons", side_effect=[ValueError("临时失败"), [], [
                {"pkg_type": 3, "emoticons": [{"emoji": "[刷新]", "perm": 1}]}]]) as get:
            self.composer.open_emoticons()
            settle(lambda: "临时失败" in self.composer.popup.status.text())
            self.composer.popup.retry_button.click()
            settle(lambda: "暂无" in self.composer.popup.status.text())
            self.composer.popup.retry_button.click()
            settle(lambda: any(b.text() == "[刷新]" for b in self.composer.popup.findChildren(QToolButton)))
        self.assertEqual(get.call_count, 3)

    def test_timeout_retains_draft_and_reports_uncertain_result_without_retry(self):
        import requests
        self.composer.edit.setText("不要重复")
        with patch.object(bili, "send_danmaku", side_effect=requests.Timeout()) as send:
            self.composer.send_text()
            settle(lambda: not self.composer.busy)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.composer.edit.text(), "不要重复")
        self.assertIn("未确认", self.composer.feedback.text())

    def test_closing_tile_during_request_does_not_destroy_running_thread(self):
        from ddm.danmaku_send import DanmakuComposer, _active_requests
        entered, release = threading.Event(), threading.Event()
        composer = DanmakuComposer()
        composer.set_room("101")
        composer.edit.setText("关闭前发送")
        def send(*a, **kw):
            entered.set()
            release.wait(2)
            return {"code": 0}
        with patch.object(bili, "send_danmaku", side_effect=send):
            composer.send_text()
            settle(entered.is_set)
            composer.deleteLater()
            APP.sendPostedEvents(None, QEvent.DeferredDelete)
            self.assertTrue(_active_requests)
            release.set()
            settle(lambda: not _active_requests)

    def test_app_saves_device_cookie_without_receiver_and_invalidates_logout_catalog(self):
        from contextlib import ExitStack
        from ddm.app import MainWindow
        from ddm import config
        with ExitStack() as stack:
            for name in ("start_tile", "refresh_status", "refresh_stats", "refresh_account"):
                stack.enter_context(patch.object(MainWindow, name))
            save = stack.enter_context(patch.object(config, "save"))
            window = MainWindow([], [{"room_id": "101", "uname": "测试"}], layout_id="1x1", state={
                "sessdata": "test-session", "bili_jct": "test-csrf", "plugins_enabled": []})
            try:
                composer = window.wall.tiles[0].composer
                def load(*a, **kw):
                    bili.set_login_cookies("test-session", "test-csrf", "initialized-device")
                    return []
                with patch.object(bili, "get_emoticons", side_effect=load):
                    composer.open_emoticons()
                    settle(lambda: composer.popup.retry_button.isEnabled())
                self.assertFalse(window._danmaku_clients)
                self.assertTrue(window._save_timer.isActive())
                window._save_timer.timeout.emit()
                self.assertEqual(save.call_args.args[0]["buvid3"], "initialized-device")
                composer.edit.setText("重新登录后再发")
                window.logout("bilibili")
                self.assertFalse(composer.popup.isVisible())
                self.assertEqual(composer.edit.text(), "重新登录后再发")
                composer.send_text()
                self.assertFalse(composer.busy)
                self.assertIn("登录", composer.feedback.text())
            finally:
                window.close()

    def test_global_emoticon_order_is_loaded_and_saved_in_app_state(self):
        from contextlib import ExitStack
        from ddm.app import MainWindow
        from ddm import config
        from ddm.danmaku_send import emoticon_order
        with ExitStack() as stack:
            for name in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account'):
                stack.enter_context(patch.object(MainWindow, name))
            save = stack.enter_context(patch.object(config, 'save'))
            window = MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'emoticon_order': {'3:emoji': ['b', 'a']}})
            try:
                self.assertEqual(emoticon_order.orders, {'3:emoji': ['b', 'a']})
                emoticon_order.save('3:emoji', [{'emoji': 'a'}, {'emoji': 'b'}])
                self.assertTrue(window._save_timer.isActive())
                window._save_timer.timeout.emit()
                snapshot = save.call_args.args[0]['emoticon_order']
                self.assertEqual(snapshot, {'3:emoji': ['a', 'b']})
                emoticon_order.save('3:emoji', [{'emoji': 'b'}])
                self.assertEqual(snapshot, {'3:emoji': ['a', 'b']}, '保存快照不能被后续拖动改写')
            finally:
                window.close()
                emoticon_order.load({})

    def test_app_close_waits_for_inflight_send_before_destroying_threads(self):
        from contextlib import ExitStack
        from ddm.app import MainWindow
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def send(*a, **kw):
            entered.set()
            release.wait(2)
            bili.set_login_cookies("test-session", "test-csrf", "late-device")
            finished.set()
            return {"code": 0}
        with ExitStack() as stack:
            save = stack.enter_context(patch("ddm.config.save"))
            for name in ("start_all", "refresh_status", "refresh_stats", "refresh_account"):
                stack.enter_context(patch.object(MainWindow, name))
            stack.enter_context(patch.object(bili, "send_danmaku", side_effect=send))
            window = MainWindow([], [{"room_id": "101"}], layout_id="1x1", state={
                "sessdata": "test-session", "bili_jct": "test-csrf", "buvid3": "device-test",
                "plugins_enabled": []})
            timer = None
            try:
                composer = window.wall.tiles[0].composer
                composer.edit.setText("关闭前发送")
                composer.send_text()
                settle(entered.is_set)
                timer = threading.Timer(.15, release.set)
                timer.start()
                window.close()
                self.assertTrue(finished.is_set(), "退出应用必须先等待发送线程结束")
                self.assertEqual(save.call_args.args[0]["buvid3"], "late-device")
            finally:
                release.set()
                if timer:
                    timer.join(2)
                window.close()

    def test_app_close_during_catalog_load_cannot_start_late_image_workers(self):
        from contextlib import ExitStack
        from ddm.app import MainWindow
        from ddm.danmaku_send import _active_requests
        entered, release, image_started = threading.Event(), threading.Event(), threading.Event()
        def load(*a, **kw):
            entered.set()
            release.wait(2)
            return [{"pkg_type": 3, "emoticons": [{"emoji": "[好]", "perm": 1,
                "url": "https://example.com/offline.png"}]}]
        with ExitStack() as stack:
            for name in ("start_all", "refresh_status", "refresh_stats", "refresh_account"):
                stack.enter_context(patch.object(MainWindow, name))
            stack.enter_context(patch.object(bili, "get_emoticons", side_effect=load))
            stack.enter_context(patch.object(images, "load_pixmap", side_effect=lambda *a: image_started.set()))
            window = MainWindow([], [{"room_id": "101"}], layout_id="1x1", state={
                "sessdata": "test-session", "bili_jct": "test-csrf", "plugins_enabled": []})
            timer = None
            try:
                window.wall.tiles[0].composer.open_emoticons()
                settle(entered.is_set)
                timer = threading.Timer(.05, release.set)
                timer.start()
                window.close()
                APP.processEvents()
                settle(lambda: not _active_requests)
                self.assertFalse(image_started.is_set(), "关窗后的表情回调不能启动图片线程")
            finally:
                release.set()
                if timer:
                    timer.join(2)
                window.close()

    def test_platform_switch_keeps_the_same_video_space(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站"})
        tile.resize(500, 350)
        tile.show()
        APP.processEvents()
        initial = tile.video.height()
        try:
            tile.set_room({"room_id": "douyu:1", "uname": "斗鱼"})
            APP.processEvents()
            self.assertEqual(tile.video.height(), initial)
            tile.set_room({"room_id": "202", "uname": "B站2"})
            APP.processEvents()
            self.assertEqual(tile.video.height(), initial)
        finally:
            tile.close()

    def test_fullscreen_idle_hides_composer_without_resizing_video(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站"})
        tile.setProperty("fullscreen", True)
        tile.resize(500, 350)
        tile.show()
        APP.processEvents()
        initial = tile.video.geometry()
        try:
            tile.set_fullscreen_controls_hidden(True)
            settle(lambda: not tile.composer.isVisible())
            self.assertFalse(tile.composer.isVisible())
            self.assertEqual(tile.video.geometry(), initial)
            tile.set_fullscreen_controls_hidden(False)
            APP.processEvents()
            self.assertTrue(tile.composer.isVisible())
            self.assertEqual(tile.video.geometry(), initial)
        finally:
            tile.close()

    def test_fullscreen_keeps_composer_when_bar_auto_hide_is_disabled(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101"})
        tile.setProperty("fullscreen", True)
        tile.resize(900, 500)
        tile.show()
        APP.processEvents()
        try:
            initial = tile.video.geometry()
            tile.set_fullscreen_controls_hidden(True, hide_bar=False)
            APP.processEvents()
            self.assertTrue(tile.bottom.isVisible())
            self.assertTrue(tile.composer.isVisible())
            self.assertEqual(tile.video.geometry(), initial)
        finally:
            tile.close()

    def test_fullscreen_keeps_input_visible_while_editing(self):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QWidget
        from ddm.fullscreen_cursor import FullscreenCursor
        from ddm.widgets import Tile
        window = QWidget()
        window.settings = {}
        tile = Tile({"room_id": "101", "uname": "B站"}, window)
        window._fullscreen_tile = tile
        window.isActiveWindow = lambda: True
        window.resize(900, 350)
        tile.resize(900, 350)
        window.show()
        tile.show()
        tile.composer.edit.setFocus()
        APP.processEvents()
        cursor = FullscreenCursor(window)
        cursor.IDLE_SECONDS = 0
        point = tile.video.mapToGlobal(tile.video.rect().center())
        try:
            with patch.object(QCursor, "pos", return_value=point):
                cursor.update_cursor()
                cursor.update_cursor()
            self.assertFalse(cursor.hidden, "键入期间鼠标停在视频上也不能藏起输入框")
        finally:
            cursor.stop()
            window.close()



if __name__ == "__main__":
    unittest.main()
