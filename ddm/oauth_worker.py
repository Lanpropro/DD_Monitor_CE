"""Cancellable OAuth authorization and account/follow loading worker."""
import threading
import requests
from PySide6.QtCore import QThread, Signal
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
        from .oauth_login import authorize
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
