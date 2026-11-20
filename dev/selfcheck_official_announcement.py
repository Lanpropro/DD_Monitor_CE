"""Startup announcements use one background request and one notification per ID."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ddm import motion, official_announcement as bulletin, theme
from ddm.app_notices import AppNotices
from ddm.notification_center import NotificationButton


ANNOUNCEMENT = {"id": "notice-1", "title": "频道维护", "body": "维护将在周末进行。\n<em>按原文显示</em>",
                "link": "https://github.com/Lanpropro/DD_Monitor_CE"}


def check_parsing():
    def parse(item):
        return bulletin.parse_announcement(json.dumps(item).encode("utf-8"))

    key, title, body, url = parse(ANNOUNCEMENT)
    assert (key, title, body) == tuple(ANNOUNCEMENT[name] for name in ("id", "title", "body"))
    assert url == QUrl(ANNOUNCEMENT["link"])
    assert parse(dict(ANNOUNCEMENT, link=""))[-1].isEmpty()
    for invalid in (None, [], {}, dict(ANNOUNCEMENT, id="非法"), dict(ANNOUNCEMENT, title="<html>" * 30),
                    dict(ANNOUNCEMENT, link="file:///C:/test"), dict(ANNOUNCEMENT, link="https://name@host/")):
        assert parse(invalid) is None, invalid
    assert bulletin.parse_announcement(b'{"broken"') is None
    assert bulletin.parse_announcement(b' ' * (bulletin.MAX_RESPONSE_BYTES + 1)) is None


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    app.setQuitOnLastWindowClosed(False)
    check_parsing()
    paths = []
    responses = {
        "/active": (200, json.dumps(ANNOUNCEMENT).encode()),
        "/empty": (200, b"null"),
        "/missing": (404, b""),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            status, payload = responses[self.path]
            self.send_response(status)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def launch(path, state, *, visible=False):
            host = QWidget()
            host._closing = False
            host._save_timer = Mock()
            host.settings = {"auto_update": False}
            host.state = state
            host.sidebar = SimpleNamespace(notification_button=NotificationButton(host))
            if visible:
                host.resize(800, 600)
                host.show()
            controller = AppNotices(host)
            with patch.object(bulletin, "ANNOUNCEMENT_URL", f"http://127.0.0.1:{server.server_port}{path}"):
                controller.check_official_announcement()
                controller.check_official_announcement()
            for _ in range(100):
                if controller.official_announcement.reply is None:
                    break
                QTest.qWait(20)
            assert controller.official_announcement.reply is None, path
            controller.check_official_announcement()
            return host, controller

        try:
            state = {}
            with patch.object(motion, "enabled", return_value=False):
                host, controller = launch("/active", state, visible=True)
            entries = host.sidebar.notification_button.center.entries
            assert len(entries) == 1
            entry = entries[0]
            assert (entry.message, entry.kind, entry.unread) == ("频道维护", "announcement", True)
            assert state["official_announcement_id"] == "notice-1"
            host._save_timer.start.assert_called_once()
            popup = host._result_notice
            assert popup.isVisible() and not popup.timer.isActive()
            assert popup.category.text() == "官方公告" and popup.action.text() == "查看详情"

            def view(dialog):
                assert dialog.heading.text() == ANNOUNCEMENT["title"]
                assert dialog.content.toPlainText() == ANNOUNCEMENT["body"]
                assert dialog.confirm_button.text() == "我知道了"
                assert dialog.window_header.breadcrumb.text() == "官方公告"
                original = next(button for button in dialog.findChildren(QPushButton)
                                if button.text() == "查看原文")
                with patch("ddm.notice_dialog.QDesktopServices.openUrl") as open_url:
                    original.click()
                    open_url.assert_called_once_with(QUrl(ANNOUNCEMENT["link"]))

            with patch.object(bulletin.NoticeDialog, "exec", lambda dialog: view(dialog)):
                QTest.mouseClick(popup.action, Qt.LeftButton)
            assert not popup.isVisible()
            assert not entry.unread
            controller.cancel_official_announcement()
            host.close()
            host.deleteLater()

            for path, saved in (("/active", state.copy()), ("/empty", {}), ("/missing", {})):
                host, controller = launch(path, saved)
                assert not host.sidebar.notification_button.center.entries
                host._save_timer.start.assert_not_called()
                host.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            assert paths == ["/active", "/active", "/empty", "/missing"], paths
        finally:
            server.shutdown()
            worker.join()
    print("PASS: startup-only request, deduplication, read-only details, empty feed and failed request")


if __name__ == "__main__":
    main()
