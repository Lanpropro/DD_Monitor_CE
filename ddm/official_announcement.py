"""Fetch a single official bulletin once per application launch."""
import json
import re

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .notice_dialog import NoticeDialog
from .result_notice import show_result


ANNOUNCEMENT_URL = "https://raw.githubusercontent.com/Lanpropro/DD_Monitor_CE/main/docs/releases/announcement.json"
MAX_RESPONSE_BYTES = 32 * 1024


def parse_announcement(payload):
    if len(payload) > MAX_RESPONSE_BYTES:
        return None
    try:
        item = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(item, dict):
        return None
    key, title, body, link = (item.get(field, "") for field in ("id", "title", "body", "link"))
    if not all(isinstance(value, str) for value in (key, title, body, link)):
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key):
        return None
    title, body = title.strip(), body.strip()
    if not 0 < len(title) <= 120 or not 0 < len(body) <= 5000:
        return None
    url = QUrl(link, QUrl.StrictMode)
    if link and (not url.isValid() or url.scheme() != "https" or not url.host() or url.userInfo()):
        return None
    return key, title, body, url


class OfficialAnnouncement(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.network = QNetworkAccessManager(self)
        self.network.finished.connect(self.finished)
        request = QNetworkRequest(QUrl(ANNOUNCEMENT_URL))
        request.setTransferTimeout(5000)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.NoLessSafeRedirectPolicy)
        self.reply = self.network.get(request)
        self.reply.downloadProgress.connect(self._limit_response)

    def _limit_response(self, received, total):
        if max(received, total) > MAX_RESPONSE_BYTES:
            self.cancel()

    def cancel(self):
        if self.reply is not None and self.reply.isRunning():
            self.reply.abort()

    @Slot(QNetworkReply)
    def finished(self, reply):
        self.reply = None
        try:
            if not self.host._closing and reply.error() == QNetworkReply.NoError:
                announcement = parse_announcement(bytes(reply.readAll()))
                if announcement is not None:
                    self.deliver(announcement)
        finally:
            reply.deleteLater()

    def deliver(self, announcement):
        key, title, body, url = announcement
        host = self.host
        if host.state.get("official_announcement_id") == key:
            return
        show_result(host, title, kind="announcement", notice_key=("official-announcement", key),
                    on_click=lambda: self.show_details(title, body, url), persistent=True)
        host.state["official_announcement_id"] = key
        host._save_timer.start()

    def show_details(self, title, body, url):
        dialog = NoticeDialog("官方公告", title, "我知道了", self.host,
                              settings=self.host.settings, link=url)
        dialog.content.setPlainText(body)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
