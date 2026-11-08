"""平台关注导入：官方网页登录、隔离 Cookie 和可取消的后台分页。"""
import os
import json
import threading
import time

import requests
from PySide6.QtCore import QByteArray, QThread, QTimer, QUrl, Qt, Signal
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel,
                              QPushButton, QVBoxLayout)

from .account_store import AccountStore

from .platform_profiles import (_profiles, clear_platform_login)


from .platform_follow_worker import (PlatformFollowLoader)


class PlatformFollowDialog(QDialog):
    accountCleared = Signal(str)
    busyChanged = Signal(bool)
    readFailed = Signal(str)

    def __init__(self, platform, parent=None, *, login_only=False, embedded=False, owner=None,
                 defer_login=False):
        super().__init__(parent)
        if embedded:
            # 在浏览器创建前设为子控件，避免图形控件随独立窗口迁移。
            self.setWindowFlags(Qt.Widget)
        self._owner = owner if owner is not None else parent
        self._embedded = embedded
        # 只有用户主动导入时才加载浏览器，启动和播放不加载 WebEngine。
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.platform = platform
        self.login_only = login_only
        self.account = {}
        self.rooms = []
        self._cookies = {}
        self._worker = None
        self._read_cancelled = False
        self._forget_after_read = False
        self._interactive_read = not login_only and bool(getattr(platform, "follow_browser_init_script", ""))
        self._pending_done = None
        self._finished_dialog = False
        self._saved_cookies = []
        self._login_url = (platform.follow_login_url if not login_only and
                           getattr(platform, "follow_browser_url", "") else
                           getattr(platform, "account_login_url", "") or platform.follow_login_url)
        self.account_store = AccountStore(platform.kind)
        self.setWindowTitle(f"{platform.label} · " + ("登录" if login_only else "登录并导入关注"))
        size = (720, 540) if getattr(platform, "account_login_url", "") else (1000, 700)
        self.resize(*size)
        layout = QVBoxLayout(self)
        self.status = QLabel("请在官方页面完成登录，然后点击「确认登录」" if login_only else
                             "请在官方页面完成登录，然后点击「读取关注」")
        layout.addWidget(self.status)
        toolbar = QHBoxLayout()
        self.remember = QCheckBox("记住登录（本机加密保存）")
        self.remember.setChecked(True)
        toolbar.addWidget(self.remember)
        toolbar.addStretch(1)
        self.forget_button = QPushButton("退出账号")
        self.forget_button.setObjectName("IconButton")
        self.forget_button.clicked.connect(self._forget)
        toolbar.addWidget(self.forget_button)
        self.read_button = QPushButton("确认登录" if login_only else "读取关注")
        self.read_button.setObjectName("PrimaryButton")
        self.read_button.clicked.connect(self._read)
        toolbar.addWidget(self.read_button)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        toolbar.addWidget(cancel)
        layout.addLayout(toolbar)
        self.browser = QWebEngineView(self)
        profile = _profiles.get(platform.kind)
        if profile is None:
            profile = QWebEngineProfile(QApplication.instance())  # off-the-record
            profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
            _profiles[platform.kind] = profile
        self._profile = profile
        self._store = profile.cookieStore()
        self._store.cookieAdded.connect(self._on_cookie)
        self._store.cookieRemoved.connect(self._on_cookie_removed)
        self.browser.setPage(QWebEnginePage(profile, self.browser))
        if getattr(platform, "follow_browser_init_script", ""):
            script = QWebEngineScript()
            script.setName("ddm-follow-list")
            script.setInjectionPoint(QWebEngineScript.DocumentCreation)
            script.setWorldId(QWebEngineScript.MainWorld)
            script.setRunsOnSubFrames(False)
            script.setSourceCode(platform.follow_browser_init_script)
            self.browser.page().scripts().insert(script)
        if platform.kind == "douyin":
            self.browser.page().settings().setUnknownUrlSchemePolicy(QWebEngineSettings.DisallowUnknownUrlSchemes)
        self.browser.setZoomFactor(.8)
        layout.addWidget(self.browser, 1)
        try:
            session = getattr(self._owner, "_platform_login_sessions", {}).get(platform.kind)
            if session is not None:
                saved = session["cookies"]
                self.remember.setChecked(session["remember"])
            else:
                saved = self.account_store.load() if os.environ.get("DDM_NO_SAVE") != "1" else []
            for raw in saved:
                for cookie in QNetworkCookie.parseCookies(QByteArray(raw.encode("utf-8"))):
                    if self._valid_cookie(cookie):
                        self._on_cookie(cookie)
                        origin = QUrl("https://" + cookie.domain().lstrip(".") + "/")
                        self._store.setCookie(cookie, origin)
        except (OSError, RuntimeError, ValueError):
            self.status.setText("保存的登录状态无法读取，请在官方页面重新登录")
        self._store.loadAllCookies()
        if not defer_login:
            self.browser.load(QUrl(self._login_url))

    def _valid_cookie(self, cookie):
        domain = cookie.domain().lstrip(".").lower()
        root = getattr(self.platform, "account_cookie_domain", "") or self.platform.follow_cookie_domain
        return domain == root or domain.endswith("." + root)

    def _on_cookie(self, cookie):
        if self._valid_cookie(cookie):
            key = (bytes(cookie.name()), cookie.domain(), cookie.path())
            self._cookies[key] = cookie

    def _on_cookie_removed(self, cookie):
        self._cookies.pop((bytes(cookie.name()), cookie.domain(), cookie.path()), None)

    def _read(self):
        if self._worker is not None:
            if self._interactive_read:
                self.cancel_read()
            return
        self._read_cancelled = False
        jar = requests.cookies.RequestsCookieJar()
        for cookie in self._cookies.values():
            if cookie.expirationDate().isValid() and cookie.expirationDate().toSecsSinceEpoch() <= \
                    time.time():
                continue
            jar.set(bytes(cookie.name()).decode("utf-8"), bytes(cookie.value()).decode("utf-8"),
                    domain=cookie.domain(), path=cookie.path() or "/", secure=cookie.isSecure())
        self._saved_cookies = [bytes(cookie.toRawForm()).decode("utf-8")
                               for cookie in self._cookies.values()]
        self.status.setText("正在确认账号信息…" if self.login_only else "正在后台读取关注，完成后可勾选导入…")
        self.read_button.setEnabled(self._interactive_read)
        self.forget_button.setEnabled(self._interactive_read)
        if self._interactive_read:
            self.read_button.setText("停止读取")
        owner = self._owner
        worker = PlatformFollowLoader(self.platform, jar, owner or self, login_only=self.login_only)
        self._worker = worker
        self.busyChanged.emit(True)
        if owner is not None and hasattr(owner, "_wait_background"):
            owner._follow_loader = worker
        worker.loaded.connect(self._loaded)
        worker.accountLoaded.connect(self._account_loaded)
        worker.failed.connect(self._failed)
        worker.browserRequested.connect(self._browser_request)
        worker.finished.connect(lambda w=worker: self._finished(w))
        worker.start()

    def cancel_read(self):
        if self._worker is not None:
            self._read_cancelled = True
            self.browser.page().runJavaScript("window.__ddmFollowCancelled = true; "
                "window.__ddmFollowGeneration = (window.__ddmFollowGeneration || 0) + 1")
            self._worker.cancel()
            self.status.setText("正在停止读取…")

    def _browser_request(self, url, request):
        if request["done"].is_set():
            return
        page = self.browser.page()
        target = QUrl(self.platform.follow_login_url)
        if self.browser.url().host() != target.host():
            def ready(ok):
                self.browser.loadFinished.disconnect(ready)
                if ok:
                    self._browser_request(url, request)
                else:
                    request["result"] = {"error": "page load failed"}
                    request["done"].set()
            self.browser.loadFinished.connect(ready)
            self.browser.load(target)
            return
        # 使用官网请求客户端；不会导出浏览器存储或登录令牌。
        script = getattr(self.platform, "follow_browser_script", "")
        if script:
            page.runJavaScript("""window.__ddmFollowResult = null; window.__ddmFollowCancelled = false;
                window.__ddmFollowGeneration = (window.__ddmFollowGeneration || 0) + 1;
                (() => { const generation = window.__ddmFollowGeneration;
                Promise.resolve().then(() => (%s)(%s))
                    .then(data => { if (generation === window.__ddmFollowGeneration)
                        window.__ddmFollowResult = {status: 200, text: JSON.stringify(data)}; })
                    .catch(error => { if (generation === window.__ddmFollowGeneration) window.__ddmFollowResult = {error:
                        ['follow_panel_not_found', 'follow_page_timeout', 'follow_panel_wrong_list'].includes(error.message)
                            ? error.message : 'request failed'}; });
                })();
                """ % (script, json.dumps(url)))
        else:
            page.runJavaScript("""window.__ddmFollowResult = null;
            (() => { const xhr = new XMLHttpRequest();
                xhr.open('GET', %s, true); xhr.withCredentials = true; xhr.timeout = 12000;
                xhr.onload = () => { window.__ddmFollowResult = {status: xhr.status, text: xhr.responseText}; };
                xhr.onerror = xhr.ontimeout = () => { window.__ddmFollowResult = {error: 'request failed'}; };
                xhr.send(); })();""" % json.dumps(url))
        def poll():
            if request["done"].is_set():
                return
            def received(result):
                if request["done"].is_set():
                    return
                if isinstance(result, str) and result not in ("", "null"):
                    result = json.loads(result)
                if isinstance(result, dict):
                    request["result"] = result
                    request["done"].set()
                else:
                    QTimer.singleShot(100, poll)
            page.runJavaScript("JSON.stringify(window.__ddmFollowResult)", received)
        QTimer.singleShot(100, poll)

    def _account_loaded(self, account):
        if not self._read_cancelled and self._pending_done is None and not getattr(self._owner, "_closing", False):
            self.account = account

    def _loaded(self, rooms):
        if self._read_cancelled or self._pending_done is not None or getattr(self._owner, "_closing", False):
            return
        if os.environ.get("DDM_NO_SAVE") != "1":
            try:
                if self.remember.isChecked():
                    self.account_store.save(self._saved_cookies, self.account)
                else:
                    self.account_store.clear()
                    if self.platform.kind == "douyin":
                        AccountStore("douyin_follows").clear()
            except (OSError, RuntimeError):
                self._failed("登录状态保存失败；取消「记住登录」后重试")
                return
        if self._owner is not None and hasattr(self._owner, "_platform_login_sessions"):
            self._owner._platform_login_sessions[self.platform.kind] = {
                "cookies": list(self._saved_cookies), "remember": self.remember.isChecked()}
        self.rooms = rooms
        self.accept()

    def _failed(self, reason):
        if not self._read_cancelled and self._pending_done is None:
            self.status.setText(reason)
            self.readFailed.emit(reason)

    def _finished(self, worker):
        owner = self._owner
        if getattr(owner, "_follow_loader", None) is worker:
            owner._follow_loader = None
        if self._worker is worker:
            self._worker = None
        worker.deleteLater()
        self.read_button.setEnabled(True)
        self.read_button.setText("确认登录" if self.login_only else "读取关注")
        self.forget_button.setEnabled(True)
        if self._read_cancelled:
            self.status.setText("读取已停止，可以重试或切换平台")
        self.busyChanged.emit(False)
        if self._pending_done is not None:
            result = self._pending_done
            self._pending_done = None
            self.done(result)
        elif self._forget_after_read:
            self._forget_after_read = False
            self._forget()

    def _forget(self):
        if self._worker is not None:
            self._forget_after_read = True
            self.cancel_read()
            return
        try:
            self.account_store.clear()
        except OSError:
            self.status.setText("登录状态清除失败，请检查文件权限后重试")
            return
        self._cookies.clear()
        self.account = {}
        if self._owner is not None and hasattr(self._owner, "_platform_login_sessions"):
            self._owner._platform_login_sessions.pop(self.platform.kind, None)
        self._store.deleteAllCookies()
        self._profile.clearHttpCache()
        self.accountCleared.emit(self.platform.kind)
        self.browser.load(QUrl(self._login_url))
        self.status.setText("已清除本机登录状态，请在官方页面重新登录")

    def done(self, result):
        if self._finished_dialog:
            super().done(result)
            return
        if self._worker is not None:
            self._pending_done = result
            self.cancel_read()
            self.status.setText("正在结束当前请求…")
            return
        if self._embedded:
            self.browser.stop()
            self.setResult(result)
            self.finished.emit(result)
            return
        self._store.cookieAdded.disconnect(self._on_cookie)
        self._store.cookieRemoved.disconnect(self._on_cookie_removed)
        self._finished_dialog = True
        self.browser.stop()
        super().done(result)
