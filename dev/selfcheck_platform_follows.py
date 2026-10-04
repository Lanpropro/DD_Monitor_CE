"""离线回归：平台登录 Cookie 隔离/加密、后台读取、取消和关注导入。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtNetwork import QNetworkCookie  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402
from ddm.account_store import AccountStore  # noqa: E402
from ddm.platform_login import PlatformFollowDialog, PlatformFollowLoader  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": "douyu:6979222", "uname": "live", "title": "test", "live": True,
          "platform": "douyu", "face": "", "cover_url": "", "viewers": "", "live_known": True},
         {"room_id": "douyu:123", "uname": "offline", "title": "", "live": False,
          "platform": "douyu", "face": "", "cover_url": "", "viewers": "", "live_known": True}]


def wait_for(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "Background import did not finish"


def platform(follow):
    return SimpleNamespace(kind="douyu", label="斗鱼", follow_login_url="about:blank",
                           follow_cookie_domain="douyu.com", follow_rooms=follow)


def check_store():
    with tempfile.TemporaryDirectory() as directory:
        store = AccountStore("douyu", directory)
        assert store.load() == []
        cookies = ["test-secret=cookie-value; domain=.douyu.com; path=/; secure; HttpOnly"]
        store.save(cookies)
        raw = store.path.read_bytes()
        assert b"cookie-value" not in raw and b"test-secret" not in raw
        assert store.load() == cookies
        account = {"uid": "123", "uname": "account-test", "face": ""}
        store.save(cookies, account)
        assert store.load() == cookies and store.load_account() == account
        from ddm.account_store import _crypt
        import json
        store.path.write_bytes(_crypt(json.dumps(cookies).encode()))
        assert store.load() == cookies and store.load_account() == {}
        store.path.write_bytes(b"corrupted")
        try:
            store.load()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Damaged DPAPI data must not load")
        store.clear()
        assert store.load() == [] and not store.path.exists()
        try:
            AccountStore("../secret", directory)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid account path accepted")
    print("PASS: DPAPI roundtrip, no plaintext credentials, corrupt data and logout cleanup")


def check_release():
    source = (ROOT / "dev/build_release.ps1").read_text(encoding="utf-8-sig")
    block = source.split('# utils 目录只要代码；', 1)[1].split('# ---- 3)', 1)[0]
    block = block.split('\n', 1)[1]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        utils = root / "source/utils"
        (utils / "accounts").mkdir(parents=True)
        (utils / "accounts/douyu.bin").write_bytes(b"test-encrypted-login")
        (utils / "config.json").write_text("test-config")
        (utils / "config.json.bak").write_text("test-backup")
        (utils / "__pycache__").mkdir()
        (utils / "__pycache__/module.pyc").write_bytes(b"test-cache")
        (utils / "module.py").write_text("# test code")
        script = root / "copy-utils.ps1"
        script.write_text('$ErrorActionPreference = "Stop"\n'
                          '$repo = $env:DDM_RELEASE_TEST_SOURCE\n'
                          '$app = $env:DDM_RELEASE_TEST_OUTPUT\n' + block, encoding="utf-8-sig")
        env = dict(os.environ, DDM_RELEASE_TEST_SOURCE=str(root / "source"),
                   DDM_RELEASE_TEST_OUTPUT=str(root / "output"))
        subprocess.run([shutil.which("pwsh") or "powershell", "-NoProfile", "-File", str(script)],
                       env=env, check=True, timeout=20, capture_output=True)
        assert [p.name for p in (root / "output/utils").iterdir()] == ["module.py"]
    print("PASS: actual release copy excludes accounts, config backups and cache")


def check_login(app):
    captured = []
    def follow(session, _cancelled):
        captured.append([(c.name, c.domain, c.path, c.secure) for c in session.cookies])
        return ROOMS

    dialog = PlatformFollowDialog(platform(follow))
    dialog.show()
    cookie = QNetworkCookie(b"test", b"value")
    cookie.setDomain(".douyu.com")
    cookie.setPath("/")
    cookie.setSecure(True)
    cookie.setHttpOnly(True)
    dialog._on_cookie(cookie)
    outsider = QNetworkCookie(b"foreign", b"secret")
    outsider.setDomain("douyu.com.evil.test")
    dialog._on_cookie(outsider)
    assert len(dialog._cookies) == 1 and dialog._profile.isOffTheRecord()
    dialog._read()
    wait_for(app, lambda: dialog._worker is None)
    assert dialog.result() == QDialog.DialogCode.Accepted and dialog.rooms == ROOMS
    assert captured == [[("test", ".douyu.com", "/", True)]]
    parsed = QNetworkCookie.parseCookies(dialog._saved_cookies[0].encode())
    assert parsed[0].domain() == ".douyu.com" and parsed[0].isHttpOnly()
    dialog.deleteLater()

    entered, release = threading.Event(), threading.Event()
    def blocked(_session, cancelled):
        entered.set()
        assert release.wait(5)
        return ROOMS
    dialog = PlatformFollowDialog(platform(blocked))
    dialog.show()
    dialog._read()
    assert entered.wait(2)
    dialog.reject()
    assert dialog._pending_done == QDialog.DialogCode.Rejected and dialog._worker.isRunning()
    release.set()
    wait_for(app, lambda: dialog._worker is None)
    assert dialog.result() == QDialog.DialogCode.Rejected and not dialog.rooms
    dialog.deleteLater()

    def expired(_session, _cancelled):
        raise RuntimeError("登录已过期，请重新登录")
    dialog = PlatformFollowDialog(platform(expired))
    dialog.show()
    dialog._read()
    wait_for(app, lambda: dialog._worker is None)
    assert dialog.isVisible() and "登录已过期" in dialog.status.text()
    with patch.object(dialog.account_store, "clear") as clear:
        dialog._forget()
        clear.assert_called_once()
        assert not dialog._cookies
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: real off-record WebEngine, scoped HttpOnly cookies, background read, cancel and expiry")


def check_host(app):
    state = {"plugins_enabled": [], "settings": {"recording_enabled": False,
             "recording_replay_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state=state)
    provider = platform(lambda _session, _cancelled: ROOMS)
    window.plugins.platforms["douyu"] = provider
    try:
        with patch("ddm.account_dialog.AccountPlatformDialog") as dialog, \
                patch.object(window, "_import_selected_follows") as loaded:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            dialog.return_value.rooms = ROOMS
            window.open_import_follows()
            assert dialog.call_args.kwargs["import_follows"]
            loaded.assert_called_once_with(ROOMS)
        with patch("ddm.account_dialog.AccountPlatformDialog") as dialog, \
                patch.object(window, "_import_selected_follows") as loaded:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            window.open_import_follows()
            loaded.assert_not_called()
        with patch.object(window, "load_avatars_for"), patch.object(window, "_refresh_meta"):
            window._import_selected_follows(ROOMS)
            window._import_selected_follows(ROOMS)
            assert len(window.sidebar.rooms()) == 2 and window._save_timer.isActive()
            assert len(window.wall.tiles) == 0 or all(not tile.room.get("room_id") for tile in window.wall.tiles)
        dialog = PlatformFollowDialog(provider, window)
        entered = threading.Event()
        def closing(_session, cancelled):
            entered.set()
            while not cancelled():
                time.sleep(.01)
            return []
        provider.follow_rooms = closing
        dialog._read()
        assert entered.wait(2) and isinstance(window._follow_loader, PlatformFollowLoader)
        window.close()
        assert not dialog._worker.isRunning()
        dialog.reject()
        wait_for(app, lambda: dialog._worker is None)
        assert not dialog.rooms
        dialog.deleteLater()
    finally:
        window.close()
    print("PASS: platform selector, cancel, existing selection/dedup/save, no autoplay, close cancels and waits")


def main():
    check_store()
    check_release()
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    check_login(app)
    check_host(app)
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == "__main__":
    main()
