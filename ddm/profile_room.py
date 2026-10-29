"""通过官网主页或直播间验证页面确认抖音主播身份和固定房间号。"""
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
            from_page = getattr(self.platform, 'profile_room_from_page', None)
            if callable(from_page):
                rid = from_page(self.user, self.cancelled.is_set)
            else:
                rid = self.platform.profile_room(self.user['uid'], self.cancelled.is_set,
                                                 web_rid=self.user.get('web_rid', ''))
            if rid and not self.cancelled.is_set():
                self.loaded.emit(rid)
        except Exception as error:  # noqa: BLE001
            if not self.cancelled.is_set():
                self.failed.emit(str(error) if isinstance(error, RuntimeError) else
                                 "主播直播间读取失败，请检查网络后重试")


class ProfileRoomDialog(PlatformFollowDialog):
    def __init__(self, platform, sec_uid, owner, *, room_id=""):
        super().__init__(platform, owner, owner=owner, login_only=True, defer_login=True)
        from PySide6.QtWebEngineCore import QWebEngineScript
        self.room_id, self.sec_uid = '', sec_uid
        self._verification_room = platform.normalize(room_id) if room_id else ''
        self._room_page_loaded = False
        self._profile_url = (platform.room_url(self._verification_room) if room_id else
                             'https://www.douyin.com/user/' + sec_uid)
        self.setWindowTitle('读取抖音主播直播间')
        self.remember.hide()
        self.forget_button.hide()
        self.read_button.setText('重试读取')
        self.status.setText('正在读取主播主页，成功后自动添加；若官网要求验证，请在页面内完成。')
        self.status.setWordWrap(True)
        if room_id:
            self.setWindowTitle('读取抖音直播间')
            self.status.setText('正在打开官网并读取房间资料；若出现验证，请在页面内完成。')
        script = QWebEngineScript()
        script.setName('ddm-profile-identity')
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        source = platform.room_browser_init_script if room_id else platform.profile_browser_init_script
        target = self._verification_room.split(':', 1)[1] if room_id else sec_uid
        script.setSourceCode('(%s)(%s);' % (source, json.dumps(target)))
        self.browser.page().scripts().insert(script)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self._poll)
        self._pending_script = False
        self._script_generation = 0
        self._deadline = time.monotonic() + (300 if self._verification_room else 30)
        self.browser.loadFinished.connect(self._page_loaded)
        self.poll.start()
        self.browser.load(QUrl(self._profile_url))

    def _read(self):
        if self._worker is not None:
            return
        self._read_cancelled = False
        self._script_generation += 1
        self._pending_script = False
        self._room_page_loaded = False
        self._deadline = time.monotonic() + (300 if self._verification_room else 30)
        self.status.setText('正在重新加载官网页面并读取直播间…')
        self.poll.start()
        self.browser.load(QUrl(self._profile_url))

    def _page_loaded(self, ok):
        if self._finished_dialog or self._pending_done is not None or self._worker is not None:
            return
        if not ok:
            self.poll.stop()
            self.status.setText('官网页面加载失败，请检查网络后点击「重试读取」')
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
            self.status.setText('官网已加载，但未识别房间资料，请重试读取或使用个人主页链接添加' if self._room_page_loaded else
                                '官网资料尚未加载，请完成官网验证或登录后点击「重试读取」')
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
        if self._verification_room and isinstance(user, dict) and user.get('page_state'):
            self._room_page_loaded = user['page_state'] == 'room_loaded'
            self.status.setText('官网直播间已加载，正在读取房间资料，无需寻找验证码。' if self._room_page_loaded else
                                '官网正在进行访问验证；若出现验证码，请在页面内完成。')
            return
        if isinstance(user, dict) and user.get('error'):
            self.poll.stop()
            self.status.setText('官网未返回主播资料，请完成页面验证或登录后点击「重试读取」')
            return
        if not isinstance(user, dict) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(user.get('uid', ''))):
            return
        if self._verification_room:
            if user.get('web_rid') != self._verification_room.split(':', 1)[1]:
                return
        elif user.get('sec_uid') != self.sec_uid:
            return
        self.poll.stop()
        self.status.setText('已确认房间资料，正在添加…' if self._verification_room else
                            '已确认主播身份，正在查询最近直播记录…')
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
