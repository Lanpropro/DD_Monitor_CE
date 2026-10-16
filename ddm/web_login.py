"""账号密码登录：收齐 B 站的 SESSDATA 和 bili_jct 后自动关闭。

只在用户主动选择"账号密码登录"时才导入 QtWebEngine（比较重）。
"""
import sys

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import bili

PROFILE_NAME = "ddm-login"
_profile: QWebEngineProfile | None = None


def _log(message: str) -> None:
    print(f"[网页登录] {message}", file=sys.stderr, flush=True)


def _shared_profile() -> QWebEngineProfile:
    global _profile
    if _profile is None:
        _profile = QWebEngineProfile(PROFILE_NAME)
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
        self.bili_jct = ""
        self._auth_cookies = {}
        self._closing = False

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
            if name not in ("SESSDATA", "bili_jct"):
                return
            raw = cookie.value()
            value = bytes(raw.data() if hasattr(raw, "data") else raw).decode("utf-8", "ignore")
        except Exception as error:  # noqa: BLE001
            _log(f"读取 cookie 失败: {error}")
            return
        if not value:
            return
        self._auth_cookies[name] = value
        if not all(self._auth_cookies.get(key) for key in ("SESSDATA", "bili_jct")):
            self.status.setText("正在获取完整登录状态…")
            return
        self.sessdata = self._auth_cookies["SESSDATA"]
        self.bili_jct = self._auth_cookies["bili_jct"]
        _log("已获取完整登录状态")
        bili.set_sessdata(self.sessdata)
        bili.set_bili_jct(self.bili_jct)
        self.status.setText("登录成功，窗口即将自动关闭…")
        self.sessionData.emit(self.sessdata)
        if not self._closing:
            self._closing = True
            QTimer.singleShot(400, self.accept)
