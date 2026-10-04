"""离线验证窗口内平台按钮、登录/关注切换、失败重试与取消收尾。"""
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from shiboken6 import isValid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QLabel, QPushButton  # noqa: E402
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


def follows_ready(dialog):
    return isinstance(dialog.page, FollowImportDialog) and not dialog.page.property("loading")


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
            assert all(owner._accounts["douyu"][key] == value for key, value in account.items())
            dispose(app, dialog)

            # 已登录平台只展示身份，不再次创建二维码或浏览器登录页。
            with patch.object(LoginWindow, "start_login") as qr, \
                    patch("ddm.platform_login.PlatformFollowDialog", side_effect=AssertionError("Login reopened")):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider})
                dialog.show()
                assert "此平台已登录" in [label.text() for label in dialog.page.findChildren(QLabel)]
                dialog.select_platform("douyu")
                from ddm.widgets import AccountRow
                assert dialog.page.findChild(AccountRow).uid == "123"
                dialog.select_platform("bilibili")
                qr.assert_not_called()
                dispose(app, dialog)

            # 此段覆盖未登录的平台由用户手动读取的入口。
            owner._clear_platform_account("douyu")
            dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True,
                                           platform_kind="douyu")
            dialog.show()
            dialog.page._read()
            assert not dialog.platform_buttons["bilibili"].isEnabled()
            wait_for(app, lambda: follows_ready(dialog))
            assert dialog.isVisible() and dialog.page.rooms == ROOMS
            assert all(b.isEnabled() for b in dialog.platform_buttons.values())
            dialog.page._check_all(True)
            dialog.page.accept()
            assert dialog.rooms == ROOMS and dialog.result() == QDialog.Accepted
            dispose(app, dialog)
            owner._clear_platform_account("douyu")

            # 成功读取后切回直接恢复列表，各平台的勾选、搜索和文件夹分别保留。
            bili.set_sessdata("")
            bili_rooms = [dict(ROOMS[0], room_id="123")]
            folders = [{"id": "games", "name": "赛事", "type": "normal"}]
            with patch.object(bili, "follow_rooms", return_value=bili_rooms) as bili_read, \
                    patch.object(provider, "follow_rooms", return_value=ROOMS) as douyu_read, \
                    patch.object(owner.sidebar, "folder_state", return_value=folders):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                dialog.page._on_success("test-session")
                wait_for(app, lambda: follows_ready(dialog))
                bili_page = dialog.page
                bili_page._check_all(True)
                bili_page.search_edit.setText("live")
                QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                assert isinstance(dialog.page, PlatformFollowDialog) and not dialog.rooms
                dialog.page._read()
                wait_for(app, lambda: follows_ready(dialog))
                assert dialog.page.selected() == []
                douyu_page = dialog.page
                douyu_page.list.item(1).setCheckState(Qt.Checked)
                douyu_page.search_edit.setText("offline")
                next(a for a in douyu_page.folder_button.menu().actions()
                     if a.data() == "games").trigger()
                completed = Mock()
                dialog.finished.connect(completed)
                browser = dialog._platform_pages["douyu"].browser
                with patch.object(browser, "load") as browser_load:
                    for _ in range(4):
                        QTest.mouseClick(dialog.platform_buttons["bilibili"], Qt.LeftButton)
                        assert dialog.page is bili_page and not douyu_page.isVisible()
                        assert dialog.page.selected() == bili_rooms
                        assert dialog.page.search_edit.text() == "live" and dialog.page.folder_id == ""
                        QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                        assert dialog.page is douyu_page and not bili_page.isVisible()
                        assert dialog.page.selected() == [ROOMS[1]]
                        assert dialog.page.search_edit.text() == "offline"
                        assert dialog.page.folder_id == "games" and dialog.pages.count() == 1
                    browser_load.assert_not_called()
                bili_read.assert_called_once()
                douyu_read.assert_called_once()
                completed.assert_not_called()
                douyu_page.accept()
                assert dialog.rooms == [ROOMS[1]] and dialog.folder_id == "games"
                assert dialog.result() == QDialog.Accepted
                completed.assert_called_once_with(QDialog.Accepted)
                dispose(app, dialog)
                assert not isValid(bili_page) and not isValid(douyu_page)

            with patch.object(bili, "follow_rooms", side_effect=[RuntimeError("test failure"), []]):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                wait_for(app, lambda: dialog._bili_loader is None)
                assert "test failure" in dialog.status.text() and dialog.retry_button.isEnabled()
                assert dialog.retry_button.isVisible() and not dialog.page.import_button.isEnabled()
                assert dialog.retry_button.width() < dialog.page.width() // 2
                assert "bilibili" not in dialog._follow_pages
                QTest.mouseClick(dialog.retry_button, Qt.LeftButton)
                wait_for(app, lambda: follows_ready(dialog))
                assert dialog.page.rooms == []
                empty_bili = dialog.page
                with patch.object(provider, "follow_rooms", return_value=[]) as douyu_read:
                    QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                    wait_for(app, lambda: follows_ready(dialog))
                    empty_douyu = dialog.page
                    assert empty_douyu.rooms == []
                    QTest.mouseClick(dialog.platform_buttons["bilibili"], Qt.LeftButton)
                    assert dialog.page is empty_bili
                    QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                    assert dialog.page is empty_douyu
                    douyu_read.assert_called_once()
                dispose(app, dialog)

            # 取消正在读取的斗鱼请求：待线程退出后关闭，无迟到结果导入。
            entered, release = threading.Event(), threading.Event()
            def blocked(_session, _cancelled):
                entered.set()
                assert release.wait(5)
                return ROOMS
            with patch.object(provider, "follow_rooms", blocked):
                owner._clear_platform_account("douyu")
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

            # 加载页使用列表页的按钮行；读取完成前后按钮位置、大小和窗口尺寸一致。
            entered, release = threading.Event(), threading.Event()
            def loading_bili():
                entered.set()
                assert release.wait(5)
                return ROOMS
            with patch.object(bili, "follow_rooms", loading_bili):
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=True)
                dialog.show()
                assert entered.wait(2)
                app.processEvents()
                page = dialog.page
                assert isinstance(page, FollowImportDialog) and page.property("loading")
                assert not page.import_button.isEnabled()
                assert all(not b.isEnabled() for b in page.filter_buttons)
                assert not dialog.retry_button.isVisible()
                assert dialog.status.isVisible() and "加载" in dialog.status.text()
                cancel = next(b for b in page.findChildren(QPushButton) if b.text() == "取消")
                loading_size = dialog.size()
                cancel_rect = cancel.geometry()
                import_rect = page.import_button.geometry()
                list_rect = page.list.geometry()
                assert cancel.isEnabled() and cancel.objectName() == "IconButton"
                assert abs(cancel_rect.center().y() - import_rect.center().y()) <= 1
                assert cancel_rect.right() < import_rect.left()
                release.set()
                wait_for(app, lambda: follows_ready(dialog))
                app.processEvents()
                page = dialog.page
                cancel = next(b for b in page.findChildren(QPushButton) if b.text() == "取消")
                assert dialog.size() == loading_size and page.list.geometry() == list_rect
                assert cancel.geometry() == cancel_rect and page.import_button.geometry() == import_rect
                assert page.import_button.isEnabled() and all(b.isEnabled() for b in page.filter_buttons)
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
                if not follows_ready(dialog):
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
    print("PASS: inline platforms, cached lists/selections/search/folders, no duplicate read/import, empty lists, retry and cancel")


if __name__ == "__main__":
    main()
