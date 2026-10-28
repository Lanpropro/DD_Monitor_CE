"""Offline Super Chat state, snapshot, panel, and video-overlay regression."""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import super_chat, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.video_danmaku import VideoDanmaku  # noqa: E402
from ddm.widgets import DanmakuPanel  # noqa: E402


def chat(chat_id, **values):
    now = int(time.time())
    return {
        "id": chat_id,
        "uid": "42",
        "uname": "测试用户",
        "message": "醒目留言内容",
        "price": 30,
        "start_time": now,
        "end_time": now + 120,
        "background_color": "#ffdd00",
        "background_price_color": "#ff8800",
        **values,
    }


def check_store():
    store = super_chat.SuperChatStore()
    first = store.upsert(chat("1"))
    assert first["super_chat_id"] == "1"
    store.upsert({**chat("1"), "message": "更新后的内容"})
    assert len(store.items) == 1
    assert store.items["1"]["message"] == "更新后的内容"
    store.upsert(chat("2"))
    assert [item["super_chat_id"] for item in store.active()] == ["1", "2"]
    store.remove(["1"])
    assert list(store.items) == ["2"], "删除要立即生效"
    store.upsert(chat("1", message="删除后的旧快照"))
    assert "1" not in store.items, "删除后迟到的快照不能把 SC 加回来"
    store.upsert({**chat("2"), "source": "snapshot"})
    assert store.items["2"]["message"] == "醒目留言内容", "快照不能覆盖较新的实时内容"
    snapshot_first = super_chat.SuperChatStore()
    snapshot_first.upsert({**chat("4"), "message": "快照先到",
                           "source": "snapshot"})
    snapshot_first.upsert({**chat("4"), "message": "实时后到",
                           "source": "websocket"})
    assert snapshot_first.items["4"]["message"] == "实时后到"
    expired = {**chat("3"), "start_time": 0, "end_time": int(time.time()) - 1}
    store.upsert(expired)
    assert "3" not in store.items, "已经过期的 SC 不应进入活动集合"
    assert store.expire(now=time.time() + 1000)
    assert not store.active()


def check_text_contrast():
    def contrast(first: QColor, second: QColor) -> float:
        def luminance(color):
            values = []
            for value in (color.redF(), color.greenF(), color.blueF()):
                values.append(value / 12.92 if value <= .03928
                              else ((value + .055) / 1.055) ** 2.4)
            return .2126 * values[0] + .7152 * values[1] + .0722 * values[2]
        low, high = sorted((luminance(first), luminance(second)))
        return (high + .05) / (low + .05)

    expected = {
        "#ffdd00": "#20242c",
        "#ffffff": "#20242c",
        "#1f2a44": "#ffffff",
        "#7b1029": "#ffffff",
    }
    for background, foreground in expected.items():
        text = super_chat.readable_text_color(background)
        assert text.name() == foreground, (background, text.name())
        assert contrast(QColor(background), text) >= 4.5
        assert super_chat.readable_text_color(QColor(background)).name() == foreground


def check_snapshot():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 0, "data": {"list": None}}

    with patch.object(super_chat.requests, "get", return_value=Response()) as request:
        with patch.object(super_chat.bili, "_resolve_room_id", return_value="456"):
            assert super_chat.snapshot_events("123") == []
        assert request.call_args.kwargs["params"] == {"room_id": "456"}

    class Failing:
        def raise_for_status(self):
            raise RuntimeError("network")

    with patch.object(super_chat.requests, "get", return_value=Failing()):
        try:
            super_chat.snapshot_events("123")
        except RuntimeError:
            pass
        else:
            raise AssertionError("snapshot_events must expose network failures to its worker")

    with patch.object(super_chat, "snapshot_events", side_effect=RuntimeError("network")):
        worker = super_chat.SuperChatSnapshot("123")
        loaded = []
        worker.loaded.connect(lambda room_id, items: loaded.append((room_id, items)))
        worker.run()
        assert loaded == [("123", [])], "snapshot failure must degrade to an empty list"


def check_snapshot_retirement(app):
    class RunningSnapshot(QThread):
        loaded = Signal(str, list)

        def __init__(self, room_id, parent=None):
            super().__init__(parent)
            self.room_id = str(room_id)
            self.started = False

        def run(self) -> None:
            self.started = True
            while not self.isInterruptionRequested():
                self.msleep(5)

    with patch.object(app_module, "SuperChatSnapshot", RunningSnapshot), \
            patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], layout_id="1x1", state={"plugins_enabled": []})
        loader = RunningSnapshot("123", window)
        window._super_chat_snapshots["123"] = loader
        loader.start()
        try:
            deadline = time.monotonic() + 2
            while not loader.started and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            assert loader.started
            window._super_chat_snapshots.pop("123")
            loader.requestInterruption()
            window._super_chat_retired.append(loader)
            assert loader.wait(500)
            window._on_super_chat_snapshot_finished("123", loader)
            assert loader not in window._super_chat_retired
            assert window._super_chat_snapshots == {}
        finally:
            loader.requestInterruption()
            loader.wait(1000)
            window.close()
        assert app is not None


