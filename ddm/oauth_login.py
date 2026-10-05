"""复用账号菜单的海外系统浏览器授权窗口，不创建内嵌浏览器。"""
import json
import os
import threading

import requests
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                              QLabel, QLineEdit, QPushButton, QVBoxLayout)

from .account_store import AccountStore
from .oauth import authorize


class OAuthLoader(QThread):
    identity = Signal(dict, dict)
    loaded = Signal(list)
    failed = Signal(str)
    browserRequested = Signal(str, str)

    def __init__(self, platform, client, saved, parent=None, *, login_only=False):
        super().__init__(parent)
        self.platform, self.client, self.saved = platform, client, saved
        self.login_only = login_only
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            with requests.Session() as session:
                tokens = authorize(self.platform.kind, session, self.client, self.saved,
                                   self.cancelled, self.browserRequested.emit)
                if not tokens or self.cancelled.is_set():
                    return
                if self.platform.kind == 'twitch':
                    session.cookies.set('auth-token', tokens['access_token'], domain='.twitch.tv', secure=True)
                    session.ddm_oauth_client_id = self.client['client_id']
                else:
                    session.headers['Authorization'] = 'Bearer ' + tokens['access_token']
                account = self.platform.account_info(session, self.cancelled.is_set)
                if self.cancelled.is_set():
                    return
                if not isinstance(account, dict) or not account.get('uid'):
                    raise RuntimeError('未能确认平台账号，请重新授权')
                self.identity.emit(account, tokens)
                rooms = [] if self.login_only else self.platform.follow_rooms(session, self.cancelled.is_set)
            if not self.cancelled.is_set():
                self.loaded.emit(rooms)
        except Exception as error:  # noqa: BLE001
            if not self.cancelled.is_set():
                self.failed.emit(str(error) if isinstance(error, RuntimeError) else
                                 '账号授权失败，请检查网络和客户端配置后重试')


