"""离线回归：重新打开导入窗口自动读取已登录平台，失效回退与取消。"""
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QByteArray, Qt  # noqa: E402
from PySide6.QtNetwork import QNetworkCookie  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from ddm import app as app_module, bili, theme  # noqa: E402
from ddm.account_dialog import AccountPlatformDialog  # noqa: E402
from ddm.account_store import AccountStore  # noqa: E402
from ddm.platform_login import PlatformFollowDialog  # noqa: E402
from dev.selfcheck_account_dialog import dispose, follows_ready  # noqa: E402
from dev.selfcheck_platform_follows import ROOMS, wait_for  # noqa: E402


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    account = {"uid": "123", "uname": "test", "face": ""}
    raw = "auth-test=fake-session; domain=.douyu.com; path=/; secure; HttpOnly"

    def account_info(session, _cancelled):
        if session.cookies.get("auth-test", domain=".douyu.com", path="/") != "fake-session":
            raise RuntimeError("Fixture cookie missing")
        return account

    provider = SimpleNamespace(kind="douyu", label="斗鱼", follow_cookie_domain="douyu.com",
        account_login_url="about:blank#login", follow_login_url="about:blank",
        account_info=Mock(side_effect=account_info), follow_rooms=Mock(return_value=ROOMS))
    with patch.object(app_module.QTimer, "singleShot"):
        owner = app_module.MainWindow([], [], state={"plugins_enabled": []})
    owner.plugins.platforms["douyu"] = provider
    try:
        # 不记住登录时，同一次软件运行内也能复用已经授权的 Cookie。
        dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, platform_kind="douyu")
        dialog.show()
        dialog.page.remember.setChecked(False)
        dialog.page._on_cookie(QNetworkCookie.parseCookies(QByteArray(raw.encode()))[0])
        dialog.page._read()
        wait_for(app, lambda: not dialog.isVisible())
        assert dialog.result() == QDialog.Accepted and owner._accounts["douyu"]["uid"] == "123"
        assert owner._platform_login_sessions["douyu"]["cookies"]
        provider.follow_rooms.assert_not_called()
        dispose(app, dialog)

        bili.set_sessdata("test-session")
        with patch.object(bili, "follow_rooms", return_value=[dict(ROOMS[0], room_id="123")]), \
                patch.dict(os.environ, {"DDM_NO_SAVE": "0"}), \
                patch.object(AccountStore, "load") as load_cookies, \
                patch.object(AccountStore, "save") as save_cookies, \
                patch.object(AccountStore, "clear") as clear_cookies, \
                patch.object(QWebEngineView, "load") as browser_load:
            for rooms in (ROOMS, []):
                provider.follow_rooms.return_value = rooms
                count = provider.follow_rooms.call_count
                # 每次重新创建真实导入窗口，然后从 B 站切到斗鱼；不手动点击读取。
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                wait_for(app, lambda: follows_ready(dialog))
                bili_page = dialog.page
                dialog.select_platform("douyu")
                assert not dialog._platform_pages["douyu"].remember.isChecked()
                assert dialog.page.property("loading") and not dialog.page.import_button.isEnabled()
                assert all(not b.isEnabled() for b in dialog.platform_buttons.values())
                wait_for(app, lambda: follows_ready(dialog))
                page = dialog.page
                assert page.rooms == rooms and provider.follow_rooms.call_count == count + 1
                page._check_all(True)
                dialog.select_platform("bilibili")
                assert dialog.page is bili_page
                dialog.select_platform("douyu")
                assert dialog.page is page and page.selected() == rooms
                assert provider.follow_rooms.call_count == count + 1
                dispose(app, dialog)
            browser_load.assert_not_called()
            load_cookies.assert_not_called()
            save_cookies.assert_not_called()
            assert clear_cookies.call_count == 2

        # 模拟重启后从加密存储恢复的登录，读取失败才显示登录页，可手动重试成功。
        owner._platform_login_sessions.clear()
        with patch.dict(os.environ, {"DDM_NO_SAVE": "0"}), \
                patch.object(AccountStore, "load", return_value=[raw]) as load_cookies, \
                patch.object(AccountStore, "save") as save_cookies, \
                patch.object(QWebEngineView, "load") as browser_load, \
                patch.object(provider, "follow_rooms", side_effect=[RuntimeError("登录已过期"), ROOMS]):
            dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True,
                                           platform_kind="douyu")
            dialog.show()
            assert dialog.page.property("loading")
            wait_for(app, lambda: isinstance(dialog.page, PlatformFollowDialog)
                     and dialog.page._worker is None)
            assert "已过期" in dialog.page.status.text() and not dialog._follow_pages
            assert dialog.page.read_button.isEnabled()
            load_cookies.assert_called_once()
            browser_load.assert_called_once()
            assert browser_load.call_args.args[0].toString() == provider.account_login_url
            # 模拟用户在回退的官方登录页完成重新登录。
            dialog.page._on_cookie(QNetworkCookie.parseCookies(QByteArray(raw.encode()))[0])
            dialog.page._read()
            wait_for(app, lambda: owner._follow_loader is None)
            assert follows_ready(dialog), dialog.page.status.text()
            assert dialog.page.rooms == ROOMS
            save_cookies.assert_called_once()
            dispose(app, dialog)

        # 取消自动读取时等待后台请求退出，不显示迟到结果。
        entered, release = threading.Event(), threading.Event()

        def blocked(_session, _cancelled):
            entered.set()
            assert release.wait(5)
            return ROOMS

        with patch.object(provider, "follow_rooms", side_effect=blocked):
            dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True,
                                           platform_kind="douyu")
            dialog.show()
            try:
                assert entered.wait(2)
                worker = owner._follow_loader
                dialog.reject()
                assert dialog.isVisible() and worker._cancelled.is_set()
            finally:
                release.set()
            wait_for(app, lambda: not dialog.isVisible())
            assert dialog.result() == QDialog.Rejected and not dialog.rooms and not dialog._follow_pages
            assert owner._follow_loader is None
            dispose(app, dialog)

        # 退出账号后不再自动读取，也不会复用内存 Cookie；登录入口仍需要确认。
        owner._clear_platform_account("douyu")
        assert "douyu" not in owner._platform_login_sessions
        with patch.object(provider, "follow_rooms") as follows:
            for imports in (True, False):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=imports,
                                               platform_kind="douyu")
                dialog.show()
                app.processEvents()
                assert isinstance(dialog.page, PlatformFollowDialog) and dialog.page._worker is None
                dispose(app, dialog)
            follows.assert_not_called()
    finally:
        bili.set_sessdata("")
        owner.close()
        app.processEvents()
    print("PASS: reopen automatically reads fresh/empty lists, no login navigation, memory/saved cookies, expiry retry, cancel and logout")


if __name__ == "__main__":
    main()
