"""B 站扫码登录。

直接调用扫码登录接口（generate + poll），由我们自己控制整个流程：
不再依赖内嵌浏览器，也就不存在"登录完成了但拿不到 cookie"的问题。
"""
import sys
import threading
import time

import qrcode
import requests
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from . import bili

GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

# 接口返回的状态码
QR_SUCCESS = 0
QR_EXPIRED = 86038
QR_SCANNED = 86090
QR_WAITING = 86101


def _log(message: str) -> None:
    print(f"[登录] {message}", file=sys.stderr, flush=True)


def make_qr_pixmap(text: str, size: int = 260) -> QPixmap:
    """把二维码内容画成图片（qrcode 只生成矩阵，图片自己画）。"""
    code = qrcode.QRCode(border=2, box_size=1)
    code.add_data(text)
    code.make(fit=True)
    matrix = code.get_matrix()
    modules = len(matrix)
    scale = max(2, size // modules)
    side = modules * scale
    image = QImage(side, side, QImage.Format_RGB32)
    image.fill(0xFFFFFFFF)
    for row_index, row in enumerate(matrix):
        for column, dark in enumerate(row):
            if not dark:
                continue
            for dy in range(scale):
                y = row_index * scale + dy
                for dx in range(scale):
                    image.setPixel(column * scale + dx, y, 0xFF000000)
    return QPixmap.fromImage(image)


class QRLogin(QThread):
    """后台生成二维码并轮询扫码状态。"""

    qrReady = Signal(str)          # 二维码内容（URL）
    statusChanged = Signal(str)    # 状态文案
    succeeded = Signal(str)        # SESSDATA
    expired = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False
        self._cancel_event = threading.Event()
        self.sessdata = ""

    def cancel(self) -> None:
        self._cancelled = True
        self._cancel_event.set()

    def run(self) -> None:
        session = requests.Session()
        session.headers.update(bili.HEADERS)
        try:
            response = session.get(GENERATE_URL, timeout=10)
            data = response.json().get("data") or {}
            key = data.get("qrcode_key") or ""
            url = data.get("url") or ""
        except Exception as error:  # noqa: BLE001
            self.failed.emit(f"二维码获取失败: {error}")
            return
        if self._cancelled:
            return
        if not key:
            self.failed.emit("二维码接口没有返回 key")
            return
        _log("二维码已生成，等待扫码")
        self.qrReady.emit(url)
        self.statusChanged.emit("请用 B 站手机客户端扫码登录")

        deadline = time.time() + 180
        while not self._cancelled and time.time() < deadline:
            try:
                poll = session.get(POLL_URL, params={"qrcode_key": key}, timeout=10)
                payload = poll.json().get("data") or {}
                code = payload.get("code")
            except Exception as error:  # noqa: BLE001
                _log(f"轮询异常: {error}")
                self._cancel_event.wait(2)
                continue

            if self._cancelled:
                return

            if code == QR_SUCCESS:
                sessdata = (poll.cookies.get("SESSDATA")
                            or session.cookies.get("SESSDATA") or "")
                if not sessdata:
                    self.failed.emit("登录成功但没拿到 SESSDATA")
                    return
                _log(f"扫码登录成功（SESSDATA {len(sessdata)} 字符）")
                self.sessdata = sessdata
                self.succeeded.emit(sessdata)
                return
            if code == QR_SCANNED:
                self.statusChanged.emit("已扫码，请在手机上点击确认")
            elif code == QR_EXPIRED:
                _log("二维码已失效")
                self.expired.emit()
                return
            self._cancel_event.wait(2)

        if not self._cancelled:
            self.expired.emit()


# 网络请求可能在窗口关闭后才返回，必须持有线程直到它自然结束。
_active_qr_threads: set[QRLogin] = set()


class LoginWindow(QDialog):
    """扫码登录窗口：登录成功自动关闭。"""

    sessionData = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginWindow")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle("登录 B 站")
        self.resize(420, 460)
        self.sessdata = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("扫码登录 B 站")
        title.setObjectName("AppTitle")
        layout.addWidget(title, 0, Qt.AlignHCenter)

        self.qr_label = QLabel("二维码加载中…")
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setFixedSize(280, 280)
        self.qr_label.setStyleSheet(
            f"background: {theme_surface()}; border-radius: 12px; color: #8a8f98;")
        layout.addWidget(self.qr_label, 0, Qt.AlignHCenter)

        self.status = QLabel("正在获取二维码…")
        self.status.setObjectName("AppSubtitle")
        self.status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.refresh_button = QPushButton("刷新二维码")
        self.refresh_button.setObjectName("IconButton")
        self.refresh_button.clicked.connect(self.start_login)
        manual_button = QPushButton("账号密码登录")
        manual_button.setObjectName("IconButton")
        manual_button.clicked.connect(self._web_login)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("IconButton")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(manual_button)
        buttons.addWidget(cancel_button)
        for button in (self.refresh_button, manual_button, cancel_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.TabFocus)
            button.setAutoDefault(False)
        layout.addLayout(buttons)

        self._thread: QRLogin | None = None
        self.start_login()
        self.setFocus(Qt.OtherFocusReason)

    # ---- 流程 ----
    def start_login(self) -> None:
        self._stop_thread()
        self.qr_label.setText("二维码加载中…")
        self.status.setText("正在获取二维码…")
        self.refresh_button.setEnabled(False)
        thread = QRLogin()
        _active_qr_threads.add(thread)
        current = lambda: self._thread is thread
        thread.qrReady.connect(lambda url: self._show_qr(url) if current() else None)
        thread.statusChanged.connect(lambda text: self.status.setText(text) if current() else None)
        thread.succeeded.connect(lambda session: self._on_success(session) if current() else None)
        thread.expired.connect(lambda: self._on_expired() if current() else None)
        thread.failed.connect(lambda message: self._on_failed(message) if current() else None)
        thread.finished.connect(lambda: self._on_thread_finished(thread))
        thread.finished.connect(lambda: _active_qr_threads.discard(thread))
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        thread.start()

    def _stop_thread(self) -> None:
        thread = self._thread
        self._thread = None
        if thread is not None and thread.isRunning():
            thread.cancel()

    def _on_thread_finished(self, thread) -> None:
        if self._thread is thread:
            self._thread = None
            self.refresh_button.setEnabled(True)

    def _show_qr(self, url: str) -> None:
        self.qr_label.setPixmap(make_qr_pixmap(url, 260))
        self.refresh_button.setEnabled(True)

    def _on_success(self, sessdata: str) -> None:
        self.sessdata = sessdata
        bili.set_sessdata(sessdata)
        self.status.setText("登录成功，窗口即将关闭…")
        self.sessionData.emit(sessdata)
        self.accept()

    def _on_expired(self) -> None:
        self.refresh_button.setEnabled(True)
        self.qr_label.setText("二维码已失效\n点下方按钮刷新")
        self.status.setText("二维码已失效")

    def _on_failed(self, message: str) -> None:
        self.refresh_button.setEnabled(True)
        self.qr_label.setText("二维码获取失败")
        self.status.setText(message)

    def _web_login(self) -> None:
        """折中方案：用内嵌浏览器走账号密码登录。"""
        from .web_login import WebLoginWindow      # 延迟导入 QtWebEngine

        self._stop_thread()
        window = WebLoginWindow(self)
        window.sessionData.connect(self._session_from_web)
        window.exec()
        if not self.sessdata:
            self.start_login()                     # 没登上就重新出二维码

    def _session_from_web(self, sessdata: str) -> None:
        self.sessdata = sessdata
        self.sessionData.emit(sessdata)
        self.accept()

    def closeEvent(self, event) -> None:
        self._stop_thread()
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self._stop_thread()
        super().done(result)


def theme_surface() -> str:
    from . import theme
    return theme.CONTENT
