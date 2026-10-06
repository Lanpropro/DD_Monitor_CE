"""通过官网主页确认抖音主播身份，再查询最近直播的固定房间号。"""
import json
import re
import threading
import time

from PySide6.QtCore import QThread, QTimer, QUrl, Signal

from .platform_login import PlatformFollowDialog


class ProfileRoomLoader(QThread):
    loaded = Signal(str)
    failed = Signal(str)

    def __init__(self, platform, user, parent):
        super().__init__(parent)
        self.platform, self.user = platform, user
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            rid = self.platform.profile_room(self.user['uid'], self.cancelled.is_set,
                                             web_rid=self.user.get('web_rid', ''))
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
        script.setSourceCode('(%s)(%s);' % (platform.profile_browser_init_script, json.dumps(sec_uid)))
        self.browser.page().scripts().insert(script)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._poll)
        self._pending_script = False
        self._script_generation = 0
        self._deadline = time.monotonic() + 30
        self.browser.loadFinished.connect(self._page_loaded)
        self.poll.start()
        self.browser.load(QUrl(self._profile_url))

    def _read(self):
        if self._worker is not None:
            return
        self._read_cancelled = False
        self._script_generation += 1
        self._pending_script = False
        self._deadline = time.monotonic() + 30
        self.status.setText('正在重新加载主播主页并读取直播间…')
        self.poll.start()
        self.browser.load(QUrl(self._profile_url))

    def _page_loaded(self, ok):
        if self._finished_dialog or self._pending_done is not None or self._worker is not None:
            return
        if not ok:
            self.poll.stop()
            self.status.setText('主播主页加载失败，请检查网络后点击「重试读取」')
            return
        if self.browser.url().toString().split('?', 1)[0].rstrip('/') != self._profile_url:
            return
        self.browser.page().runJavaScript(
            'window.__ddmProfileCancelled = false; window.__ddmDouyinProfile?.read();')
        self._poll()

    def _poll(self):
        if (self._finished_dialog or self._pending_done is not None or self._read_cancelled
                or getattr(self._owner, '_closing', False)):
            self.poll.stop()
            return
        if self._worker is not None:
            return
        if time.monotonic() >= self._deadline:
            self.poll.stop()
            self.status.setText('主页资料尚未加载，请完成官网验证或登录后点击「重试读取」')
            return
        if self._pending_script:
            return
        self._pending_script = True
        generation = self._script_generation
        self.browser.page().runJavaScript('JSON.stringify(window.__ddmDouyinProfile?.peek())',
            lambda value: self._identity(value) if generation == self._script_generation else None)

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
        if isinstance(user, dict) and user.get('error'):
            self.poll.stop()
            self.status.setText('官网未返回主播资料，请完成页面验证或登录后点击「重试读取」')
            return
        if (not isinstance(user, dict) or user.get('sec_uid') != self.sec_uid
                or not re.fullmatch(r'[1-9][0-9]{0,19}', str(user.get('uid', '')))):
            return
        self.poll.stop()
        self.status.setText('已确认主播身份，正在查询最近直播记录…')
        self.read_button.setEnabled(False)
        worker = ProfileRoomLoader(self.platform, user, self)
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
        self._script_generation += 1
        self.browser.page().runJavaScript('window.__ddmProfileCancelled = true')
        super().done(result)
