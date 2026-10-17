"""Offline regression for Bilibili login cookies, device identity and persistence."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

import requests
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import bili, config, login
from ddm.app import MainWindow


APP = QApplication.instance() or QApplication([])


class CookieTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("SESSION_DATA", "BILI_JCT", "BUVID3"):
            self.stack.enter_context(patch.object(bili, name, "", create=True))

    def test_login_switch_clears_previous_csrf_but_keeps_device(self):
        bili.set_login_cookies("first-session", "first-csrf", "browser")
        bili.set_sessdata("second-session")
        self.assertEqual(bili._cookies(), {"SESSDATA": "second-session", "buvid3": "browser"})
        bili.set_login_cookies("second-session", "second-csrf")
        bili.set_sessdata("second-session")
        self.assertEqual(bili._cookies()["bili_jct"], "second-csrf")
        bili.set_sessdata("")
        self.assertEqual(bili._cookies(), {"buvid3": "browser"})

    def test_browser_id_is_fetched_once_across_rooms(self):
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0, "data": {"b_3": "shared-browser"}}
        with patch.object(bili.requests, "get", return_value=response) as fetch:
            with ThreadPoolExecutor(max_workers=6) as pool:
                values = list(pool.map(lambda _: bili.ensure_buvid3(), range(6)))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(values, ["shared-browser"] * 6)
        self.assertEqual(bili._cookies(), {"buvid3": "shared-browser"})
        with patch.object(bili.requests, "get", side_effect=AssertionError("Unexpected network")):
            self.assertEqual(bili.ensure_buvid3(), "shared-browser")

    def test_invalid_browser_response_does_not_poison_cache(self):
        response = Mock(status_code=200)
        for payload in ({"code": -352}, {"code": 0, "data": {"b_3": ""}},
                        {"code": 0, "data": {"b_3": 123}}, {"code": 0, "data": [123]}):
            response.json.return_value = payload
            with patch.object(bili.requests, "get", return_value=response), self.assertRaises(ValueError):
                bili.ensure_buvid3()
            self.assertEqual(bili.BUVID3, "")

    def window(self, state):
        for method in ("refresh_status", "refresh_stats", "refresh_account", "load_room_avatars"):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.stack.enter_context(patch("ddm.app.QTimer.singleShot"))
        window = MainWindow([], [], layout_id="1x1", state={"plugins_enabled": [], **state})
        self.addCleanup(window.close)
        return window

    def test_disk_restart_preserves_all_three_cookies(self):
        state = {"version": 1, "sessdata": "saved-session", "bili_jct": "saved-csrf", "buvid3": "saved-browser"}
        window = self.window(state)
        self.assertEqual(bili._cookies(), {"SESSDATA": "saved-session", "bili_jct": "saved-csrf", "buvid3": "saved-browser"})
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "CONFIG_PATH", str(Path(directory) / "state.json")), \
                patch.dict(os.environ, {"DDM_NO_SAVE": ""}):
            config.save(window.current_state())
            saved = config.load()
        self.assertEqual({key: saved[key] for key in ("sessdata", "bili_jct", "buvid3")},
                         {key: state[key] for key in ("sessdata", "bili_jct", "buvid3")})
        bili.set_login_cookies("", "", "")
        self.window(saved)
        self.assertEqual(bili._cookies()["bili_jct"], "saved-csrf")

    def test_old_config_remains_usable_and_logout_clears_auth(self):
        window = self.window({"sessdata": "old-session"})
        self.assertEqual(bili._cookies(), {"SESSDATA": "old-session"})
        bili.set_login_cookies("old-session", "new-csrf", "browser")
        with patch.object(config, "save") as save:
            window._on_login("old-session")
            self.assertEqual(save.call_args.args[0]["bili_jct"], "new-csrf")
            window.logout("bilibili")
            saved = save.call_args.args[0]
        self.assertEqual((saved["sessdata"], saved["bili_jct"], saved["buvid3"]), ("", "", "browser"))

    def test_new_browser_identity_schedules_persistence(self):
        window = self.window({"sessdata": "old-session"})
        source = Mock()
        window._danmaku_clients["123"] = source
        bili.set_login_cookies("old-session", "", "discovered-browser")
        with patch.object(config, "save") as save:
            window._on_danmaku_status(source, "已连接")
            self.assertTrue(window._save_timer.isActive())
            window._save_timer.timeout.emit()
            self.assertEqual(save.call_args.args[0]["buvid3"], "discovered-browser")

    def test_qr_login_captures_poll_and_session_cookies(self):
        session = requests.Session()
        session.cookies.set("buvid3", "qr-browser", domain=".bilibili.com")
        generated = Mock(json=lambda: {"data": {"qrcode_key": "fixture", "url": "https://example.invalid/qr"}})
        success = Mock(json=lambda: {"data": {"code": 0}})
        success.cookies = requests.cookies.RequestsCookieJar()
        success.cookies.set("SESSDATA", "qr-session", domain=".bilibili.com")
        success.cookies.set("bili_jct", "qr-csrf", domain=".bilibili.com")
        session.get = Mock(side_effect=[generated, success])
        worker = login.QRLogin()
        with patch.object(login.requests, "Session", return_value=session):
            worker.run()
        self.assertEqual((worker.sessdata, worker.bili_jct, worker.buvid3), ("qr-session", "qr-csrf", "qr-browser"))
        with patch.object(login.LoginWindow, "start_login"):
            dialog = login.LoginWindow()
        try:
            dialog._thread = worker
            dialog._on_success(worker.sessdata)
            self.assertEqual(bili._cookies(), {"SESSDATA": "qr-session", "bili_jct": "qr-csrf", "buvid3": "qr-browser"})
        finally:
            dialog.close()

    def test_qr_cookie_scopes_do_not_conflict_or_accept_foreign_domains(self):
        session = requests.Session()
        session.cookies.set("SESSDATA", "old-session", domain=".bilibili.com")
        session.cookies.set("bili_jct", "root-csrf", domain=".bilibili.com")
        session.cookies.set("bili_jct", "host-csrf", domain="passport.bilibili.com")
        session.cookies.set("buvid3", "browser", domain=".bilibili.com")
        generated = Mock(json=lambda: {"data": {"qrcode_key": "fixture", "url": "https://example.invalid/qr"}})
        success = Mock(json=lambda: {"data": {"code": 0}})
        success.cookies = requests.cookies.RequestsCookieJar()
        success.cookies.set("SESSDATA", "new-session", domain=".bilibili.com")
        success.cookies.set("bili_jct", "foreign-csrf", domain="bilibili.com.evil.invalid")
        success.cookies.set("bili_jct", "new-csrf", domain=".bilibili.com")
        session.get = Mock(side_effect=[generated, success])
        worker = login.QRLogin()
        with patch.object(login.requests, "Session", return_value=session):
            worker.run()
        self.assertEqual((worker.sessdata, worker.bili_jct, worker.buvid3),
                         ("new-session", "new-csrf", "browser"))

    def test_web_cookies_are_domain_checked_and_order_independent(self):
        from ddm.web_login import WebLoginWindow
        # Use the real cookie handlers without opening a browser or persistent profile.
        class Receiver:
            _closing = False
            sessdata = ""
            _cookies = {}
            status = Mock()
            sessionData = Mock()
            accept = Mock()
            _finish_login = WebLoginWindow._finish_login
        receiver = Receiver()
        receiver._login_timer = QTimer()
        receiver._login_timer.setSingleShot(True)
        receiver._login_timer.timeout.connect(receiver._finish_login)
        def cookie(name, value, domain):
            item = QNetworkCookie(name.encode(), value.encode())
            item.setDomain(domain)
            WebLoginWindow._on_cookie(receiver, item)
        try:
            cookie("SESSDATA", "foreign", "bilibili.com.evil.invalid")
            self.assertEqual(receiver._cookies, {})
            cookie("SESSDATA", "web-session", ".bilibili.com")
            QTest.qWait(350)
            receiver.sessionData.emit.assert_not_called()
            cookie("bili_jct", "web-csrf", ".bilibili.com")
            cookie("buvid3", "web-browser", ".bilibili.com")
            QTest.qWait(450)
            self.assertEqual(bili._cookies(), {"SESSDATA": "web-session", "bili_jct": "web-csrf", "buvid3": "web-browser"})
            receiver.sessionData.emit.assert_called_once_with("web-session")
        finally:
            receiver._login_timer.stop()


if __name__ == "__main__":
    unittest.main()
