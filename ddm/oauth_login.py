"""复用账号菜单的海外系统浏览器授权窗口，不创建内嵌浏览器。"""
import json
import os
import threading

import requests
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout,
                              QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                              QScrollArea, QVBoxLayout, QWidget)

from . import theme
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
        self._authorization_url, self._user_code = '', ''
        self.account_store = AccountStore(platform.kind)
        self.client_store = AccountStore(platform.kind + '_oauth_client')
        self.resize(700, 510)
        action_label = '开始授权' if login_only else '读取关注'
        layout = QVBoxLayout(self)
        self.status = QLabel('使用系统浏览器完成授权，成功后自动返回软件。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.setup_button = QPushButton('首次配置与步骤说明')
        self.setup_button.setObjectName('IconButton')
        self.setup_button.setCursor(Qt.PointingHandCursor)
        self.setup_button.setAutoDefault(False)
        self.setup_button.setCheckable(True)
        layout.addWidget(self.setup_button)
        self.setup = QScrollArea()
        self.setup.setWidgetResizable(True)
        self.setup.setFrameShape(QFrame.NoFrame)
        self.setup.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        setup_layout = QVBoxLayout(content)
        setup_layout.setContentsMargins(0, 0, 8, 0)
        hint = QLabel(f'首次配置只需完成一次，之后点击「{action_label}」即可授权。')
        hint.setWordWrap(True)
        setup_layout.addWidget(hint)
        if platform.kind == 'twitch':
            steps = (
                ('https://dev.twitch.tv/console/apps', '打开开发者控制台',
                 '登录 Twitch，账号须验证邮箱并开启两步验证。点击「Register Your Application」。'),
                ('https://dev.twitch.tv/docs/authentication/register-app/', '查看注册说明',
                 '填写唯一应用名称、类别和回调地址 http://localhost:3000（点击 Add）；'
                 'Client Type 选择 Public／公共客户端，再创建应用。'),
                ('https://dev.twitch.tv/console/apps', '打开应用管理',
                 '点击 Manage，复制 Client ID 到下方输入框。它是应用编号，不是用户 ID，无需 Client Secret。'),
            )
            primary_url, primary_text = steps[0][0], '打开 Twitch 开发者控制台'
            last_step = f'4. 点击下方「{action_label}」，在浏览器登录并允许读取关注；成功后软件自动确认账号。'
        else:
            steps = (
                ('https://console.cloud.google.com/', '打开 Google Cloud',
                 '登录 Google，创建或选择一个项目。后续页面均使用同一项目。'),
                ('https://console.cloud.google.com/apis/library/youtube.googleapis.com', '启用 YouTube Data API v3',
                 '点击「启用」，用于读取订阅频道。'),
                ('https://console.cloud.google.com/auth/audience', '配置授权受众',
                 '首次进入 Google Auth Platform 时填写应用名称和联系邮箱；个人账号选择 External。'
                 '在测试用户中添加自己的 Google 邮箱。'),
                ('https://console.cloud.google.com/auth/clients', '创建桌面客户端',
                 '创建 OAuth 客户端，应用类型选择「桌面应用／Desktop app」，下载 JSON 文件。'),
            )
            primary_url, primary_text = steps[0][0], '打开 Google Cloud 控制台'
            last_step = f'5. 用下方按钮导入 JSON，再点击「{action_label}」，在浏览器登录并允许读取订阅。'
        self.setup_links = []
        for number, (url, title, description) in enumerate(steps, 1):
            label = QLabel(f'{number}. <a href="{url}" style="color:{theme.ACCENT}">{title}</a><br>{description}')
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            label.linkActivated.connect(self._open_link)
            setup_layout.addWidget(label)
            self.setup_links.append(label)
        last = QLabel(last_step)
        last.setWordWrap(True)
        setup_layout.addWidget(last)
        self.setup_page_button = QPushButton(primary_text)
        self.setup_page_button.setObjectName('IconButton')
        self.setup_page_button.setCursor(Qt.PointingHandCursor)
        self.setup_page_button.setAutoDefault(False)
        self.setup_page_button.clicked.connect(lambda: self._open_link(primary_url))
        setup_layout.insertWidget(1, self.setup_page_button)
        form = QFormLayout()
        self.client_id = QLineEdit()
        self.client_id.setPlaceholderText('自己的 OAuth 客户端 ID')
        form.addRow('Client ID', self.client_id)
        self.client_secret = QLineEdit()
        self.client_secret.setEchoMode(QLineEdit.Password)
        self.import_button = None
        if platform.kind == 'youtube':
            form.addRow('Client Secret（可选）', self.client_secret)
            self.import_button = QPushButton('导入 Google 桌面客户端 JSON')
            self.import_button.setObjectName('IconButton')
            self.import_button.setCursor(Qt.PointingHandCursor)
            self.import_button.setAutoDefault(False)
            self.import_button.clicked.connect(self._import_google_client)
        setup_layout.addLayout(form)
        self.setup.setWidget(content)
        layout.addWidget(self.setup, 1)
        self.setup_button.toggled.connect(self.setup.setVisible)
        if self.import_button is not None:
            layout.addWidget(self.import_button)
        self.code = QLabel()
        self.code.setTextFormat(Qt.PlainText)
        self.code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.code)
        self.browser_actions = QWidget()
        browser_box = QHBoxLayout(self.browser_actions)
        browser_box.setContentsMargins(0, 0, 0, 0)
        self.browser_button = QPushButton('重新打开授权页')
        self.copy_code_button = QPushButton('复制授权码')
        for button in (self.browser_button, self.copy_code_button):
            button.setObjectName('IconButton')
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            browser_box.addWidget(button)
        self.browser_button.clicked.connect(lambda: self._open_link(self._authorization_url))
        self.copy_code_button.clicked.connect(lambda: QApplication.clipboard().setText(self._user_code))
        self.browser_actions.hide()
        layout.addWidget(self.browser_actions)
        layout.addStretch()
        self.remember = QCheckBox('记住登录（本机加密保存）')
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        actions = QHBoxLayout()
        self.forget_button = QPushButton('退出账号')
        self.read_button = QPushButton(action_label)
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
        self.setup_button.setChecked(not bool(self.client_id.text()))
        self.setup.setVisible(self.setup_button.isChecked())
        if self.client_id.text():
            self.setup_button.setText('修改登录配置与查看步骤')

    def _open_link(self, url):
        if url:
            if not QDesktopServices.openUrl(QUrl(url)):
                self.status.setText('无法打开系统浏览器，请检查默认浏览器设置后点击链接重试')
            elif url == self._authorization_url and self._worker is not None:
                self.status.setText('请在系统浏览器完成授权，软件正在等待结果…')

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
            self.status.setText('桌面客户端已载入，点击下方按钮完成 Google 授权。')
            self.setup_button.setChecked(False)
            self.setup_button.setText('修改登录配置与查看步骤')
        except (OSError, ValueError, KeyError, TypeError):
            self.status.setText('请选择 Google 下载的桌面应用客户端 JSON')

    def _read(self, _checked=False, *, force=False):
        if self._worker is not None:
            self.cancel_read()
            return
        client = {'client_id': self.client_id.text().strip(), 'client_secret': self.client_secret.text().strip()}
        if not client['client_id'] or (self.platform.kind == 'youtube' and
                not client['client_id'].endswith('.apps.googleusercontent.com')):
            self.setup_button.setChecked(True)
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
        self.setup_button.setChecked(False)
        self.setup_button.setText('修改登录配置与查看步骤')
        self.setup_button.setEnabled(False)
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
        if self.import_button is not None:
            self.import_button.setEnabled(False)
        self.busyChanged.emit(True)
        worker.start()

    def _open_browser(self, url, code):
        if self._read_cancelled or self._pending_done is not None or getattr(self._owner, '_closing', False):
            return
        self._authorization_url, self._user_code = url, code
        self.browser_actions.show()
        self.copy_code_button.setVisible(bool(code))
        self.code.setText('授权码：' + code if code else '')
        self.status.setText('请在系统浏览器完成授权，软件正在等待结果…')
        self._open_link(url)

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
            self._authorization_url, self._user_code = '', ''
            self.browser_actions.hide()
            self.code.clear()
            self._worker.cancel()
            self.status.setText('正在停止授权…')

    def _finished(self, worker):
        if getattr(self._owner, '_follow_loader', None) is worker:
            self._owner._follow_loader = None
        self._worker = None
        self._authorization_url, self._user_code = '', ''
        self.browser_actions.hide()
        self.code.clear()
        self.setup_button.setEnabled(True)
        worker.deleteLater()
        self.read_button.setText('开始授权' if self.login_only else '读取关注')
        self.reauthorize_button.setEnabled(True)
        self.client_id.setEnabled(True)
        self.client_secret.setEnabled(True)
        if self.import_button is not None:
            self.import_button.setEnabled(True)
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
