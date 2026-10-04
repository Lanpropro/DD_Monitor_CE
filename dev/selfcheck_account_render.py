"""Windows 屏幕回归：使用实际图形后端，验证登录/关注页面反复切换。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# 与正常启动一致，不开启 AA_ShareOpenGLContexts，也不禁用 GPU。
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import app as app_module, bili, theme  # noqa: E402
from ddm.account_dialog import AccountPlatformDialog  # noqa: E402
from ddm.dialogs import FollowImportDialog  # noqa: E402
from ddm.login import LoginWindow  # noqa: E402

ROOMS = [{"room_id": "123", "uname": "test", "title": "render test", "live": True, "face": ""}]


def wait_for(app, predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "Background list did not finish"


def screen_color(dialog, widget, color, name):
    # QWidget.grab()/grabWindow(hwnd) 不能代表 DWM 合成后的显示，截取屏幕上的窗口区域。
    origin = dialog.mapToGlobal(QPoint())
    capture = dialog.screen().grabWindow(0, origin.x(), origin.y(), dialog.width(), dialog.height())
    point = widget.mapTo(dialog, QPoint(widget.width() // 2, widget.height() // 2))
    point = QPoint(round(point.x() * capture.devicePixelRatio()),
                   round(point.y() * capture.devicePixelRatio()))
    actual = capture.toImage().pixelColor(point)
    preview = ROOT / "work/preview"
    preview.mkdir(parents=True, exist_ok=True)
    assert capture.save(str(preview / f"account-switch-{name}.png"))
    assert actual == QColor(color), f"{name}: expected {color}, screen shows {actual.name()}"


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    with patch.object(app_module.QTimer, "singleShot"):
        owner = app_module.MainWindow([], [], state={"plugins_enabled": []})
    from PySide6.QtWebEngineWidgets import QWebEngineView
    provider = SimpleNamespace(kind="douyu", label="斗鱼", follow_cookie_domain="douyu.com",
        follow_login_url="about:blank", account_login_url="about:blank#login",
        account_info=lambda _s, _c: {"uid": "123", "uname": "test", "face": ""},
        follow_rooms=lambda _s, _c: ROOMS)
    errors = []
    original_load = QWebEngineView.load

    def load_in_place(view, url):
        # 浏览器第一次加载时就属于最终窗口，不能先创建独立登录窗口再迁移。
        assert isinstance(view.window(), AccountPlatformDialog), "Browser loaded in a temporary window"
        return original_load(view, url)

    def qr(page):
        page._thread = None
        pixmap = QPixmap(280, 280)
        pixmap.fill(QColor("#e14e76"))
        page.qr_label.setPixmap(pixmap)

    try:
        with patch.object(LoginWindow, "start_login", qr), \
                patch.object(QWebEngineView, "load", load_in_place), \
                patch.object(bili, "follow_rooms", return_value=ROOMS):
            for imports in (False, True):
                bili.set_sessdata("test-session" if imports else "")
                dialog = AccountPlatformDialog(owner, {"斗鱼": provider}, import_follows=imports)
                dialog.move(80, 80)

                def show_bili():
                    if imports:
                        wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog))
                        widget = dialog.page.list
                        widget.setStyleSheet("background: #4555a8; color: white;")
                        color = "#4555a8"
                    else:
                        assert isinstance(dialog.page, LoginWindow)
                        widget, color = dialog.page.qr_label, "#e14e76"
                    QTest.qWait(200)
                    assert dialog.pages.currentWidget() is dialog.page
                    assert dialog.page.geometry() == dialog.pages.rect()
                    return widget, color

                def steps():
                    try:
                        widget, color = show_bili()
                        screen_color(dialog, widget, color, f"{imports}-bili-start")
                        retained = None
                        sizes = []
                        for cycle in range(4):
                            old = dialog.page
                            QTest.mouseClick(dialog.platform_buttons["douyu"], Qt.LeftButton)
                            page = dialog.page
                            assert not old.isVisible() and page.window() is dialog
                            if retained is not None:
                                assert page is retained
                            retained = page
                            wait_for(app, lambda: page.browser.url().toString() == provider.account_login_url
                                     and not page.browser.page().isLoading())
                            loaded = []
                            page.browser.loadFinished.connect(loaded.append)
                            page.browser.setHtml('<html><body style="margin:0;background:#32b464;'
                                                 'height:100vh">DOUYU RENDER TEST</body></html>')
                            wait_for(app, lambda: bool(loaded))
                            assert loaded[-1]
                            page.browser.loadFinished.disconnect(loaded.append)
                            QTest.qWait(200)
                            assert dialog.pages.currentWidget() is page
                            assert page.geometry() == dialog.pages.rect()
                            assert len(dialog._platform_pages) == 1 and dialog.pages.count() == 1
                            screen_color(dialog, page.browser, "#32b464", f"{imports}-douyu-{cycle}")
                            sizes.append(dialog.size())
                            QTest.mouseClick(dialog.platform_buttons["bilibili"], Qt.LeftButton)
                            widget, color = show_bili()
                            assert not page.isVisible() and page.window() is dialog
                            screen_color(dialog, widget, color, f"{imports}-bili-{cycle}")
                        assert all(size == sizes[0] for size in sizes), "Window grows on each switch"
                    except Exception as error:  # noqa: BLE001
                        errors.append(error)
                    finally:
                        dialog.reject()

                QTimer.singleShot(0, steps)
                dialog.exec()
                dialog.deleteLater()
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                if errors:
                    raise errors[0]
    finally:
        bili.set_sessdata("")
        owner.close()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print("PASS: production graphics, browser created in place, 8 round trips, screen colors, page bounds and stable size")


if __name__ == "__main__":
    main()
