"""离线回归：账号信息首次失败可恢复，旧登录请求不能覆盖退出状态。"""
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module, bili  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


class AccountStub(QObject):
    loaded = Signal(dict)
    failed = Signal()
    finished = Signal()
    responses = []
    instances = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instances.append(self)

    def start(self):
        account = self.responses.pop(0)
        if account:
            self.loaded.emit(account)
        else:
            self.failed.emit()

    def isRunning(self):
        return False


class AvatarStub(QObject):
    loaded = Signal(str, QPixmap)
    finished = Signal()

    def __init__(self, faces, parent=None):
        super().__init__(parent)

    def start(self):
        pass

    def isRunning(self):
        return False


def main():
    app = QApplication(sys.argv)
    loader = bili.AccountLoader()
    failed, loaded = [], []
    loader.failed.connect(lambda: failed.append(True))
    loader.loaded.connect(lambda account: loaded.append(account))
    with patch.object(bili, "my_account", side_effect=[None, {"uname": "worker-test"}]):
        loader.run()
        loader.run()
    assert failed == [True] and loaded == [{"uname": "worker-test"}]
    with patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "sync_danmaku"), \
            patch.object(app_module, "AccountLoader", AccountStub):
        window = MainWindow([], [], state={"sessdata": "test-login"})
        try:
            scheduled = []
            with patch.object(app_module.QTimer, "singleShot",
                              side_effect=lambda delay, callback: scheduled.append((delay, callback))):
                AccountStub.responses[:] = [None, {"uname": "test-account"}]
                window.refresh_account()
                assert len(scheduled) == 1, "账号请求失败后必须安排恢复尝试"
                assert scheduled[0][0] == 5000
                scheduled.pop()[1]()
                assert window.sidebar.account_row.uname == "test-account"
                assert not scheduled
                AccountStub.responses[:] = [None, None]
                window.refresh_account()
                scheduled.pop()[1]()
                assert not scheduled, "失败恢复只尝试一次，不能无限请求账号接口"
                assert window.sidebar.account_row.uname == "test-account", "请求失败不能清掉已有昵称"
                stale = AccountStub.instances[-1]
                window.logout()
                stale.loaded.emit({"uname": "stale-account"})
                assert not window.sidebar.account_row.uname, "退出后旧请求不能恢复账号显示"
                bili.set_sessdata("test-login")
                AccountStub.responses[:] = [None]
                window.refresh_account()
                window.logout()
                count = len(AccountStub.instances)
                scheduled.pop()[1]()
                assert not scheduled and len(AccountStub.instances) == count, "退出后不能执行延迟重试"
                bili.set_sessdata("test-login")
                with patch.object(app_module, "AvatarLoader", AvatarStub):
                    window._on_account_loaded({"uname": "avatar-test", "face": "mock-face"})
                    avatar_loader = window._account_avatar_loader
                    window.logout()
                    avatar_loader.loaded.emit("account", QPixmap(26, 26))
                    assert not window.sidebar.account_row.uname, "退出后旧头像请求不能恢复账号显示"
        finally:
            window.close()
            app.processEvents()
    print("账号信息失败恢复、重试上限及退出隔离：通过", flush=True)


if __name__ == "__main__":
    main()
