"""离线验证窗口内平台按钮、登录/关注切换、失败重试与取消收尾。"""
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog  # noqa: E402
from ddm import app as app_module, bili, theme  # noqa: E402
from ddm.account_dialog import AccountPlatformDialog  # noqa: E402
from ddm.dialogs import FollowImportDialog  # noqa: E402
from ddm.login import LoginWindow  # noqa: E402
from ddm.platform_login import PlatformFollowDialog  # noqa: E402
from dev.selfcheck_platform_follows import ROOMS, wait_for  # noqa: E402


def dispose(app, dialog):
    dialog.reject()
    dialog.deleteLater()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    account = {"uid": "123", "uname": "test", "face": ""}
    provider = SimpleNamespace(kind="douyu", label="斗鱼", follow_cookie_domain="douyu.com",
        follow_login_url="about:blank", account_login_url="about:blank#login",
        account_info=lambda _s, _c: account, follow_rooms=lambda _s, _c: ROOMS)
    with patch.object(app_module.QTimer, "singleShot"):
        owner = app_module.MainWindow([], [], state={"plugins_enabled": []})
    owner.plugins.platforms["douyu"] = provider
    owner.show()
    try:
        def offline_qr(page):
            page._thread = None
            page.qr_label.setText("offline QR")
        with patch.object(LoginWindow, "start_login", offline_qr), \
                patch.object(QInputDialog, "getItem", side_effect=AssertionError("Standalone picker")), \
                patch.object(owner, "_on_login", side_effect=bili.set_sessdata):
            bili.set_sessdata("")
            dialog = AccountPlatformDialog(owner, {"斗鱼": provider})
            dialog.show()
            app.processEvents()
            first = dialog.page
            thread = Mock(isRunning=Mock(return_value=True))
            first._thread = thread
            QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
            assert isinstance(dialog.page, PlatformFollowDialog)
            thread.cancel.assert_called_once()
            assert dialog.page.parentWidget() is dialog.pages and not dialog.page.isWindow()
            assert dialog.page._owner is owner and dialog.page.browser.zoomFactor() == .8
            assert len([w for w in app.topLevelWidgets() if w.isVisible() and w is not owner]) == 1
            QTest.mouseClick(dialog.platform_buttons["bilibili"], Qt.LeftButton)
            assert isinstance(dialog.page, LoginWindow) and dialog.isVisible()
            dialog.page._on_success("test-session")
            assert dialog.result() == QDialog.Accepted and not dialog.isVisible()
            dispose(app, dialog)

            # 第三方登录成功直接关闭；导入关注则在同一窗口进入勾选列表。
            dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, platform_kind="douyu")
            dialog.show()
            dialog.page._read()
            wait_for(app, lambda: not dialog.isVisible())
            assert dialog.result() == QDialog.Accepted and not dialog.rooms
            assert owner._accounts["douyu"] == account
            dispose(app, dialog)

            dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True,
                                           platform_kind="douyu")
            dialog.show()
            dialog.page._read()
            assert not dialog.platform_buttons["bilibili"].isEnabled()
            wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
            assert dialog.isVisible() and dialog.page.rooms == ROOMS
            assert all(b.isEnabled() for b in dialog.platform_buttons.values())
            dialog.page._check_all(True)
            dialog.page.accept()
            assert dialog.rooms == ROOMS and dialog.result() == QDialog.Accepted
            dispose(app, dialog)

            # B 站登录后读取列表，平台按钮在列表内保留，切换后清除勾选。
            bili.set_sessdata("")
            with patch.object(bili, "follow_rooms", return_value=[dict(ROOMS[0], room_id="123")]):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                dialog.page._on_success("test-session")
                wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
                dialog.page._check_all(True)
                QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                assert isinstance(dialog.page, PlatformFollowDialog) and not dialog.rooms
                dialog.page._read()
                wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
                assert dialog.page.selected() == []
                retained = dialog._platform_pages["douyu"]
                QTest.mouseClick(dialog.platform_buttons["bilibili"], Qt.LeftButton)
                wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
                QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                assert dialog.page is retained and dialog.page._pending_done is None
                dialog.page._read()
                wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
                assert dialog.page.rooms == ROOMS and dialog.page.selected() == []
                dispose(app, dialog)

            with patch.object(bili, "follow_rooms", side_effect=[RuntimeError("test failure"), []]):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                wait_for(app, lambda: dialog._bili_loader is None)
                assert "test failure" in dialog.status.text() and dialog.retry_button.isEnabled()
                QTest.mouseClick(dialog.retry_button, Qt.LeftButton)
                wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
                assert dialog.page.rooms == []
                dispose(app, dialog)

            # 取消正在读取的斗鱼请求：待线程退出后关闭，无迟到结果导入。
            entered, release = threading.Event(), threading.Event()
            def blocked(_session, _cancelled):
                entered.set()
                assert release.wait(5)
                return ROOMS
            with patch.object(provider, "follow_rooms", blocked):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True,
                                               platform_kind="douyu")
                dialog.show()
                page = dialog.page
                page._read()
                assert entered.wait(2)
                dialog.reject()
                assert dialog.isVisible() and page._worker.isRunning()
                release.set()
                wait_for(app, lambda: not dialog.isVisible())
                assert page._worker is None and not dialog.rooms
                assert dialog.result() == QDialog.Rejected
                dispose(app, dialog)

            # B 站旧请求返回时不能替换已关闭窗口或导入列表。
            entered, release = threading.Event(), threading.Event()
            def blocked_bili():
                entered.set()
                assert release.wait(5)
                return ROOMS
            with patch.object(bili, "follow_rooms", blocked_bili):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                assert entered.wait(2)
                dialog.reject()
                assert not dialog.isVisible()
                release.set()
                wait_for(app, lambda: dialog._bili_loader is None)
                assert not dialog.rooms and dialog.result() == QDialog.Rejected
                dispose(app, dialog)

            # 真实宿主模态入口直接打开带按钮的窗口，勾选后只添加一次。
            def confirm_import():
                dialog = next(w for w in app.topLevelWidgets()
                              if isinstance(w, AccountPlatformDialog) and w.isVisible())
                if not isinstance(dialog.page, FollowImportDialog):
                    QTimer.singleShot(10, confirm_import)
                    return
                assert dialog.platform_buttons["bilibili"].isVisible()
                dialog.page._check_all(True)
                dialog.page.accept()
            with patch.object(bili, "follow_rooms", return_value=ROOMS), \
                    patch.object(owner, "load_avatars_for"), patch.object(owner, "_refresh_meta"):
                for _ in range(2):
                    QTimer.singleShot(0, confirm_import)
                    owner.open_import_follows()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                assert len(owner.sidebar.rooms()) == 2
                assert not any(tile.room.get("room_id") for tile in owner.wall.tiles)
    finally:
        bili.set_sessdata("")
        owner.close()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: inline platform buttons, one window, login/import, selection isolation, retry, cancel and late results")


if __name__ == "__main__":
    main()
