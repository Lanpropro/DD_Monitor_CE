"""Offline Super Chat state, snapshot, panel, and video-overlay regression."""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QRect, QThread, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config, super_chat, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.video_danmaku import VideoDanmaku  # noqa: E402
from ddm.widgets import DanmakuPanel, SuperChatCard  # noqa: E402


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
            window._dismiss_super_chat('123', 'current')
            assert 'current' in window._super_chats['123'].items
            assert not window._super_chats['123'].active(), 'Local close must not delete the source event'
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
        assert panel.super_chats._cards[0].message.text() == "第二条"
        assert panel.super_chats._cards[0].price.text() == "¥50"
        assert panel.super_chats._cards[0].name.textFormat() == Qt.PlainText
        assert panel.super_chats._cards[0].message.textFormat() == Qt.PlainText
        assert "#FFFFFF" in panel.super_chats._cards[0].styleSheet()
        panel.set_super_chats([
            super_chat.normalize(chat("dark", background_color="#1f2a44")),
        ])
        app.processEvents()
        assert "#FFFFFF" in panel.super_chats._cards[0].styleSheet()
        panel.set_super_chats([*items, super_chat.normalize(chat("3", message="第三条"))])
        panel.resize(480, 420)
        app.processEvents()
        visible = sum(card.isVisible() for card in panel.super_chats._cards)
        assert visible == 3 and panel.super_chats._cards[0].y() > panel.super_chats._cards[1].y(), \
            'Three or more SCs must form a selectable stack'
        assert panel.super_chats.width() < panel.body.viewport().width() / 2
        assert panel.super_chats.x() >= panel.body.viewport().width() / 2
        assert panel.super_chats.parentWidget() is panel.body.viewport()
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
        assert overlay.super_chat_overlay.width() <= overlay.width()
        assert overlay.super_chat_overlay.height() <= overlay.height()
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


