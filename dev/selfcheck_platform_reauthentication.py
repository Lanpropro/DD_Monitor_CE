"""Offline: force-login bypasses account summary and resets only the target platform."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import Qt, QCoreApplication, QEvent, QPoint, QRect
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QPushButton
from ddm import app as host
from ddm.account_dialog import AccountPlatformDialog
from ddm.platform_login import PlatformFollowDialog
from ddm.ui import ActionButton, ToggleSwitch


def check_windows_browser_click(dialog):
    import ctypes
    from ctypes import wintypes

    browser = dialog.page.browser
    browser.setHtml('<input style="width:160px;height:80px" onfocus="document.title=\'focused\'">')
    for _ in range(40):
        if browser.url().scheme() == 'data' and not browser.page().isLoading():
            break
        QTest.qWait(25)
    point = browser.mapTo(dialog, QPoint(36, 36))
    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = wintypes.HWND(int(dialog.winId()))
    rect = wintypes.RECT()
    assert user32.GetWindowRect(hwnd, ctypes.byref(rect))
    scale = dialog.devicePixelRatioF()
    hit = user32.WindowFromPoint(wintypes.POINT(rect.left + round(point.x() * scale),
                                               rect.top + round(point.y() * scale)))
    assert user32.GetAncestor(hit, 2) == hwnd.value, "Windows must hit the login window over the browser"
    QTest.mouseClick(dialog.windowHandle(), Qt.LeftButton, Qt.NoModifier, point)
    for _ in range(20):
        if browser.title() == 'focused':
            break
        QTest.qWait(25)
    assert browser.title() == 'focused', "The inner HTML input must receive focus from the click"


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(host.QTimer, "singleShot"):
        owner = host.MainWindow([], [], state={"plugins_enabled": [],
            "settings": {"auto_update": False, "close_behavior": "exit"}})
    providers = {name: SimpleNamespace(kind=name, label=name, follow_cookie_domain=name+".com",
        follow_login_url="about:blank", account_login_url="about:blank",
        account_info=lambda *_: {"uid":"1"}, follow_rooms=lambda *_: []) for name in ("douyin", "douyu", "huya", "youtube", "twitch", "chzzk")}
    owner._accounts.update({name:{"uid":"1","uname":"fixture"} for name in providers})
    try:
        with patch.object(PlatformFollowDialog, "_forget") as forget:
            normal = AccountPlatformDialog(owner, providers, platform_kind="douyin")
            assert not isinstance(normal.page, PlatformFollowDialog)
            forget.assert_not_called()
            normal.reject(); normal.deleteLater()
            forced = AccountPlatformDialog(owner, providers, platform_kind="douyin", reauthenticate=True)
            assert isinstance(forced.page, PlatformFollowDialog)
            forget.assert_not_called()
            forced.show()
            QTest.qWait(25)
            forget.assert_called_once()
            forced.select_platform("douyu")
            assert not isinstance(forced.page, PlatformFollowDialog)
            forget.assert_called_once()
            forced.reject(); forced.deleteLater()

        owner._accounts.pop("douyin")
        load = QWebEngineView.load
        loads = []
        def observe_load(browser, url):
            page = browser.parentWidget()
            dialog = page.window()
            loads.append((dialog.isVisible(), dialog.pages.currentWidget() is page,
                          dialog.pages.testAttribute(Qt.WA_NativeWindow), url.toString()))
            return load(browser, url)

        work_area = QRect(0, 0, 480, 850)
        with patch.object(QWebEngineView, "load", observe_load), \
                patch.object(owner, "screen", return_value=SimpleNamespace(availableGeometry=lambda: work_area)):
            login = AccountPlatformDialog(owner, providers, platform_kind="douyin")
            try:
                assert not loads, loads
                if app.platformName() == "windows":
                    login.setWindowFlag(Qt.WindowStaysOnTopHint)
                    login.setAttribute(Qt.WA_ShowWithoutActivating)
                login.show()
                QTest.qWait(80)
                assert loads == [(True, True, True, "about:blank")], loads
                assert login.windowFlags() & Qt.FramelessWindowHint
                assert work_area.contains(login.frameGeometry()), login.frameGeometry()
                picker = login.account_bar.platform
                assert picker.buttons["douyin"].isVisible() and picker.more.isVisible()
                assert isinstance(login.page.remember, ToggleSwitch)
                assert isinstance(login.page.read_button, ActionButton)
                assert not any(button.isVisible() and button.text() in ("退出账号", "取消")
                               for button in login.page.findChildren(QPushButton))
                assert login.page.reload_button.text() == "刷新"
                for button in (login.page.remember, login.page.read_button, login.page.reload_button):
                    assert login.rect().contains(button.mapTo(login, button.rect().bottomRight()))
                page = login.page
                with (patch.object(page.account_store, "clear"),
                      patch.object(type(page._profile), "clearHttpCache") as clear_cache):
                    page._forget()
                    clear_cache.assert_called_once()
                    assert len(loads) == 1 and not page.read_button.isEnabled(), loads
                    page.reload_button.click()
                    assert len(loads) == 1, loads
                    page._profile.clearHttpCacheCompleted.emit()
                    assert len(loads) == 2 and page.read_button.isEnabled(), loads
                page.reload_button.click()
                assert len(loads) == 3, loads
                if app.platformName() == "windows":
                    assert not login.testAttribute(Qt.WA_TranslucentBackground)
                    assert not login.mask().isEmpty()
                    check_windows_browser_click(login)
                overflow = next(kind for kind in providers if picker.actions[kind].isVisible())
                picker.actions[overflow].trigger()
                assert login.kind == overflow and picker.buttons[overflow].isVisible()
                login.account_bar.titlebar.close_button.click()
                assert login.isHidden()
            finally:
                login.reject()
                login.deleteLater()
    finally:
        owner.close(); app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: embedded login loads after mounting; force reauthentication resets only the target")


if __name__ == "__main__":
    main()
