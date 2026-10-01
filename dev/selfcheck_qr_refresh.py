"""离线回归：二维码等待扫码期间可刷新，旧请求不能覆盖新二维码或完成登录。"""
import os
import sys
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import bili, login  # noqa: E402


class QRStub(QObject):
    qrReady = Signal(str)
    statusChanged = Signal(str)
    succeeded = Signal(str)
    expired = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = False
        self.running = False

    def start(self):
        self.running = True

    def cancel(self):
        self.cancelled = True

    def isRunning(self):
        return self.running

    def wait(self, _timeout):
        return False


def main():
    app = QApplication(sys.argv)
    with patch.object(login, "QRLogin", QRStub), patch.object(bili, "set_sessdata") as set_session:
        window = login.LoginWindow()
        try:
            window.show()
            app.processEvents()
            buttons = window.findChildren(QPushButton)
            assert not any(button.hasFocus() for button in buttons), "打开扫码页不能自动选中按钮"
            first = window._thread
            assert not window.refresh_button.isEnabled(), "获取二维码期间不能重复发送生成请求"
            first.qrReady.emit("https://example.com/first")
            assert window.refresh_button.isEnabled(), "等待扫码时必须允许刷新二维码"
            for button in buttons:
                QTest.mouseMove(button, button.rect().center())
                app.processEvents()
                assert button.cursor().shape() == Qt.PointingHandCursor, \
                    f"{button.text()} 悬停时必须显示可点击的手形指针"
            assert not any(button.hasFocus() for button in buttons)
            QTest.keyClick(window, Qt.Key_Tab)
            app.processEvents()
            assert any(button.hasFocus() for button in buttons), "Tab 键仍应能选择登录按钮"
            QTest.mouseClick(window.refresh_button, Qt.LeftButton)
            second = window._thread
            assert second is not first and first.cancelled
            assert not window.refresh_button.isEnabled()
            first.qrReady.emit("https://example.com/stale")
            first.statusChanged.emit("stale status")
            first.succeeded.emit("stale-session")
            first.expired.emit()
            first.failed.emit("stale error")
            first.finished.emit()
            assert not window.refresh_button.isEnabled(), "旧线程结束不能提前启用新请求的刷新按钮"
            assert window.status.text() == "正在获取二维码…"
            assert not window.sessdata
            set_session.assert_not_called()
            second.qrReady.emit("https://example.com/second")
            assert window.refresh_button.isEnabled()
            second.expired.emit()
            assert window.refresh_button.isEnabled()
            QTest.mouseClick(window.refresh_button, Qt.LeftButton)
            third = window._thread
            third.failed.emit("mock network error")
            assert window.refresh_button.isEnabled(), "获取失败后必须允许重试"
            window.reject()
            assert third.cancelled, "取消登录时必须取消后台扫码轮询"
            third.succeeded.emit("late-session")
            set_session.assert_not_called()
        finally:
            window.close()
            app.processEvents()
        window = login.LoginWindow()
        current = window._thread
        current.qrReady.emit("https://example.com/current")
        current.succeeded.emit("current-session")
        set_session.assert_called_once_with("current-session")
        assert window.sessdata == "current-session"
        assert window.result() == QDialog.DialogCode.Accepted
        window.close()
    for cancel_on in ("generate", "poll"):
        worker = login.QRLogin()
        emitted = []
        worker.qrReady.connect(lambda url: emitted.append("qr"))
        worker.succeeded.connect(lambda session: emitted.append("success"))

        def get(url, **kwargs):
            if url == login.GENERATE_URL:
                if cancel_on == "generate":
                    worker.cancel()
                return Mock(json=lambda: {"data": {
                    "qrcode_key": "test-key", "url": "https://example.com/qr"}})
            worker.cancel()
            return Mock(json=lambda: {"data": {"code": login.QR_SUCCESS}})

        session = Mock()
        session.get.side_effect = get
        with patch.object(login.requests, "Session", return_value=session):
            worker.run()
        assert "success" not in emitted
        assert emitted == ([] if cancel_on == "generate" else ["qr"])
    print("二维码刷新、失败重试、旧请求隔离和取消轮询：通过", flush=True)


if __name__ == "__main__":
    main()
