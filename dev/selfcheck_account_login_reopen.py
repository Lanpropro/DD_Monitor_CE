"""真实菜单回归：已登录账号再次登录须先退出菜单和鼠标回调。"""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PySide6.QtCore import QCoreApplication, QEvent, QThread, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, bili
from ddm.account_dialog import AccountPlatformDialog


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with patch.object(app_module.QTimer, "singleShot"):
        owner = app_module.MainWindow([], [], state={"plugins_enabled": []})
    owner.plugins.platforms["douyu"] = SimpleNamespace(
        kind="douyu", label="斗鱼", follow_login_url="about:blank",
        follow_cookie_domain="douyu.com", account_login_url="about:blank",
        account_info=lambda _session, _cancelled: {"uid": "2", "uname": "test"})
    bili.set_sessdata("offline-session")
    owner._accounts["bilibili"] = {"uid": "1", "uname": "offline-account", "face": ""}
    owner._render_account()
    owner.show()
    failures = []
    active = {"clicking": False, "menu_returned": False, "calls": 0}
    baseline = []
    results = []

    def before_login():
        active["calls"] += 1
        results.append((active["menu_returned"], active["clicking"],
                        QThread.currentThread().loopLevel()))

    # MainWindow 的原有登录信号先接到了 open_login；在该入口记录真实时序。
    original_login = owner.open_login

    def login():
        before_login()
        original_login()

    owner.open_login = login

    def click_login():
        try:
            menu = app.activePopupWidget()
            assert menu is not None, "点击已登录用户名必须打开账号菜单"
            button = menu.actions()[0].defaultWidget()
            active["clicking"] = True
            QTest.mouseClick(button, Qt.LeftButton)
        except Exception as error:
            failures.append(error)
        finally:
            active["clicking"] = False

    def close_login():
        try:
            dialog = app.activeModalWidget()
            assert isinstance(dialog, AccountPlatformDialog), "应打开实际平台登录窗口"
            assert dialog.kind == "douyu" and dialog.isEnabled()
            assert dialog.page.browser.isEnabled()
            assert app.activePopupWidget() is None, "登录期间不应残留账号菜单"
            dialog.reject()
        except Exception as error:
            failures.append(error)
            modal = app.activeModalWidget()
            if modal is not None:
                modal.reject()
            popup = app.activePopupWidget()
            if popup is not None:
                popup.close()

    # 真实 QMenu.exec + QPushButton 点击 + 平台网页登录，不模拟 exec 返回值。
    def run():
        try:
            baseline.append(QThread.currentThread().loopLevel())
            for collapsed in (False, True):
                owner.sidebar.set_collapsed(collapsed, animate=False)
                for _ in range(2):
                    active.update(menu_returned=False, clicking=False)
                    QTimer.singleShot(30, click_login)
                    QTimer.singleShot(500, close_login)
                    QTest.mouseClick(owner.sidebar.account_row, Qt.LeftButton)
                    active["menu_returned"] = True
                    QTest.qWait(650)
                    assert app.activeModalWidget() is None
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            assert active["calls"] == 4, "每次点击只能发起一次登录"
            assert all(returned and not clicking and depth == baseline[0]
                       for returned, clicking, depth in results), (
                "登录必须在菜单循环及鼠标点击返回之后开始", results, baseline)
        except Exception as error:
            failures.append(error)
        finally:
            app.quit()

    # 外部进程还应设置超时，以便原生图形后端卡死时也能终止自检。
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(lambda: (failures.append(AssertionError("登录自检超时")), app.quit()))
    deadline.start(15000)
    QTimer.singleShot(0, run)
    try:
        app.exec()
    finally:
        deadline.stop()
        bili.set_sessdata("")
        owner.close()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not failures, failures
    print("PASS: real account menu exits before login; 4 browser reopens/cancels, expanded/collapsed")


if __name__ == "__main__":
    main()
