"""Bilibili QR generation, poll protocol and cancellable login worker."""
import sys
import threading
import time
import requests
from PySide6.QtCore import QThread, Signal
from . import bili


GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"


POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


QR_SUCCESS = 0


QR_EXPIRED = 86038


QR_SCANNED = 86090


QR_WAITING = 86101


def _log(message: str) -> None:
    print(f"[登录] {message}", file=sys.stderr, flush=True)


def _login_cookie(name: str, *jars) -> str:
    """优先本次响应，处理同名多作用域 Cookie，只接收 B 站根域凭证。"""
    for jar in jars:
        matches = [cookie for cookie in jar if cookie.name == name and cookie.value
                   and cookie.domain.lstrip(".").lower() == "bilibili.com" and cookie.path == "/"]
        if matches:
            return str(matches[-1].value)
    return ""


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
        self.bili_jct = ""
        self.buvid3 = ""

    def cancel(self) -> None:
        self._cancelled = True
        self._cancel_event.set()

    def run(self) -> None:
        session = requests.Session()
        session.headers.update(bili.HEADERS)
        if bili.BUVID3:
            session.cookies.set("buvid3", bili.BUVID3, domain=".bilibili.com")
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
                sessdata = _login_cookie("SESSDATA", poll.cookies, session.cookies)
                if not sessdata:
                    self.failed.emit("登录成功但没拿到 SESSDATA")
                    return
                _log(f"扫码登录成功（SESSDATA {len(sessdata)} 字符）")
                self.sessdata = sessdata
                self.bili_jct = _login_cookie("bili_jct", poll.cookies, session.cookies)
                self.buvid3 = _login_cookie("buvid3", poll.cookies, session.cookies)
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
