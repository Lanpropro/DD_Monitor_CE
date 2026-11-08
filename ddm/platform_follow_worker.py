"""Cancellable platform follow reader with browser request handoff."""
import threading
import time
import requests
from PySide6.QtCore import QThread, Signal


class PlatformFollowLoader(QThread):
    loaded = Signal(list)
    accountLoaded = Signal(dict)
    failed = Signal(str)
    browserRequested = Signal(str, object)

    def __init__(self, platform, cookies, parent=None, *, login_only=False):
        super().__init__(parent)
        self.platform = platform
        self.cookies = cookies.copy()
        self.login_only = login_only
        self._cancelled = threading.Event()

    def _browser_get(self, url, **kwargs):
        request = {"done": threading.Event(), "result": None}
        prepared = requests.Request("GET", url, params=kwargs.get("params")).prepare()
        self.browserRequested.emit(prepared.url, request)
        deadline = time.monotonic() + 60
        while not request["done"].wait(.1):
            if self._cancelled.is_set() or time.monotonic() > deadline:
                request["done"].set()
                raise RuntimeError("抖音关注读取已取消或超时，请稍后重试")
        result = request["result"]
        if isinstance(result, dict) and result.get("error") == "follow_panel_not_found":
            raise RuntimeError("请在官网个人页点开数字旁的「关注」列表，再点击「读取关注」")
        if isinstance(result, dict) and result.get("error") == "follow_page_timeout":
            raise RuntimeError("官网关注列表没有加载完成，请完成页面验证后重试")
        if isinstance(result, dict) and result.get("error") == "follow_panel_wrong_list":
            raise RuntimeError("请切换到当前账号的「关注」列表，并清空列表搜索后重试")
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError("抖音关注读取失败，请在官方页面完成登录或验证后重试")
        response = requests.Response()
        response.status_code = result["status"]
        response._content = result["text"].encode("utf-8")
        response.encoding = "utf-8"
        return response

    def cancel(self):
        self._cancelled.set()

    def run(self):
        try:
            with requests.Session() as session:
                session.cookies.update(self.cookies)
                if getattr(self.platform, "follow_browser_url", ""):
                    get = session.get
                    browser_urls = self.platform.follow_browser_url
                    if isinstance(browser_urls, str):
                        browser_urls = (browser_urls,)
                    session.get = lambda url, **kwargs: (self._browser_get(url, **kwargs)
                        if url in browser_urls else get(url, **kwargs))
                if callable(getattr(self.platform, "account_info", None)):
                    account = self.platform.account_info(session, self._cancelled.is_set)
                    if not self._cancelled.is_set() and (not isinstance(account, dict) or not account.get("uid")):
                        raise RuntimeError("未能确认平台账号，请完成登录后重试")
                    if not self._cancelled.is_set():
                        self.accountLoaded.emit(account)
                elif self.login_only:
                    raise RuntimeError("此平台尚未支持账号登录")
                read_follows = getattr(self.platform, "follow_accounts", None) or self.platform.follow_rooms
                rooms = [] if self.login_only else read_follows(session, self._cancelled.is_set)
            if not self._cancelled.is_set():
                self.loaded.emit(rooms)
        except Exception as error:  # noqa: BLE001
            if not self._cancelled.is_set():
                self.failed.emit(str(error) if isinstance(error, RuntimeError) else
                                 "关注获取失败，请检查登录状态和网络后重试")
