"""真实 Qt 控件回归：逐房间草稿、表情分流、异步失败和过期请求隔离。"""
import importlib.util
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QKeyEvent, QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QToolButton
from ddm import bili, images, theme

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
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("ddm.danmaku_send"), "缺少独立的弹幕输入控件")
        from ddm.danmaku_send import DanmakuComposer
        self.saved = (bili.SESSION_DATA, bili.BILI_JCT)
        bili.set_sessdata("test-session")
        bili.set_bili_jct("test-csrf")
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
        bili.set_sessdata(self.saved[0])
        bili.set_bili_jct(self.saved[1])
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
                bili.set_sessdata("test-session")
                bili.set_bili_jct("test-csrf")
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
                widths = {}
                for width, height in ((900, 520), (480, 300), (360, 230)):
                    tile.resize(width, height)
                    APP.processEvents()
                    # 信息条上的既有元素任何宽度都要在；输入框只会自适应收缩，
                    # 放不下时整块收起，绝不去挤掉状态文字和音量滑条。
                    self.assertTrue(tile.status_label.isVisible(), "信息条状态不能被输入区挤没")
                    self.assertTrue(tile.danmaku_settings_button.isVisible())
                    self.assertTrue(tile.volume_button.isVisible())
                    self.assertLess(tile.video.geometry().bottom(), tile.bottom.y())
                    self.assertTrue(tile.bottom.rect().contains(tile.composer.geometry()))
                    self.assertLessEqual(tile.bottom.geometry().bottom(), tile.height())
                    if not tile.composer.isVisible():
                        # 收起时输入框不该还拿着焦点
                        self.assertFalse(tile.composer.edit.hasFocus())
                        continue
                    widths[width] = tile.composer.edit.width()
                    self.assertGreater(tile.composer.edit.width(), 0)
                    self.assertTrue(tile.composer.emote_button.isVisible())
                    composer_height = tile.composer.HEIGHT
                    self.assertEqual(tile.composer.emote_button.size().toTuple(),
                                     (composer_height, composer_height))
                    self.assertEqual(tile.composer.send_button.size().toTuple(), (52, composer_height))
                    # 宽格子里输入区限宽，别把主画面底栏整条铺满。
                    self.assertLessEqual(tile.composer.width(), tile.COMPOSER_MAX_WIDTH)
                    # 没有发送结果时不该有浮动提示；提示只在失败/发送中才出现。
                    self.assertFalse(tile.composer.feedback.isVisible())
                    self.assertEqual(tile.composer.feedback.text(), "")
                self.assertTrue(widths[900] > widths[480] > 40,
                                f"输入框应随格子宽度自适应伸缩：{widths}")
                self.assertIn(900, widths)
                self.assertIn(480, widths)
            tile.set_room({"room_id": "douyu:1", "uname": "斗鱼"})
            APP.processEvents()
            self.assertFalse(tile.composer.isVisible())
            tile.set_room(None)
            APP.processEvents()
            self.assertFalse(tile.composer.isVisible())
        finally:
            theme.apply("dark")
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
            buttons = popup.findChildren(QToolButton)
            locked = next(b for b in buttons if b.text() == "锁定")
            self.assertFalse(locked.isEnabled())
            self.assertIn("粉丝团", locked.toolTip())
            self.assertTrue(self.composer.emote_button.screen().availableGeometry().contains(popup.geometry()))
            next(b for b in buttons if b.text() == "[doge]").click()
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

    def test_web_login_waits_for_both_auth_cookies_in_either_order(self):
        from PySide6.QtNetwork import QNetworkCookie
        from PySide6.QtWidgets import QDialog, QLabel
        from types import SimpleNamespace
        from ddm.web_login import WebLoginWindow
        for names in (("SESSDATA", "bili_jct"), ("bili_jct", "SESSDATA")):
            window = QDialog()
            window.sessdata = window.bili_jct = ""
            window._auth_cookies = {}
            window._closing = False
            window.status = QLabel(window)
            emitted = []
            window.sessionData = SimpleNamespace(emit=emitted.append)
            for i, name in enumerate(names):
                cookie = QNetworkCookie(name.encode(), ("web-session" if name == "SESSDATA" else "web-csrf").encode())
                cookie.setDomain(".bilibili.com")
                WebLoginWindow._on_cookie(window, cookie)
                self.assertEqual(emitted, [] if i == 0 else ["web-session"])
            self.assertEqual((bili.SESSION_DATA, bili.BILI_JCT), ("web-session", "web-csrf"))
            window.close()

    def test_web_login_ignores_other_domains_cookies(self):
        from PySide6.QtNetwork import QNetworkCookie
        from PySide6.QtWidgets import QDialog, QLabel
        from types import SimpleNamespace
        from ddm.web_login import WebLoginWindow
        window = QDialog()
        window.sessdata = window.bili_jct = ""
        window._auth_cookies = {}
        window._closing = False
        window.status = QLabel(window)
        emitted = []
        window.sessionData = SimpleNamespace(emit=emitted.append)
        for name in (b"SESSDATA", b"bili_jct"):
            cookie = QNetworkCookie(name, b"wrong-domain")
            cookie.setDomain("notbilibili.com")
            WebLoginWindow._on_cookie(window, cookie)
        self.assertEqual(emitted, [])
        self.assertEqual(bili.SESSION_DATA, "test-session")
        window.close()

    def test_shrinking_bar_never_leaves_stale_button_positions(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站"})
        tile.resize(1400, 320)
        tile.show()
        APP.processEvents()
        try:
            composer = tile.composer
            for width in (1400, 1100, 900, 700, 520, 480, 1500, 600, 900):
                # 故意不处理事件循环：缩放的同一帧里按钮也不能留在旧位置，
                # 否则会压到旁边的弹幕开关上（用户报的「鼠标移入错位一次」）。
                tile.resize(width, 320)
                self.assertTrue(composer.rect().contains(composer.emote_button.geometry()),
                                f"宽度 {width} 时表情按钮跑出输入区")
                if composer.send_button.isVisible():
                    self.assertTrue(composer.rect().contains(composer.send_button.geometry()),
                                    f"宽度 {width} 时发送按钮跑出输入区")
        finally:
            tile.close()

    def test_large_tile_composer_uses_the_extended_width(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站"})
        tile.resize(1400, 360)
        tile.show()
        APP.processEvents()
        try:
            self.assertTrue(tile.composer.isVisible())
            # 大格子直接给到上限宽度，不再点开/收起，避免收起时重排卡顿
            self.assertEqual(tile.composer.width(), tile.COMPOSER_MAX_WIDTH)
            self.assertIn("Enter", tile.composer.edit.placeholderText())
            center = tile.bottom.width() // 2
            self.assertLessEqual(abs(tile.composer.x() + tile.composer.width() // 2 - center), 2)
            tile.composer.edit.setFocus()
            APP.processEvents()
            self.assertEqual(tile.composer.width(), tile.COMPOSER_MAX_WIDTH)
            tile.composer.edit.clearFocus()
            APP.processEvents()
            self.assertEqual(tile.composer.width(), tile.COMPOSER_MAX_WIDTH)
        finally:
            tile.close()

    def test_status_and_hover_changes_do_not_move_composer(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站", "live": True})
        tile.resize(1000, 320)
        tile.show()
        APP.processEvents()
        try:
            tile.set_status("已连接")
            APP.processEvents()
            before = tile.composer.x()
            for status in ("连接中…", "缓冲中…", "已连接"):
                tile.set_status(status)
                APP.processEvents()
                self.assertEqual(tile.composer.x(), before, "状态刷新不能把输入区挪位")
            for visible in (False, True, False, True):
                tile.set_controls_visible(visible)
                APP.processEvents()
                self.assertEqual(tile.composer.x(), before, "悬停显隐不能把输入区挪位")
        finally:
            tile.close()

    def test_room_switch_keeps_video_geometry_for_inline_composer(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站"})
        tile.resize(500, 350)
        tile.show()
        APP.processEvents()
        initial = (tile.video.geometry(), tile.bottom.geometry())
        try:
            tile.set_room({"room_id": "douyu:1", "uname": "斗鱼"})
            APP.processEvents()
            # 输入区不再单独占高度：换到不支持发送的房间只是把它藏起来，
            # 视频和底栏的几何都不跟着变。
            self.assertFalse(tile.composer.isVisible())
            self.assertEqual((tile.video.geometry(), tile.bottom.geometry()), initial)
            tile.set_room({"room_id": "202", "uname": "B站2"})
            APP.processEvents()
            self.assertTrue(tile.composer.isVisible())
            self.assertEqual((tile.video.geometry(), tile.bottom.geometry()), initial)
        finally:
            tile.close()

    def test_fullscreen_idle_hides_composer_without_resizing_video(self):
        from ddm.widgets import Tile
        tile = Tile({"room_id": "101", "uname": "B站"})
        tile.resize(500, 350)
        tile.show()
        APP.processEvents()
        initial = tile.video.geometry()
        try:
            tile.set_fullscreen_controls_hidden(True)
            APP.processEvents()
            self.assertFalse(tile.composer.isVisible())
            self.assertEqual(tile.video.geometry(), initial)
            tile.set_fullscreen_controls_hidden(False)
            APP.processEvents()
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
        tile = Tile({"room_id": "101", "uname": "B站"}, window)
        window._fullscreen_tile = tile
        window.isActiveWindow = lambda: True
        window.resize(500, 350)
        tile.resize(500, 350)
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

    def test_login_restore_save_and_logout_include_bili_jct(self):
        from ddm import app as app_module
        with patch.object(app_module.QTimer, "singleShot"):
            window = app_module.MainWindow([], [], layout_id="1x1", state={
                "sessdata": "saved-session", "bili_jct": "saved-csrf", "plugins_enabled": []})
        try:
            self.assertEqual((bili.SESSION_DATA, bili.BILI_JCT), ("saved-session", "saved-csrf"))
            self.assertEqual(window.current_state()["bili_jct"], "saved-csrf")
            bili.set_sessdata("new-session")
            bili.set_bili_jct("new-csrf")
            with patch.object(window, "refresh_account"), patch.object(window, "sync_danmaku"):
                window._on_login("new-session")
            self.assertEqual(window.state["bili_jct"], "new-csrf")
            window.logout("bilibili")
            self.assertEqual((bili.SESSION_DATA, bili.BILI_JCT), ("", ""))
            self.assertEqual(window.current_state()["bili_jct"], "")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
