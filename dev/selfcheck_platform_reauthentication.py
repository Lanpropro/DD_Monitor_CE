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
from PySide6.QtWidgets import QApplication
from ddm import app as host
from ddm.account_dialog import AccountPlatformDialog
from ddm.platform_login import PlatformFollowDialog


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(host.QTimer, "singleShot"):
        owner = host.MainWindow([], [], state={"plugins_enabled": [], "settings": {"auto_update": False}})
    providers = {name: SimpleNamespace(kind=name, label=name, follow_cookie_domain=name+".com",
        follow_login_url="about:blank", account_login_url="about:blank",
        account_info=lambda *_: {"uid":"1"}, follow_rooms=lambda *_: []) for name in ("huya", "douyu")}
    owner._accounts.update({name:{"uid":"1","uname":"fixture"} for name in providers})
    try:
        with patch.object(PlatformFollowDialog, "_forget") as forget:
            normal = AccountPlatformDialog(owner, providers, platform_kind="huya")
            assert not isinstance(normal.page, PlatformFollowDialog)
            forget.assert_not_called()
            normal.reject(); normal.deleteLater()
            forced = AccountPlatformDialog(owner, providers, platform_kind="huya", reauthenticate=True)
            assert isinstance(forced.page, PlatformFollowDialog)
            forget.assert_called_once()
            forced.select_platform("douyu")
            assert not isinstance(forced.page, PlatformFollowDialog)
            forget.assert_called_once()
            forced.reject(); forced.deleteLater()
    finally:
        owner.close(); app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: force reauthentication opens browser, resets once, preserves other platforms")


if __name__ == "__main__":
    main()
