"""真实 QThread 回归：慢请求期间刷新/取消不阻塞，销毁窗口不销毁运行中线程。"""
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import shiboken6

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import login, theme  # noqa: E402


class SlowQR(login.QRLogin):
    workers = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self.release_request = threading.Event()
        self.workers.append(self)

    def run(self):
        self.qrReady.emit("https://example.com/slow-request")
        self.release_request.wait(10)  # 模拟取消后仍在返回途中的网络请求。
        self.statusChanged.emit("late status")
        self.succeeded.emit("late-session")


class WebStub(QObject):
    sessionData = Signal(str)

    def exec(self):
        return 0


def wait_ready(app, window):
    deadline = time.monotonic() + 2
    while not window.refresh_button.isEnabled() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert window.refresh_button.isEnabled()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    with patch.object(login, "QRLogin", SlowQR):
        window = login.LoginWindow()
        try:
            window.show()
            wait_ready(app, window)
            button = window.refresh_button
            QTest.mouseMove(button, button.rect().center())
            app.processEvents()
            normal_color = button.grab().toImage().pixelColor(10, button.height() // 2)
            QTest.mousePress(button, Qt.LeftButton)
            app.processEvents()
            pressed_color = button.grab().toImage().pixelColor(10, button.height() // 2)
            assert normal_color != pressed_color, "登录按钮按下时必须有可见反馈"
            start = time.monotonic()
            QTest.mouseRelease(button, Qt.LeftButton)
            refresh_ms = (time.monotonic() - start) * 1000
            wait_ready(app, window)
            previous = window._thread
            start = time.monotonic()
            with patch.dict(sys.modules, {"ddm.web_login": SimpleNamespace(WebLoginWindow=WebStub)}):
                window._web_login()
            web_ms = (time.monotonic() - start) * 1000
            assert previous._cancelled and window._thread is not previous
            assert web_ms < 150, "切换网页登录不能等待二维码网络线程"
            wait_ready(app, window)
            start = time.monotonic()
            window.reject()
            cancel_ms = (time.monotonic() - start) * 1000
            print(f"refresh={refresh_ms:.0f}ms web-switch={web_ms:.0f}ms cancel={cancel_ms:.0f}ms", flush=True)
            assert refresh_ms < 150 and cancel_ms < 150, "按钮点击不能等待网络线程"
            assert all(worker.parent() is not window for worker in SlowQR.workers)
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            assert not shiboken6.isValid(window)
            assert all(worker.isRunning() for worker in SlowQR.workers), "窗口销毁后慢请求应仍可安全收尾"
        finally:
            for worker in SlowQR.workers:
                worker.release_request.set()
                worker.wait(2000)
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            if shiboken6.isValid(window):
                window.close()
    print("慢请求下刷新/取消响应及窗口销毁安全：通过", flush=True)


if __name__ == "__main__":
    main()