class OAuthAccountDialog(QDialog):
    accountCleared = Signal(str)
    busyChanged = Signal(bool)
    readFailed = Signal(str)

    def __init__(self, platform, parent=None, *, owner=None, login_only=False, embedded=False,
                 defer_login=False):
        super().__init__(parent)
        if embedded:
            self.setWindowFlags(Qt.Widget)
        self.platform, self._owner, self.login_only = platform, owner or parent, login_only
        self.account, self.rooms, self._auth = {}, [], {}
        self._worker, self._pending_done = None, None
        self._read_cancelled, self._interactive_read = False, True
        self._forget_after_read = False
        self.account_store = AccountStore(platform.kind)
        self.client_store = AccountStore(platform.kind + '_oauth_client')
        self.resize(620, 330)
        layout = QVBoxLayout(self)
        self.status = QLabel('使用系统浏览器完成授权，成功后自动返回软件。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        form = QFormLayout()
        self.client_id = QLineEdit()
        self.client_id.setPlaceholderText('自己的 OAuth 客户端 ID')
        form.addRow('Client ID', self.client_id)
        self.client_secret = QLineEdit()
        self.client_secret.setEchoMode(QLineEdit.Password)
        if platform.kind == 'youtube':
            form.addRow('Client Secret（可选）', self.client_secret)
            button = QPushButton('导入 Google 桌面客户端 JSON')
            button.setObjectName('IconButton')
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.clicked.connect(self._import_google_client)
            form.addRow(button)
        layout.addLayout(form)
        self.code = QLabel()
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.code)
        layout.addStretch()
        self.remember = QCheckBox('记住登录（本机加密保存）')
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        actions = QHBoxLayout()
        self.forget_button = QPushButton('退出账号')
        self.read_button = QPushButton('开始授权' if login_only else '读取关注')
        self.reauthorize_button = QPushButton('重新授权')
        cancel = QPushButton('取消')
        for button in (self.forget_button, self.reauthorize_button, self.read_button, cancel):
            button.setObjectName('IconButton')
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.forget_button.clicked.connect(self._forget)
        self.read_button.clicked.connect(self._read)
        self.reauthorize_button.clicked.connect(lambda: self._read(force=True))
        cancel.clicked.connect(self.reject)
        layout.addLayout(actions)
        try:
            client = self.client_store.load_account()
            self.client_id.setText(client.get('client_id', ''))
            self.client_secret.setText(client.get('client_secret', ''))
            memory = getattr(self._owner, '_platform_login_sessions', {}).get(platform.kind)
            if memory is not None:
                self._auth = memory.get('auth', {})
                self.remember.setChecked(memory.get('remember', True))
            elif os.environ.get('DDM_NO_SAVE') != '1':
                self._auth = self.account_store.load_auth()
        except (OSError, RuntimeError, ValueError):
            self.status.setText('保存的授权无法读取，请重新配置并授权')

    def _import_google_client(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 Google 桌面 OAuth 客户端', '', 'JSON (*.json)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8') as source:
                client = json.load(source)['installed']
            if not isinstance(client.get('client_id'), str) or not client['client_id'].endswith('.apps.googleusercontent.com'):
                raise ValueError('Invalid desktop client')
            self.client_id.setText(client['client_id'])
            self.client_secret.setText(client.get('client_secret', ''))
            self.status.setText('桌面客户端已载入，点击「开始授权」完成 Google 登录。')
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText('请选择 Google 下载的桌面应用客户端 JSON')

    def _read(self, _checked=False, *, force=False):
        if self._worker is not None:
            self.cancel_read()
            return
        client = {'client_id': self.client_id.text().strip(), 'client_secret': self.client_secret.text().strip()}
        if not client['client_id'] or (self.platform.kind == 'youtube' and
                not client['client_id'].endswith('.apps.googleusercontent.com')):
            self.status.setText('请填写自己的 Twitch 公共客户端 ID' if self.platform.kind == 'twitch' else
                                '请先导入 Google 桌面客户端 JSON 或填写客户端 ID')
            return
        try:
            if os.environ.get('DDM_NO_SAVE') != '1':
                self.client_store.save([], client)
        except (OSError, RuntimeError):
            self.status.setText('客户端配置保存失败，请检查文件权限后重试')
            return
        self._read_cancelled = False
        self.code.clear()
        self.status.setText('正在确认授权并读取账号…')
        worker = OAuthLoader(self.platform, client, {} if force else dict(self._auth),
                             self._owner or self, login_only=self.login_only)
        self._worker = worker
        if hasattr(self._owner, '_wait_background'):
            self._owner._follow_loader = worker
        worker.browserRequested.connect(self._open_browser)
        worker.identity.connect(self._identity)
        worker.loaded.connect(self._loaded)
        worker.failed.connect(self._failed)
        worker.finished.connect(lambda: self._finished(worker))
        self.read_button.setText('停止读取')
        self.reauthorize_button.setEnabled(False)
        self.client_id.setEnabled(False)
        self.client_secret.setEnabled(False)
        self.busyChanged.emit(True)
        worker.start()

    def _open_browser(self, url, code):
        if self._read_cancelled or self._pending_done is not None or getattr(self._owner, '_closing', False):
            return
        self.code.setText('授权码：' + code if code else '')
        self.status.setText('请在系统浏览器完成授权，软件正在等待结果…')
        if not QDesktopServices.openUrl(QUrl(url)):
            self._failed('无法打开系统浏览器，请检查默认浏览器设置后重试')
            self._worker.cancel()

    def _identity(self, account, tokens):
        if self._read_cancelled or self._pending_done is not None or getattr(self._owner, '_closing', False):
            return
        try:
            if os.environ.get('DDM_NO_SAVE') != '1':
                if self.remember.isChecked():
                    self.account_store.save([], account, auth=tokens)
                else:
                    self.account_store.clear()
        except (OSError, RuntimeError):
            self._failed('授权保存失败；取消「记住登录」后重试')
            self._read_cancelled = True
            self._worker.cancel()
            return
        self.account, self._auth = account, tokens
        if hasattr(self._owner, '_platform_login_sessions'):
            self._owner._platform_login_sessions[self.platform.kind] = {
                'cookies': [], 'auth': tokens, 'remember': self.remember.isChecked()}
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
            self.status.setText('正在停止授权…')

    def _finished(self, worker):
        if getattr(self._owner, '_follow_loader', None) is worker:
            self._owner._follow_loader = None
        self._worker = None
        worker.deleteLater()
        self.read_button.setText('开始授权' if self.login_only else '读取关注')
        self.reauthorize_button.setEnabled(True)
        self.client_id.setEnabled(True)
        self.client_secret.setEnabled(True)
        self.busyChanged.emit(False)
        if self._pending_done is not None:
            result, self._pending_done = self._pending_done, None
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
            self.status.setText('授权清除失败，请检查文件权限后重试')
            return
        self.account, self._auth, self.rooms = {}, {}, []
        self.accountCleared.emit(self.platform.kind)
        self.status.setText('已退出此平台账号，可以重新授权')

    def done(self, result):
        if self._worker is not None:
            self._pending_done = result
            self.cancel_read()
            return
        super().done(result)
