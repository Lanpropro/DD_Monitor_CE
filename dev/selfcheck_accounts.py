"""离线回归：统一账号入口、多平台优先级、UID/图标及退出隔离。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, Qt, Signal  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QPushButton  # noqa: E402
from ddm import app as app_module, bili, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.platform_login import PlatformFollowDialog  # noqa: E402
from dev.selfcheck_platform_follows import wait_for  # noqa: E402


class AvatarStub(QObject):
    loaded = Signal(str, QPixmap)
    finished = Signal()

    def __init__(self, _faces, parent=None):
        super().__init__(parent)

    def start(self):
        pass

    def isRunning(self):
        return False


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    account = {"uid": "7890123", "uname": "斗鱼测试账号", "face": ""}
    provider = SimpleNamespace(kind="douyu", label="斗鱼", follow_login_url="about:blank",
        follow_cookie_domain="douyu.com", account_login_url="about:blank#standalone-login",
        account_info=lambda _s, _c: account,
        follow_rooms=Mock(return_value=[]))
    with patch.object(app_module.QTimer, "singleShot"):
        window = MainWindow([], [], state={"plugins_enabled": []})
    window.plugins.platforms["douyu"] = provider
    window.show()
    app.processEvents()
    try:
        with patch.object(window, "open_login") as login, \
                patch.object(window, "open_import_follows") as imports:
            row = window.sidebar.account_row
            QTest.mouseClick(row, Qt.LeftButton, pos=QPoint(12, 12))
            login.assert_called_once_with()
            imports.assert_not_called()
        with patch.object(window, "_open_account_dialog") as login:
            window.open_login()
            login.assert_called_once_with({"斗鱼": provider}, platform_kind="bilibili")
        with patch.object(window, "_follow_loader", Mock(isRunning=Mock(return_value=True)), create=True), \
                patch.object(window, "_open_account_dialog") as login:
            window.open_login()
            login.assert_not_called()
        with patch.object(window, "_open_account_dialog") as login:
            window.open_login("bilibili")
            login.assert_called_once_with({"斗鱼": provider}, platform_kind="bilibili")

        # 登录只查询身份，不分页读取关注；真实浏览器使用空白页。
        dialog = PlatformFollowDialog(provider, window, login_only=True)
        dialog.show()
        assert dialog.read_button.text() == "确认登录"
        assert dialog._login_url == provider.account_login_url and dialog.width() <= 720
        assert dialog.height() <= 540
        assert dialog.browser.zoomFactor() == .8
        dialog._read()
        wait_for(app, lambda: dialog._worker is None)
        assert dialog.result() == QDialog.DialogCode.Accepted and dialog.account == account
        provider.follow_rooms.assert_not_called()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        # 导入关注和退出账号也使用独立登录页，不回到完整关注网站。
        dialog = PlatformFollowDialog(provider, window)
        assert dialog._login_url == provider.account_login_url
        with patch.object(dialog.account_store, "clear"), patch.object(dialog.browser, "load") as load:
            dialog._forget()
            assert load.call_args.args[0].toString() == provider.account_login_url
        dialog.reject()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        # www 与 passport 的 Cookie 分别按原域恢复，不使用登录页域覆盖。
        from PySide6.QtWebEngineCore import QWebEngineCookieStore
        raw = ["www-test=value; domain=www.douyu.com; path=/; secure; HttpOnly",
               "passport-test=value; domain=passport.douyu.com; path=/; secure; HttpOnly"]
        with patch.dict(os.environ, {"DDM_NO_SAVE": "0"}), \
                patch("ddm.account_store.AccountStore.load", return_value=raw), \
                patch.object(QWebEngineCookieStore, "setCookie") as set_cookie:
            dialog = PlatformFollowDialog(provider, window, login_only=True)
            assert [call.args[1].host() for call in set_cookie.call_args_list] == [
                "www.douyu.com", "passport.douyu.com"]
        dialog.reject()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        with patch.object(provider, "account_info", side_effect=RuntimeError("登录已过期")):
            dialog = PlatformFollowDialog(provider, window, login_only=True)
            dialog.show()
            dialog._read()
            wait_for(app, lambda: dialog._worker is None)
            assert dialog.isVisible() and not dialog.account and "已过期" in dialog.status.text()
            dialog.reject()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        # 宿主接收统一窗口结果；登录模式不导入关注。
        with patch("ddm.account_dialog.AccountPlatformDialog") as login, \
                patch.object(window, "_import_selected_follows") as imports:
            login.return_value.exec.return_value = QDialog.DialogCode.Accepted
            login.return_value.rooms = []
            window._open_account_dialog({"斗鱼": provider}, platform_kind="douyu")
            imports.assert_not_called()
        window._accounts["douyu"] = dict(account)
        window._render_account()
        row = window.sidebar.account_row
        assert row.platform == "douyu" and row.uid == account["uid"]
        assert row.platform_badge.isVisible() and not row.platform_badge.pixmap().isNull()
        assert "ID: " + account["uid"] in row.account_id._full_text
        texts = [a.text() for a in window.sidebar.account_menu().actions() if a.text()]
        assert "退出登录" in texts and "登录其他平台…" in texts
        assert window._login_choices() == ["B站"]
        with patch.object(window, "open_login") as login:
            menu = window.sidebar.account_menu()
            action = next(a for a in menu.actions() if a.text() == "登录其他平台…")
            with patch.object(window.sidebar, "account_menu", return_value=menu), \
                    patch.object(menu, "exec", return_value=action):
                window.sidebar._open_account_menu()
            login.assert_called_once_with()

        # 两个平台头像交错返回，不能把斗鱼头像覆盖到 B 站。
        with patch.object(app_module, "AvatarLoader", AvatarStub):
            window._accounts["douyu"] = dict(account, face="mock-douyu")
            douyu_account = window._accounts["douyu"]
            window._render_account()
            douyu_avatar = window._account_avatar_loader
            bili.set_sessdata("test-session")
            window._on_account_loaded({"uid": 123456, "uname": "B站测试账号", "face": "mock-bili"})
            bili_avatar = window._account_avatar_loader
            assert row.platform == "bilibili" and row.uid == "123456"
            assert window._login_choices() == []
            menu = window.sidebar.account_menu()
            rows = [a.defaultWidget() for a in menu.actions() if hasattr(a, "defaultWidget")
                    and a.defaultWidget().findChild(QPushButton) is not None]
            assert len(rows) == 1
            from ddm.widgets import AccountRow
            assert [item.findChild(AccountRow).uid for item in rows] == ["7890123"]
            assert menu.testAttribute(Qt.WA_TranslucentBackground)
            assert menu.windowFlags() & Qt.NoDropShadowWindowHint
            assert rows[0].width() == row.width()
            assert rows[0].findChild(QPushButton).parentWidget() is rows[0].findChild(AccountRow)
            assert menu.actions()[-1].defaultWidget() is rows[0]
            assert [a.text() for a in menu.actions() if a.text()] == ["退出登录", "登录其他平台…"]
            menu.show()
            app.processEvents()
            logout_button = rows[0].findChild(QPushButton)
            account_row = rows[0].findChild(AccountRow)
            assert abs(logout_button.geometry().center().y() - account_row.rect().center().y()) <= 1
            assert "text-align: center" in logout_button.styleSheet()
            menu.close()
            with patch("ddm.platform_login.clear_platform_login") as clear:
                rows[0].findChild(QPushButton).click()
                clear.assert_called_once_with("douyu")
            assert bili.SESSION_DATA and "douyu" not in window._accounts
            # 恢复测试身份，让之前的头像线程回调仍引用同一账号。
            window._accounts["douyu"] = douyu_account
            blue, red = QPixmap(26, 26), QPixmap(26, 26)
            blue.fill(Qt.blue)
            red.fill(Qt.red)
            douyu_avatar.loaded.emit("account", red)
            assert row.platform == "bilibili" and row.avatar._source is None
            bili_avatar.loaded.emit("account", blue)
            assert row.avatar._source.toImage().pixelColor(13, 13).blue() == 255
            window.logout()
            assert row.platform == "douyu" and row.uid == account["uid"]
            assert row.avatar._source.toImage().pixelColor(13, 13).red() == 255
            bili_avatar.loaded.emit("account", blue)
            assert row.platform == "douyu"

        for side in ("left", "top"):
            window.sidebar.set_side(side)
            for collapsed in (False, True):
                window.sidebar.set_collapsed(collapsed, animate=False)
                app.processEvents()
                assert row.platform_badge.isVisible() == (not collapsed)
                if not collapsed:
                    assert row.platform_badge.x() > row.account_text.x()
                assert row.account_id.isVisible() == (not collapsed)
                if not collapsed:
                    assert "7890123" in row.account_id._full_text
                    assert row.name.height() + row.account_id.height() <= row.height() - 8
        with patch("ddm.platform_login.clear_platform_login") as clear:
            window.logout()
            clear.assert_called_once_with("douyu")
        assert not row.platform and not row.uname and row.avatar._source is None
        assert row.platform_badge.isHidden() and row.account_id.isHidden()
        assert window._login_choices() == ["B站", "斗鱼"]
        # 重启只恢复加密文件中的身份缓存，禁用插件不展示其账号。
        with patch.dict(os.environ, {"DDM_NO_SAVE": "0"}), \
                patch("ddm.account_store.AccountStore.load_account", return_value=account):
            window._restore_platform_accounts()
        assert row.platform == "douyu" and row.uid == account["uid"]
        window.plugins.platforms.pop("douyu")
        window._render_account()
        assert not row.uname
    finally:
        window.close()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        bili.set_sessdata("")
    print("PASS: unified login/menu, identity-only login, Bilibili priority, UID/logo, portrait/compact, logout and restore")


if __name__ == "__main__":
    main()
