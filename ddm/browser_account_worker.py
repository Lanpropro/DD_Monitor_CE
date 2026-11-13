"""Cancellable website login and read-only follow loading; no UI or credential persistence."""
import threading
import time

import requests
from PySide6.QtCore import QByteArray, QDateTime, QThread, Signal
from PySide6.QtNetwork import QNetworkCookie

from .account_browser import AccountBrowser
from .plugins import LoginRequiredError


def cookie_jar(records, domains):
    jar = requests.cookies.RequestsCookieJar()
    for raw in records:
        for cookie in QNetworkCookie.parseCookies(QByteArray(raw.encode('utf-8'))):
            domain = cookie.domain().lstrip('.').lower()
            if not any(domain == allowed or domain.endswith('.' + allowed) for allowed in domains):
                continue
            expires = cookie.expirationDate()
            if expires.isValid() and expires.toSecsSinceEpoch() <= time.time():
                continue
            jar.set(bytes(cookie.name()).decode(), bytes(cookie.value()).decode(), domain=cookie.domain(),
                    path=cookie.path() or '/', secure=cookie.isSecure())
    return jar


def cookie_records(cookies):
    records = []
    for item in cookies:
        cookie = QNetworkCookie(item['name'].encode(), item['value'].encode())
        cookie.setDomain(item['domain'])
        cookie.setPath(item.get('path', '/'))
        cookie.setSecure(item.get('secure', False))
        cookie.setHttpOnly(item.get('httpOnly', False))
        if item.get('expires', -1) > 0:
            cookie.setExpirationDate(QDateTime.fromSecsSinceEpoch(int(item['expires'])))
        records.append(bytes(cookie.toRawForm()).decode())
    return records


class BrowserAccountLoader(QThread):
    identity = Signal(dict, list)
    loaded = Signal(list)
    failed = Signal(str)
    status = Signal(str)

    def __init__(self, platform, saved, parent=None, *, login_only=False):
        super().__init__(parent)
        self.platform, self.saved, self.login_only = platform, list(saved), login_only
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            platform = self.platform
            with requests.Session() as session:
                records = self.saved
                session.cookies = cookie_jar(records, platform.browser_cookie_domains)
                session.ddm_follow_progress = lambda count: self.status.emit(f'已读取 {count} 个关注频道…')
                account = None
                if records and not self.cancelled.is_set():
                    self.status.emit('正在确认保存的登录状态…')
                    try:
                        account = platform.browser_account_info(session, self.cancelled.is_set)
                    except LoginRequiredError:
                        pass  # Only rejected credentials open login; network failures preserve the session.
                if account is None and not self.cancelled.is_set():
                    self.status.emit('请在独立浏览器窗口登录，完成后关闭该窗口，软件将读取账号与关注…')
                    with AccountBrowser(platform.browser_login_url, platform.browser_cookie_domains,
                                        self.cancelled) as browser:
                        deadline = time.monotonic() + 300
                        while not self.cancelled.wait(.5):
                            cookies = browser.cookies()
                            keys = {item['name'] for item in cookies}
                            ready = ('auth-token' in keys if platform.kind == 'twitch' else
                                     'LOGIN_INFO' in keys and bool(keys & {'SAPISID', '__Secure-3PAPISID'}))
                            if ready:
                                records = cookie_records(cookies)
                                session.cookies = cookie_jar(records, platform.browser_cookie_domains)
                                try:
                                    account = platform.browser_account_info(session, self.cancelled.is_set)
                                    break
                                except LoginRequiredError:
                                    raise LoginRequiredError('网页登录身份未确认，请重新打开窗口并完成登录，或使用 OAuth 授权') from None
                            elif browser.login_closed:
                                raise LoginRequiredError('窗口已关闭，但未读取到完整登录状态，请重新打开并完成登录')
                            if time.monotonic() >= deadline:
                                raise RuntimeError('网页登录等待超时，请重新打开登录窗口')
                if self.cancelled.is_set():
                    return
                if not isinstance(account, dict) or not account.get('uid'):
                    raise RuntimeError('未能确认平台账号，请重新登录')
                self.identity.emit(account, records)
                self.status.emit('已确认账号，正在读取关注列表…')
                rooms = [] if self.login_only else platform.browser_follow_rooms(session, self.cancelled.is_set)
            if not self.cancelled.is_set():
                self.loaded.emit(rooms)
        except Exception as error:  # noqa: BLE001
            if not self.cancelled.is_set():
                self.failed.emit(str(error) if isinstance(error, RuntimeError) else
                                 '网页登录或关注读取失败，请检查代理和网络后重试')
