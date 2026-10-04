"""离线回归：虎牙、抖音和 Twitch 身份确认、独立登录入口和账号退出。"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
import requests  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtNetwork import QNetworkCookie  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from ddm import app as app_module, bili, theme  # noqa: E402
from ddm.account_dialog import AccountPlatformDialog  # noqa: E402
from ddm.account_store import AccountStore  # noqa: E402
from ddm.platform_login import PlatformFollowDialog  # noqa: E402
from plugins_user.domestic_live.plugin import HuyaPlatform, DouyinPlatform, DouyuPlatform  # noqa: E402
from plugins_user.global_live.plugin import TwitchPlatform, YouTubePlatform  # noqa: E402
from dev.selfcheck_account_dialog import dispose  # noqa: E402
from dev.selfcheck_platform_follows import wait_for  # noqa: E402


def response(payload=None, *, text="", status=200):
    result = MagicMock(status_code=status, text=text)
    result.json.return_value = payload
    result.__enter__.return_value = result
    return result


def rejected(provider, replies, *, cookie_domain=".twitch.tv"):
    with requests.Session() as session:
        session.cookies.set("auth-token", "fixture-token", domain=cookie_domain)
        session.get = Mock(side_effect=replies)
        try:
            provider.account_info(session, lambda: False)
        except (RuntimeError, ValueError):
            return
        raise AssertionError("Invalid login accepted")


def check_endpoints():
    huya, douyin, twitch = HuyaPlatform(), DouyinPlatform(), TwitchPlatform()
    with requests.Session() as session:
        data = {"isLogined": True, "uid": 123, "userNick": "huya-test",
                "userLogo": "//huyaimg.msstatic.com/avatar.png"}
        session.get = Mock(return_value=response(text="ddmAccount(" + json.dumps(data) + ")"))
        assert huya.account_info(session, lambda: False) == {
            "uid": "123", "uname": "huya-test", "face": "https://huyaimg.msstatic.com/avatar.png"}
        assert session.get.call_args.kwargs["params"]["do"] == "checkLogin"
        assert session.get.call_args.kwargs["timeout"] == (4, 8)
        data["userLogo"] = "https://msstatic.com.evil.invalid/avatar.png"
        session.get.return_value = response(text="ddmAccount(" + json.dumps(data) + ")")
        assert huya.account_info(session, lambda: False)["face"] == ""
        session.get = Mock(return_value=response({"status_code": 0, "data": {
            "id_str": "9007199254740999", "nickname": "douyin-test", "avatar_thumb": {
                "url_list": ["https://evil.invalid/a.png", "https://p3.douyinpic.com/a.png"]}}}))
        assert douyin.account_info(session, lambda: False) == {
            "uid": "9007199254740999", "uname": "douyin-test", "face": "https://p3.douyinpic.com/a.png"}
        assert session.get.call_args.args[0] == "https://live.douyin.com/webcast/user/me/"
        session.cookies.set("auth-token", "fixture-token", domain=".twitch.tv")
        identity = {"user_id": "456", "client_id": "fixture-client", "login": "twitch-test"}
        user = {"id": "456", "display_name": "Twitch Test",
                "profile_image_url": "https://static-cdn.jtvnw.net/a.png"}
        session.get = Mock(side_effect=[response(identity), response({"data": [user]})])
        assert twitch.account_info(session, lambda: False) == {
            "uid": "456", "uname": "Twitch Test", "face": user["profile_image_url"]}
        assert session.get.call_args_list[0].args[0] == "https://id.twitch.tv/oauth2/validate"
        assert session.get.call_args.kwargs["headers"]["Client-ID"] == "fixture-client"
        session.get = Mock(side_effect=AssertionError("Cancelled request"))
        for provider in (huya, douyin, twitch):
            assert provider.account_info(session, lambda: True) == {}
    rejected(huya, [response(text='ddmAccount({"isLogined":false,"uid":123})')])
    rejected(huya, [response(text='evilCallback({"isLogined":true,"uid":123})')])
    rejected(douyin, [response({"status_code": 20003, "data": {"id_str": "123"}})])
    rejected(douyin, [response({"status_code": 0, "data": {"id_str": "0"}})])
    rejected(twitch, [], cookie_domain="twitch.tv.evil.invalid")
    rejected(twitch, [response(status=401)])
    rejected(twitch, [response({"client_id": "app", "user_id": None})])
    rejected(twitch, [response(identity), response({"data": [{"id": "other-user"}]})])
    with requests.Session() as session:
        session.cookies.set("auth-token", "fixture-token", domain=".twitch.tv")
        session.get = Mock(return_value=response(identity))
        assert twitch.account_info(session, Mock(side_effect=[False, True])) == {}
        session.get.assert_called_once()


def check_dialogs():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    providers = [HuyaPlatform(), DouyinPlatform(), TwitchPlatform()]
    with patch.object(app_module.QTimer, "singleShot"):
        owner = app_module.MainWindow([], [], state={"plugins_enabled": []})
    for provider in [*providers, DouyuPlatform(), YouTubePlatform()]:
        owner.plugins.platforms[provider.kind] = provider
    try:
        assert set(owner._account_platforms()) == {"虎牙", "抖音", "Twitch", "斗鱼"}
        assert set(owner._follow_platforms()) == {"斗鱼"}
        with patch.object(owner, "_open_account_dialog") as opened:
            owner.open_login("twitch")
            assert set(opened.call_args.args[0]) == {"虎牙", "抖音", "Twitch", "斗鱼", "YouTube"}
        bili.set_sessdata("fixture-bili")
        pending_providers = {**owner._account_platforms(), "YouTube": owner.plugins.platforms["youtube"]}
        with patch.object(QWebEngineView, "load", side_effect=AssertionError("Pending platform loaded browser")):
            dialog = AccountPlatformDialog(owner, pending_providers, platform_kind="youtube")
            assert "待接入" in dialog.platform_buttons["youtube"].text()
            assert any("需要 Google 桌面 OAuth" in label.text() for label in dialog.page.findChildren(QLabel))
            assert "youtube" not in owner._accounts
            dispose(app, dialog)
        for provider in providers:
            account = {"uid": "123", "uname": provider.kind + "-test", "face": ""}
            with patch.object(provider, "account_info", return_value=account), \
                    patch.object(provider, "follow_rooms", side_effect=AssertionError("Login imported follows")), \
                    patch.object(QWebEngineView, "load"):
                dialog = AccountPlatformDialog(owner, owner._account_platforms(), platform_kind=provider.kind)
                dialog.show()
                page = dialog.page
                assert isinstance(page, PlatformFollowDialog) and page.login_only
                cookie = QNetworkCookie(b"fixture", b"fixture-value")
                cookie.setDomain("." + provider.account_cookie_domain)
                cookie.setPath("/")
                page._on_cookie(cookie)
                foreign = QNetworkCookie(b"foreign", b"foreign-value")
                foreign.setDomain("." + provider.account_cookie_domain + ".evil.invalid")
                assert not page._valid_cookie(foreign)
                page.remember.setChecked(False)
                page._read()
                wait_for(app, lambda: page._worker is None)
                assert owner._accounts[provider.kind]["uid"] == "123"
                assert not owner._platform_login_sessions[provider.kind]["remember"]
                dispose(app, dialog)
                # 重新打开已登录平台只显示身份页，不能导航登录网页。
                dialog = AccountPlatformDialog(owner, owner._account_platforms(), platform_kind=provider.kind)
                assert not isinstance(dialog.page, PlatformFollowDialog)
                dispose(app, dialog)
            with patch("ddm.platform_login.clear_platform_login") as clear:
                owner.logout(provider.kind)
                clear.assert_called_once_with(provider.kind)
            assert bili.SESSION_DATA and provider.kind not in owner._accounts
            assert provider.kind not in owner._platform_login_sessions
        with patch.dict(os.environ, {"DDM_NO_SAVE": "0"}), \
                patch.object(AccountStore, "load_account", return_value={"uid": "123", "uname": "cached"}):
            owner._restore_platform_accounts()
        assert {p.kind for p in providers}.issubset(owner._accounts)
    finally:
        bili.set_sessdata("")
        owner.close()
        app.processEvents()


if __name__ == "__main__":
    check_endpoints()
    check_dialogs()
    print("PASS: Huya/Douyin/Twitch verified identity, invalid/expired login, cancel, cookie isolation, restore and independent logout")
