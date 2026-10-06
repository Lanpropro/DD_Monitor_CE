"""通过官网主页确认抖音主播身份，再查询最近直播的固定房间号。"""
import json
import re
import threading
import time

from PySide6.QtCore import QThread, QTimer, QUrl, Signal

from .platform_login import PlatformFollowDialog


PROFILE_SCRIPT = r"""(() => {
    const target = %s;
    const remember = user => {
        if (user && user.sec_uid === target && /^[1-9][0-9]{0,19}$/.test(String(user.uid)))
            window.__ddmProfileIdentity = {uid: String(user.uid), sec_uid: target};
    };
    const wanted = url => {
        try {
            const u = new URL(url, location.href);
            return u.origin === location.origin && u.pathname === '/aweme/v1/web/user/profile/other/'
                && u.searchParams.get('sec_user_id') === target;
        } catch (_) { return false; }
    };
    const capture = data => { if (data?.status_code === 0) remember(data.user); };
    const open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
        if (wanted(url)) this.addEventListener('load', () => {
            try { capture(this.responseType === 'json' ? this.response : JSON.parse(this.responseText)); }
            catch (_) {}
        }, {once: true});
        return open.call(this, method, url, ...args);
    };
    const fetch = window.fetch;
    window.fetch = function(input, ...args) {
        const result = fetch.call(this, input, ...args);
        if (wanted(typeof input === 'string' ? input : input?.url))
            result.then(r => r.clone().json()).then(capture).catch(() => {});
        return result;
    };
    // 官网可能直接在首屏 JSON 中提供身份，无需额外发起接口请求。
    const visit = (data, depth = 0) => {
        if (!data || typeof data !== 'object' || depth > 20) return;
        remember(data);
        Object.values(data).forEach(value => visit(value, depth + 1));
    };
    window.addEventListener('DOMContentLoaded', () => {
        for (const script of document.querySelectorAll('script[type="application/json"], script#RENDER_DATA')) {
            try { visit(JSON.parse(script.textContent)); }
            catch (_) { try { visit(JSON.parse(decodeURIComponent(script.textContent))); } catch (_) {} }
        }
    }, {once: true});
})();"""


class ProfileRoomLoader(QThread):
    loaded = Signal(str)
    failed = Signal(str)

    def __init__(self, platform, uid, parent):
        super().__init__(parent)
        self.platform, self.uid = platform, uid
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            rid = self.platform.profile_room(self.uid, self.cancelled.is_set)
            if rid and not self.cancelled.is_set():
                self.loaded.emit(rid)
        except Exception as error:  # noqa: BLE001
            if not self.cancelled.is_set():
                self.failed.emit(str(error) if isinstance(error, RuntimeError) else
                                 "主播直播间读取失败，请检查网络后重试")


class ProfileRoomDialog(PlatformFollowDialog):
    def __init__(self, platform, sec_uid, owner):
        super().__init__(platform, owner, owner=owner, login_only=True, defer_login=True)
        from PySide6.QtWebEngineCore import QWebEngineScript
        self.room_id, self.sec_uid = '', sec_uid
        self._profile_url = 'https://www.douyin.com/user/' + sec_uid
        self.setWindowTitle('读取抖音主播直播间')
        self.remember.hide()
        self.forget_button.hide()
        self.read_button.setText('重试读取')
        self.status.setText('正在读取主播主页，成功后自动添加；若官网要求验证，请在页面内完成。')
        self.status.setWordWrap(True)
        script = QWebEngineScript()
        script.setName('ddm-profile-identity')
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setSourceCode(PROFILE_SCRIPT % json.dumps(sec_uid))
        self.browser.page().scripts().insert(script)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._poll)
        self._pending_script = False
        self._deadline = time.monotonic() + 60
        self.poll.start()
        self.browser.load(QUrl(self._profile_url))

    def _read(self):
        self._read_cancelled = False
        self._deadline = time.monotonic() + 60
        self.status.setText('正在读取主播身份与最近直播记录…')
        self.poll.start()
        self._poll()

    def _poll(self):
        if (self._finished_dialog or self._pending_done is not None or self._read_cancelled
                or getattr(self._owner, '_closing', False)):
            self.poll.stop()
            return
        if self._worker is not None or self._pending_script:
            return
        if time.monotonic() >= self._deadline:
            self.poll.stop()
            self.status.setText('主页资料尚未加载，请完成官网验证或登录后点击「重试读取」')
            return
        self._pending_script = True
        self.browser.page().runJavaScript('JSON.stringify(window.__ddmProfileIdentity)', self._identity)

    def _identity(self, value):
        self._pending_script = False
        if (self._finished_dialog or self._pending_done is not None or self._read_cancelled
                or self._worker is not None or getattr(self._owner, '_closing', False)):
            return
        if self.browser.url().toString().split('?', 1)[0].rstrip('/') != self._profile_url:
            return
        try:
            user = json.loads(value) if isinstance(value, str) else value
        except ValueError:
            return
        if (not isinstance(user, dict) or user.get('sec_uid') != self.sec_uid
                or not re.fullmatch(r'[1-9][0-9]{0,19}', str(user.get('uid', '')))):
            return
        self.poll.stop()
        self.status.setText('已确认主播身份，正在查询最近直播记录…')
        self.read_button.setEnabled(False)
        worker = ProfileRoomLoader(self.platform, user['uid'], self)
        self._worker = worker
        worker.loaded.connect(self._resolved)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda: self._finished(worker))
        worker.start()

    def _resolved(self, rid):
        if (not self._read_cancelled and self._pending_done is None
                and not getattr(self._owner, '_closing', False)):
            self.room_id = rid
            self.accept()

    def _finished(self, worker):
        super()._finished(worker)
        self.read_button.setText('重试读取')

    def done(self, result):
        self.poll.stop()
        super().done(result)