def check_websocket_adapter():
    from ddm.danmaku import _Handler

    events = []
    handler = _Handler(events.append)
    open_chat = SimpleNamespace(
        room_id=1, uid=2, open_id="open", uname="观众",
        uface="https://example.invalid/avatar.png", message_id=345,
        message="Open Live SC", rmb=50, timestamp=1, start_time=2,
        end_time=3, guard_level=0, fans_medal_level=0,
        fans_medal_name="", fans_medal_wearing_status=False, msg_id="m")
    handler._on_open_live_super_chat(None, open_chat)
    assert events[-1]["super_chat_id"] == "345"
    assert events[-1]["price"] == 50
    assert events[-1]["face"] == "https://example.invalid/avatar.png"
    handler._on_open_live_super_chat(
        None, SimpleNamespace(message_id=346, message="", msg="Open Live alias",
                              rmb=10, start_time=2, end_time=3, uid=2,
                              uname="观众"))
    assert events[-1]["message"] == "Open Live alias"
    handler._on_open_live_super_chat_delete(
        None, SimpleNamespace(message_ids=[345, 346]))
    assert events[-1] == {"kind": "super_chat_delete", "ids": ["345", "346"]}


def check_room_lifecycle():
    from selfcheck_video_danmaku import Client, Snapshot

    with patch.object(app_module, "SuperChatSnapshot", Snapshot), \
            patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], layout_id="1x1", state={"plugins_enabled": []})
        try:
            client = Client("123")
            window._danmaku_clients["123"] = client
            window._load_super_chat_snapshot("123", client)
            first = window._super_chat_snapshots["123"]
            window._on_danmaku_message(client, {"kind": "super_chat_delete", "ids": ["deleted"]})
            first.loaded.emit("123", [super_chat.normalize(chat("deleted"), source="snapshot")])
            assert not window._super_chats["123"].active(), "Delete before the first snapshot must persist"

            window._stop_danmaku_client("123")
            client = Client("123")
            window._danmaku_clients["123"] = client
            window._load_super_chat_snapshot("123", client)
            current = window._super_chat_snapshots["123"]
            first.loaded.emit("123", [super_chat.normalize(chat("stale"), source="snapshot")])
            assert "123" not in window._super_chats, "A retired snapshot must not affect a new connection"
            current.loaded.emit("123", [super_chat.normalize(chat("current"), source="snapshot")])
            assert set(window._super_chats["123"].items) == {"current"}
            window._on_super_chat_snapshot_finished("123", first)
            assert window._super_chat_snapshots["123"] is current
        finally:
            window.close()


def check_widgets(app):
    panel = DanmakuPanel()
    overlay = VideoDanmaku()
    now = int(time.time())
    items = [
        super_chat.normalize(chat("1", message="第一条", price=30)),
        super_chat.normalize(chat("2", message="第二条", price=50,
                                  background_color="#ff88aa")),
    ]
    try:
        panel.resize(480, 420)
        panel.set_super_chats(items)
        panel.show()
        app.processEvents()
        assert panel.super_chats.isVisible()
        assert panel.super_chats._cards[0].message.text() == "第一条"
        assert panel.super_chats._cards[0].price.text() == "¥30"
        assert panel.super_chats._cards[0].name.textFormat() == Qt.PlainText
        assert panel.super_chats._cards[0].message.textFormat() == Qt.PlainText
        assert "#20242c" in panel.super_chats._cards[0].styleSheet()
        panel.set_super_chats([
            super_chat.normalize(chat("dark", background_color="#1f2a44")),
        ])
        app.processEvents()
        assert "#ffffff" in panel.super_chats._cards[0].styleSheet()
        panel.set_super_chats([*items, super_chat.normalize(chat("3", message="第三条"))])
        panel.resize(480, 420)
        app.processEvents()
        visible = sum(card.isVisible() for card in panel.super_chats._cards)
        assert visible == 3 and visible <= panel._super_chat_limit(), \
            "420px 面板应显示三张卡片"
        panel.set_placeholder("New room")
        assert not panel.super_chats._events and panel.super_chats.isHidden()

        overlay.resize(800, 450)
        overlay.set_enabled(True)
        overlay.set_active(True)
        overlay.set_super_chats(items)
        overlay.show()
        app.processEvents()
        assert overlay.super_chat_overlay.isVisible()
        image = overlay.super_chat_overlay.grab().toImage()
        assert image.pixelColor(image.width() - 30, 100).alpha() > 0
        overlay.set_super_chats([
            super_chat.normalize(chat(
                "dark", message="DARK", uname="NAME",
                background_color="#1f2a44", background_price_color="#0b1220")),
        ])
        app.processEvents()
        dark = overlay.super_chat_overlay.grab().toImage()
        region = dark.rect().intersected(
            overlay.super_chat_overlay.rect().adjusted(
                dark.width() - 360, 0, 0, min(200, dark.height())))
        assert any(dark.pixelColor(x, y).lightness() > 180
                   for y in range(region.top(), region.bottom() + 1)
                   for x in range(region.left(), region.right() + 1)), \
            "dark SC background needs light text"
        overlay.resize(140, 180)
        app.processEvents()
        assert overlay.super_chat_overlay.size() == overlay.size()
        small = overlay.super_chat_overlay.grab().toImage()
        assert any(small.pixelColor(x, y).alpha() > 0
                   for y in range(small.height()) for x in range(small.width()))
        overlay.set_enabled(False)
        assert overlay.super_chat_overlay.isHidden()
        assert len(overlay.super_chats) == 1, "关闭弹幕只隐藏 SC，不能清掉状态"
        overlay.set_enabled(True)
        assert overlay.super_chat_overlay.isVisible()
        overlay.clear()
        assert overlay.super_chat_overlay.isHidden() and not overlay.super_chats
        assert overlay.add_event({"kind": "gift"}) is False
    finally:
        panel.close()
        overlay.close()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    check_store()
    check_text_contrast()
    check_snapshot()
    check_snapshot_retirement(app)
    check_websocket_adapter()
    check_room_lifecycle()
    check_widgets(app)
    print("Super Chat store, snapshot, panel, and video overlay: PASS")
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    main()
