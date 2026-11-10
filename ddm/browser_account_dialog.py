"""Minimal website login entry, with the existing OAuth flow available as an alternative."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .account_store import AccountStore
from .browser_account_worker import BrowserAccountLoader


def prefer_browser_login(platform, owner):
    if not getattr(platform, 'browser_login_url', ''):
        return False
    memory = getattr(owner, '_platform_login_sessions', {}).get(platform.kind)
    if memory is not None:
        return not bool(memory.get('auth', {}).get('access_token'))
    if platform.kind in getattr(owner, '_accounts', {}) and os.environ.get('DDM_NO_SAVE') != '1':
        try:
            return not bool(AccountStore(platform.kind).load_auth().get('access_token'))
        except (OSError, RuntimeError, ValueError):
            pass
    if getattr(platform, 'oauth_provider', '') and os.environ.get('DDM_NO_SAVE') != '1':
        try:
            client = AccountStore(platform.kind + '_oauth_client').load_account()
            if client.get('client_id'):
                return False
        except (OSError, RuntimeError, ValueError):
            pass
    return True


class BrowserAccountDialog(QDialog):
    accountCleared = Signal(str)
    busyChanged = Signal(bool)
    readFailed = Signal(str)

    def __init__(self, platform, parent=None, *, owner=None, login_only=False, embedded=False,
                 defer_login=False):
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.platform, self._owner, self.login_only = platform, owner or parent, login_only
        self.account, self.rooms, self._cookies = {}, [], []
        self._worker, self._pending_done = None, None
        self._interactive_read, self._read_cancelled = True, False
        self.account_store = AccountStore(platform.kind)
        self.resize(620, 300)
        layout = QVBoxLayout(self)
        self.status = QLabel('无需注册开发者账号。点击下方按钮，在独立官方浏览器窗口完成登录。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = QLabel('支持 Chrome / Edge。完成登录后关闭独立窗口，软件将读取关注。已开启内置代理时沿用该代理。')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self.remember = QCheckBox('记住登录（本机加密保存）')
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        actions = QHBoxLayout()
        self.read_button = QPushButton('打开网页登录' if login_only else '登录并读取关注')
        self.forget_button = QPushButton('退出账号')
        self.oauth_button = QPushButton('OAuth 授权（高级）')
        cancel = QPushButton('取消')
        for button in (self.read_button, self.forget_button, self.oauth_button, cancel):
            button.setObjectName('IconButton')
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.read_button.clicked.connect(self._read)
        self.forget_button.clicked.connect(self._forget)
        self.oauth_button.clicked.connect(self._oauth)
        cancel.clicked.connect(self.reject)
        try:
            memory = getattr(self._owner, '_platform_login_sessions', {}).get(platform.kind)
            if memory is not None:
                self._cookies = list(memory.get('cookies', []))
                self.remember.setChecked(memory.get('remember', True))
            elif os.environ.get('DDM_NO_SAVE') != '1':
                self._cookies = self.account_store.load()
        except (OSError, ValueError, RuntimeError):
            self.status.setText('保存的登录无法读取，请重新打开网页登录')

    def _read(self, _checked=False):
        if self._worker is not None:
            self.cancel_read()
            return
        self._read_cancelled = False
        worker = BrowserAccountLoader(self.platform, self._cookies, self._owner or self,
                                      login_only=self.login_only)
        self._worker = worker
        if hasattr(self._owner, '_wait_background'):
            self._owner._follow_loader = worker
        worker.status.connect(self._status)
        worker.identity.connect(self._identity)
        worker.loaded.connect(self._loaded)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda: self._finished(worker))
        self.read_button.setText('停止读取')
        self.oauth_button.setEnabled(False)
        self.forget_button.setEnabled(False)
        self.remember.setEnabled(False)
        self.busyChanged.emit(True)
        worker.start()

    def _status(self, text):
        if not self._read_cancelled and self._pending_done is None:
            self.status.setText(text)

    def _identity(self, account, cookies):
        if self._read_cancelled or self._pending_done is not None or getattr(self._owner, '_closing', False):
            return
        try:
            if os.environ.get('DDM_NO_SAVE') != '1':
                if self.remember.isChecked():
                    self.account_store.save(cookies, account)
                else:
                    self.account_store.clear()
        except (OSError, RuntimeError):
            self._failed('登录保存失败，取消「记住登录」后重试')
            self.cancel_read()
            return
        self.account, self._cookies = account, list(cookies)
        if hasattr(self._owner, '_platform_login_sessions'):
            self._owner._platform_login_sessions[self.platform.kind] = {
                'cookies': list(cookies), 'remember': self.remember.isChecked()}
            self._owner._accounts[self.platform.kind] = dict(account)
            self._owner._render_account()

    def _loaded(self, rooms):
        if not self._read_cancelled and self._pending_done is None and not getattr(self._owner, '_closing', False):
            self.rooms = rooms
            self.accept()

    def _failed(self, reason):
        if not self._read_cancelled and self._pending_done is None:
            self.status.setText(reason)
            self.readFailed.emit(reason)

    def cancel_read(self):
        if self._worker is not None:
            self._read_cancelled = True
            self._worker.cancel()
            self.status.setText('正在停止读取并关闭本次登录窗口…')

    def _finished(self, worker):
        if getattr(self._owner, '_follow_loader', None) is worker:
            self._owner._follow_loader = None
        self._worker = None
        worker.deleteLater()
        self.read_button.setText('打开网页登录' if self.login_only else '登录并读取关注')
        self.oauth_button.setEnabled(True)
        self.forget_button.setEnabled(True)
        self.remember.setEnabled(True)
        self.busyChanged.emit(False)
        if self._pending_done is not None:
            result, self._pending_done = self._pending_done, None
            self.done(result)

    def _forget(self):
        try:
            if os.environ.get('DDM_NO_SAVE') != '1':
                self.account_store.clear()
        except OSError:
            self.status.setText('登录状态清除失败，请重试')
            return
        self.account, self.rooms, self._cookies = {}, [], []
        if hasattr(self._owner, '_platform_login_sessions'):
            self._owner._platform_login_sessions.pop(self.platform.kind, None)
            self._owner._accounts.pop(self.platform.kind, None)
            self._owner._render_account()
        self.accountCleared.emit(self.platform.kind)
        self.status.setText('已退出此平台账号，可以重新登录')

    def _oauth(self):
        from .oauth_login import OAuthAccountDialog
        page = OAuthAccountDialog(self.platform, self, owner=self._owner, login_only=self.login_only)
        page.accountCleared.connect(self.accountCleared)
        if page.exec() == QDialog.Accepted:
            self.account, self.rooms = page.account, page.rooms
            self.accept()
        page.deleteLater()

    def done(self, result):
        if self._worker is not None:
            self._pending_done = result
            self.cancel_read()
            return
        super().done(result)
