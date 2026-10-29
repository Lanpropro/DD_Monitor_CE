"""账号密码登录：内嵌浏览器打开 B 站登录页，抓到 SESSDATA 自动关闭。

只在用户主动选择"账号密码登录"时才导入 QtWebEngine（比较重）。
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import bili
from . import config

PROFILE_NAME = "ddm-login"
_profile: QWebEngineProfile | None = None


def _log(message: str) -> None:
    print(f"[网页登录] {message}", file=sys.stderr, flush=True)


def _shared_profile() -> QWebEngineProfile:
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile(PROFILE_NAME)
        _profile.setCachePath(str(Path(config.data_root()) / 'cache' / 'web-login'))
    return _profile


class _NoPopupPage(QWebEnginePage):
    """屏蔽弹窗，避免登录过程里冒出一堆窗口。"""

    def createWindow(self, _type):  # noqa: N802
        return None


class WebLoginWindow(QDialog):
    """内嵌浏览器登录窗口。"""

    sessionData = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("账号密码登录 B 站")
        self.resize(980, 640)
        self.sessdata = ""
        self._closing = False
        self._cookies = {}
        self._login_timer = QTimer(self)
        self._login_timer.setSingleShot(True)
        self._login_timer.timeout.connect(self._finish_login)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.status = QLabel("登录成功后窗口会自动关闭")
        self.status.setObjectName("AppSubtitle")
        top.addWidget(self.status)
        top.addStretch(1)
        reload_button = QPushButton("刷新页面")
        reload_button.setObjectName("IconButton")
        reload_button.clicked.connect(self._reload)
        top.addWidget(reload_button)
        layout.addLayout(top)

        self.browser = QWebEngineView(self)
        profile = _shared_profile()
        self._store = profile.cookieStore()
        self._store.cookieAdded.connect(self._on_cookie)
        self.browser.setPage(_NoPopupPage(profile, self.browser))
        self.browser.loadFinished.connect(lambda ok: self._store.loadAllCookies())
        self._reload()
        layout.addWidget(self.browser, 1)

    def _reload(self) -> None:
        self.browser.load(QUrl("https://passport.bilibili.com/login"))

    def _on_cookie(self, cookie) -> None:
        if self._closing:
            return
        try:
            domain = cookie.domain().lstrip(".").lower()
            if domain != "bilibili.com" and not domain.endswith(".bilibili.com"):
                return
            name = bytes(cookie.name().data() if hasattr(cookie.name(), "data")
                         else cookie.name()).decode("utf-8", "ignore")
            if name not in ("SESSDATA", "bili_jct", "buvid3"):
                return
            raw = cookie.value()
            value = bytes(raw.data() if hasattr(raw, "data") else raw).decode("utf-8", "ignore")
        except Exception as error:  # noqa: BLE001
            _log(f"读取 cookie 失败: {error}")
            return
        if not value:
            return
        self._cookies[name] = value
        # Cookie 到达顺序不固定，等登录态和 CSRF 齐全，再给设备 Cookie 留出时间。
        if self._cookies.get("SESSDATA") and self._cookies.get("bili_jct"):
            self._login_timer.start(300)

    def _finish_login(self) -> None:
        if self._closing or not self._cookies.get("SESSDATA") or not self._cookies.get("bili_jct"):
            return
        self.sessdata = self._cookies["SESSDATA"]
        bili.set_login_cookies(self.sessdata, self._cookies["bili_jct"], self._cookies.get("buvid3"))
        self._closing = True
        self.status.setText("登录成功，窗口即将自动关闭…")
        self.sessionData.emit(self.sessdata)
        self.accept()

    def done(self, result: int) -> None:
        self._closing = True
        self._login_timer.stop()
        try:
            self._store.cookieAdded.disconnect(self._on_cookie)
        except RuntimeError:
            pass
        super().done(result)
