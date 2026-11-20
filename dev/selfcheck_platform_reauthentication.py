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
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication
from ddm import app as host
from ddm.account_dialog import AccountPlatformDialog
from ddm.platform_login import PlatformFollowDialog


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(host.QTimer, "singleShot"):
        owner = host.MainWindow([], [], state={"plugins_enabled": [],
            "settings": {"auto_update": False, "close_behavior": "exit"}})
    providers = {name: SimpleNamespace(kind=name, label=name, follow_cookie_domain=name+".com",
        follow_login_url="about:blank", account_login_url="about:blank",
        account_info=lambda *_: {"uid":"1"}, follow_rooms=lambda *_: []) for name in ("douyin", "douyu")}
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

        with patch.object(QWebEngineView, "load", observe_load):
            login = AccountPlatformDialog(owner, providers, platform_kind="douyin")
            try:
                assert not loads, loads
                login.show()
                QTest.qWait(80)
                assert loads == [(True, True, True, "about:blank")], loads
            finally:
                login.reject()
                login.deleteLater()
    finally:
        owner.close(); app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: embedded login loads after mounting; force reauthentication resets only the target")


if __name__ == "__main__":
    main()