def check_avatar_header_and_edges(app):
    avatar = QPixmap(64, 64)
    avatar.fill(QColor('#dd22bb'))
    event = super_chat.normalize(chat('avatar', price=100, face='https://example.invalid/avatar.png',
                                      background_color='#ddeeff', background_bottom_color='#234567',
                                      background_price_color='#ff8800'))
    card = SuperChatCard()
    overlay = VideoDanmaku()
    try:
        with patch.object(super_chat, 'load_cached_image', return_value=avatar):
            card.resize(340, 100)
            card.set_event(event)
            card.show()
            overlay.resize(1200, 600)
            overlay.apply_settings({'super_chat_opacity': 100})
            overlay.set_enabled(True)
            overlay.set_active(True)
            overlay.set_super_chats([event])
            overlay.show()
            app.processEvents()
        assert card.avatar_image.pixmap.cacheKey() == avatar.cacheKey()
        assert card.left.parentWidget() is card.user_details
        assert card.left.x() >= card.name.geometry().right()
        assert card.price.y() >= card.name.geometry().bottom()
        assert card.message.font().pixelSize() == 14
        image = card.avatar.grab().toImage()
        assert image.pixelColor(image.width() // 2, image.height() // 2).name() == '#dd22bb'
        sc = overlay.super_chat_overlay
        image = sc.render_image()
        rect = sc.card_rects()[0].translated(-sc._content_origin)
        scale = image.devicePixelRatio()
        def pixel(x, y):
            return image.pixelColor(round((rect.x() + x) * scale), round((rect.y() + y) * scale))
        assert pixel(22, 18).name() == '#dd22bb', 'Video SC must paint the sender avatar'
        assert pixel(rect.width() - 60, 5).name() == '#fff1c5', 'User information must use the light official header'
        assert any(0 < pixel(x, y).alpha() < 255 for x in range(9) for y in range(9)), \
            'Rounded corners must retain fractional alpha instead of a binary mask'
        before = sc.avatar_image.pixmap.cacheKey()
        sc.avatar_image._loaded('https://example.invalid/old-avatar.png', QPixmap(16, 16))
        assert sc.avatar_image.pixmap.cacheKey() == before, 'Late avatars must not replace the current sender'
        sc.set_chats([event], .35)
        baseline = sc.render_image()
        base_rect = sc.card_rects()[0].translated(-sc._content_origin)
        sc.set_chats([event, super_chat.normalize(chat('low', price=30, background_color='#ff0000')),
                      super_chat.normalize(chat('middle', price=50, background_color='#00ff00'))], .35)
        stacked = sc.render_image()
        front = sc.card_rects()[0].translated(-sc._content_origin)
        for x, y in ((2, 50), (7, 38), (rect.width() - 4, 50)):
            single_pixel = baseline.pixelColor(round((base_rect.x() + x) * scale), round((base_rect.y() + y) * scale))
            stack_pixel = stacked.pixelColor(round((front.x() + x) * scale), round((front.y() + y) * scale))
            assert single_pixel == stack_pixel, 'Rear colours must not bleed into foreground edges'
    finally:
        card.close()
        overlay.close()


def check_quick_card_mask(app):
    parent = QWidget()
    parent.resize(640, 360)
    overlay = VideoDanmaku(parent)
    overlay.setGeometry(parent.rect())
    try:
        # Quick hides its raster controller with an off-widget pixel. The SC
        # sibling must use the real video mask instead of inheriting that pixel.
        overlay._quick_requested = True
        overlay._suppress_quick_raster_surface()
        region = QRegion(QRect(0, 0, 640, 340))
        overlay.setMask(region)
        overlay.set_enabled(True)
        overlay.set_active(True)
        parent.show()
        app.processEvents()
        items = [super_chat.normalize(chat('quick-mask'))]
        for _ in range(2):
            overlay.set_super_chats(items)
            card = overlay.super_chat_overlay.card_rects()[0].toAlignedRect()
            sc = overlay.super_chat_overlay
            visible_mask = sc.mask().translated(sc._content_origin)
            assert visible_mask.subtracted(region).isEmpty()
            assert visible_mask.contains(card.center()), \
                'SC cards must remain inside the visible mask after every tick'
            assert sc.width() <= 342 and sc.height() <= 118, 'Native SC surface must stay card-sized'
            image = sc.render_image()
            assert any(image.pixelColor(x, y).alpha() > 0
                       for y in range(image.height()) for x in range(image.width()))
        overlay.super_chat_overlay.bind(overlay)
        assert overlay.super_chat_overlay.mask().translated(overlay.super_chat_overlay._content_origin).subtracted(region).isEmpty()
        overlay.set_native_video(False)
        overlay.super_chat_overlay.sync(overlay)
        assert overlay.mask() == region
        assert overlay.super_chat_overlay.mask().translated(overlay.super_chat_overlay._content_origin).subtracted(region).isEmpty()
    finally:
        overlay.clear()
        parent.close()


def check_official_palette(app):
    expected = (
        (30, '#EDF5FF', '#2A60B2'), (50, '#DBFFFD', '#427D9E'),
        (100, '#FFF1C5', '#E2B52B'), (500, '#FFEAD2', '#E09443'),
        (1000, '#FFE7E4', '#E54D4D'), (2000, '#FFD8D8', '#AB1A32'))
    for price, header, body in expected:
        for source in ('snapshot', 'websocket'):
            event = super_chat.normalize(chat(str(price), price=price, background_color='#010203',
                                             background_bottom_color='#040506'), source=source)
            assert event['background_color'] == header
            assert event['background_bottom_color'] == body
        card = SuperChatCard()
        overlay = VideoDanmaku()
        try:
            with patch('ddm.super_chat.motion.enabled', return_value=False):
                raw = chat(str(price), price=price, background_color='#FF0000',
                           background_bottom_color='#00FF00')
                card.resize(340, 100)
                card.set_event(raw)
                card.show()
                overlay.resize(1200, 600)
                overlay.apply_settings({'super_chat_opacity': 100})
                overlay.set_enabled(True)
                overlay.set_active(True)
                overlay.set_super_chats([dict(raw, kind='super_chat')])
                overlay.show()
                app.processEvents()
            panel_image = card.grab().toImage()
            assert panel_image.pixelColor(panel_image.width() // 2, 4).name() == header.lower()
            assert panel_image.pixelColor(5, panel_image.height() - 12).name() == body.lower()
            assert panel_image.pixelColor(panel_image.width() - 20, panel_image.height() - 10).name() == body.lower(), \
                'The SC text viewport must keep its official body background'
            sc = overlay.super_chat_overlay
            image = sc.render_image()
            rect = sc.card_rects()[0].translated(-sc._content_origin)
            ratio = image.devicePixelRatio()
            pixel = lambda x, y: image.pixelColor(round((rect.x() + x) * ratio), round((rect.y() + y) * ratio))
            assert pixel(rect.width() / 2, 4).name() == header.lower()
            assert pixel(5, rect.height() - 12).name() == body.lower()
            assert any(pixel(x, y).red() > 245 and pixel(x, y).green() > 245 and pixel(x, y).blue() > 245
                       for y in range(62, 90) for x in range(12, 120)), 'SC body text must be white'
            sc.presentation.collapse()
            rect = sc.card_rects()[0].translated(-sc._content_origin)
            image = sc.render_image()
            assert pixel(rect.width() / 2, 4).name() == header.lower()
            assert rect.height() == 36
        finally:
            card.close()
            overlay.close()
    for price, minimum in ((0, 30), (49, 30), (99, 50), (499, 100), (999, 500),
                           (1999, 1000), (5000, 2000)):
        assert super_chat.super_chat_palette(price) == super_chat.super_chat_palette(minimum)
    palette = super_chat.super_chat_palette(30)
    palette['background_color'] = '#FF0000'
    assert super_chat.super_chat_palette(30)['background_color'] == '#EDF5FF'


def check_adaptive_content(app):
    samples = ('第一行 abc\n第二行 gypq', '这是一条较长的醒目留言，全部正文应该完整展示。' * 6,
               'https://example.invalid/' + 'abcdefghijklmnop' * 10,
               'A long message with several English words. ' * 8,
               '第一段\n\n第二段\n第三段 😀 表情与换行\nEND gypq')
    for scale in (1.0, 1.25, 2.0):
        for message in samples:
            event = chat('adaptive', message=message)
            width = round(340 * scale)
            height = super_chat.sc_card_height(event, width, scale)
            images = []
            for extra in (0, 50):
                image = QImage(width, height + round(extra * scale), QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                VideoDanmaku._paint_super_chat(painter, image.rect(), event, scale)
                painter.end()
                images.append(image)
            region = QRect(round(12 * scale), round(56 * scale), width - round(24 * scale), height - round(56 * scale))
            assert images[0].copy(region) == images[1].copy(region), 'Expanded SC text must match an unconstrained render'
            card = SuperChatCard()
            try:
                card.configure(scale, False)
                card.setFixedWidth(width)
                card.set_event(event)
                card.show()
                app.processEvents()
                assert card.message.text() == message
                assert card.message.document().size().height() <= card.message.viewport().height(), \
                    ('All panel SC text must fit', scale, len(message), card.height())
                assert card.height() == height
            finally:
                card.close()
    short = super_chat.sc_card_height(chat('short', message='short'), 340)
    long = super_chat.sc_card_height(chat('long', message=samples[1]), 340)
    assert long > short
    assert super_chat.sc_card_height(chat('compact', message=samples[1]), 340, collapsed=True) == 36


def check_settings_persistence():
    expected = {'super_chat_scale': 140, 'super_chat_collapse_delay': 9,
                'super_chat_position': [.2, .7]}
    with patch.object(MainWindow, 'refresh_status'), patch.object(MainWindow, 'refresh_stats'):
        window = MainWindow([], [], state={'plugins_enabled': []})
        try:
            window._on_video_danmaku_settings_changed(expected)
            saved = window.current_state()
            assert window._save_timer.isActive()
        finally:
            window.close()
        with TemporaryDirectory(prefix='ddm-sc-settings-') as directory, \
                patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')), \
                patch.dict(os.environ):
            os.environ.pop('DDM_NO_SAVE', None)
            config.save(saved)
            loaded = config.load()
        restored = MainWindow([], [], state=loaded)
        try:
            for key, value in expected.items():
                assert restored.settings[key] == value, (key, restored.settings[key])
        finally:
            restored.close()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    check_official_palette(app)
    check_adaptive_content(app)
    check_store()
    check_text_contrast()
    check_snapshot()
    check_snapshot_retirement(app)
    check_websocket_adapter()
    check_room_lifecycle()
    check_settings_persistence()
    with patch('ddm.super_chat.motion.enabled', return_value=False):
        check_widgets(app)
        check_avatar_header_and_edges(app)
        check_quick_card_mask(app)
    print("Super Chat store, snapshot, panel, and video overlay: PASS")
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    main()
