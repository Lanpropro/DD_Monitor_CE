"""离线画面弹幕回归：滚动、防追尾、显示参数、独立开关和共享连接。"""
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config, theme
from ddm.app import MainWindow
from ddm.danmaku import DanmakuClient
from ddm.dialogs import SettingsDialog
from ddm.widgets import Tile


class Client(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, room_id, parent=None):
        super().__init__(parent)
        self.stopped = False

    def start(self):
        self.status.emit("已连接")

    def stop(self):
        self.stopped = True


def check_motion(app):
    tile = Tile({"room_id": "1", "live": True})
    tile.resize(900, 540)
    tile.show()
    app.processEvents()
    overlay = tile.video_danmaku
    settings = dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                    video_danmaku_area=50)
    overlay.apply_settings(settings)
    tile.set_video_active(True)
    assert not overlay.isVisible() and not overlay.timer.isActive()
    tile.danmaku_button.click()
    assert overlay.isVisible() and overlay.geometry() == tile.video.geometry()
    try:
        for width in (200, 240, 300, 320, 360, 420, 900):
            tile.resize(width, 540)
            app.processEvents()
            controls = [tile.pause_button, tile.volume_button, tile.volume_slider,
                        tile.volume_label, tile.danmaku_button, tile.recording_button,
                        tile.fullscreen_button]
            visible = [widget for widget in controls if widget.isVisible()]
            assert all(widget.x() >= 0 and widget.geometry().right() < tile.bottom.width()
                       for widget in visible), (width, [(w.text() if hasattr(w, "text")
                                                        else "slider", w.geometry()) for w in visible])
            assert all(a.geometry().right() < b.geometry().left()
                       for a, b in zip(visible, visible[1:])), (width, [w.geometry() for w in visible])
            tile.set_recording_state("record")
            tile.set_recording_elapsed("12:34:56")
            app.processEvents()
            active = [widget for widget in controls[:-1] + [tile.recording_time, tile.fullscreen_button]
                      if widget.isVisible()]
            assert all(a.geometry().right() < b.geometry().left()
                       for a, b in zip(active, active[1:])), (width, [w.geometry() for w in active])
            assert active[-1].geometry().right() < tile.bottom.width()
            tile.set_recording_elapsed("")
            tile.set_recording_state("")
        tile.resize(900, 540)
        app.processEvents()
        assert overlay.font_pixels() == 28
        with patch("ddm.video_danmaku.time.monotonic", return_value=100):
            assert overlay.add_event({"text": "短弹幕", "color": "#ff99cc"})
            first = overlay.comments[0]
            speed = first.speed
            for _ in range(overlay.lane_count() - 1):
                assert overlay.add_event({"text": "其他轨道"})
            assert not overlay.add_event({"text": "轨道满时直接丢弃"})
        with patch("ddm.video_danmaku.time.monotonic", return_value=101):
            overlay._tick()
        assert abs(first.x - (overlay.width() - speed)) < 0.01, "滚动必须按实际时间推进"
        assert not overlay._lane_available(first.lane, speed * 10), "长弹幕不能追上前面的短弹幕"
        assert not overlay.add_event({"kind": "gift", "text": "礼物"})
        tile.set_paused(True)
        assert not overlay.timer.isActive()
        assert not overlay.add_event({"text": "暂停时不积压消息"})
        with patch("ddm.video_danmaku.time.monotonic", return_value=101):
            tile.set_paused(False)
        assert overlay.timer.isActive()
        with patch("ddm.video_danmaku.time.monotonic", return_value=110):
            overlay._tick()
        assert not overlay.comments and not overlay.timer.isActive()
        overlay.apply_settings(dict(settings, video_danmaku_speed=200))
        assert overlay.add_event({"text": "短弹幕"})
        assert abs(overlay.comments[0].speed - speed * 2) < 0.01
        overlay.apply_settings(dict(settings, video_danmaku_size=48, video_danmaku_area=25))
        assert overlay.font_pixels() == 48
        assert overlay.lane_count() * overlay.lane_height() <= overlay.height() * .25
        overlay.apply_settings(dict(settings, video_danmaku_scale=True))
        tile.resize(900, 760)
        app.processEvents()
        assert overlay.font_pixels() == 28
        tile.resize(900, 400)
        app.processEvents()
        assert overlay.font_pixels() < 28
        tile.set_fullscreen_controls_hidden(True)
        assert overlay.height() == tile.video.height() and overlay.isVisible()
        tile.danmaku_button.setChecked(False)
        assert not overlay.isVisible() and not overlay.comments and not overlay.timer.isActive()
    finally:
        tile.close()


def check_routing(app):
    rooms = [{"room_id": rid, "uname": rid, "live": True}
             for rid in ("1001", "1001", "1002", "1003")]
    with patch("ddm.app.DanmakuClient", Client), patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                            state={"plugins_enabled": []})
        window.resize(1200, 760)
        window.show()
        app.processEvents()
        first, duplicate, second, disabled = window.wall.tiles
        try:
            for tile in window.wall.tiles:
                tile.set_video_active(True)
            for tile in (first, duplicate, second):
                QTest.mouseClick(tile.danmaku_button, Qt.LeftButton)
            assert len(window._danmaku_clients) == 2, "同直播间的两格应共用连接"
            client = window._danmaku_clients["1001"]
            client.message.emit({"text": "房间一"})
            assert len(first.video_danmaku.comments) == len(duplicate.video_danmaku.comments) == 1
            assert not second.video_danmaku.comments and not disabled.video_danmaku.comments
            window.settings["danmaku_block_words"] = ["广告"]
            client.message.emit({"text": "广告"})
            client.message.emit({"kind": "gift", "text": "礼物"})
            assert len(first.video_danmaku.comments) == 1
            window.wall.set_layout("dm_main2")
            window.sync_danmaku()
            assert window._danmaku is client, "弹幕格应复用画面弹幕连接"
            assert window.wall.danmaku.count.text() == "已连接"
            client.message.emit({"text": "共享消息"})
            assert "共享消息" in window.wall.danmaku.body.toPlainText()
            first.danmaku_button.setChecked(False)
            duplicate.danmaku_button.setChecked(False)
            assert window._danmaku_clients["1001"] is client, "弹幕格仍需使用此连接"
            window.wall.set_layout("2x2")
            window.sync_danmaku()
            assert client.stopped and "1001" not in window._danmaku_clients
            first.set_room({"room_id": "2001", "uname": "新直播间", "live": True})
            first.set_video_active(True)
            first.danmaku_button.setChecked(True)
            client.message.emit({"text": "旧消息"})
            assert not first.video_danmaku.comments, "换房间后忽略旧连接的消息"
            saved = window.current_state()
            _, restored = config.build_rooms(saved)
            assert [room["video_danmaku_enabled"] for room in restored] == [True, False, True, False]
            reopened = MainWindow([], restored, layout_id="2x2", state=saved)
            try:
                assert [tile.danmaku_button.isChecked() for tile in reopened.wall.tiles] == \
                    [True, False, True, False]
            finally:
                reopened.close()
            window._on_fullscreen(first)
            window._clear_fullscreen_cover()
            assert first.video_danmaku.isVisible()
            assert "1002" not in window._danmaku_clients, "全屏时停止隐藏格子的订阅"
            window._exit_fullscreen()
            window._clear_fullscreen_cover()
            app.processEvents()
            window.sync_danmaku()
            assert "1002" in window._danmaku_clients
            second.room["live"] = False
            window.sync_danmaku()
            assert "1002" not in window._danmaku_clients
            clients = list(window._danmaku_clients.values())
            window.close()
            assert not window._danmaku_clients and all(client.stopped for client in clients)
        finally:
            window.close()


def check_settings(app):
    values = dict(config.DEFAULT_SETTINGS, video_danmaku_size=40, video_danmaku_speed=150,
                  video_danmaku_opacity=35, video_danmaku_area=25, video_danmaku_scale=False)
    dialog = SettingsDialog(values, {})
    dialog.nav.setCurrentRow(1)
    dialog.show()
    app.processEvents()
    page = dialog.danmaku_page
    try:
        assert all(page.values()[key] == value for key, value in values.items()
                   if key.startswith("video_danmaku_"))
        assert page.scroll.verticalScrollBar().maximum() > 0, "小设置窗口应可滚动访问所有选项"
        page.scroll.ensureWidgetVisible(page.video_scale)
        app.processEvents()
        assert page.video_scale.isVisible()
        page.reset()
        assert all(page.values()[key] == value for key, value in config.DEFAULT_SETTINGS.items()
                   if key.startswith("video_danmaku_"))
    finally:
        dialog.close()


def check_cancel(app):
    with patch("ddm.danmaku.bili.danmaku_conf") as lookup:
        client = DanmakuClient("123")
        client.stop()
        client.start()
        assert client.wait(1000)
        lookup.assert_not_called()
    started, release = threading.Event(), threading.Event()

    def lookup(room_id):
        started.set()
        assert release.wait(3)
        return 123, "token", [{"host": "example.invalid", "wss_port": 443}]

    with patch("ddm.danmaku.bili.danmaku_conf", lookup), patch("ddm.danmaku._Client") as backend, \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], layout_id="1x1", state={"plugins_enabled": []})
        try:
            client = window._ensure_danmaku_client("123")
            assert started.wait(1)
            before = time.monotonic()
            window._stop_danmaku_client("123")
            assert time.monotonic() - before < .2, "关闭开关不能等待网络请求而卡住界面"
            assert client in window._danmaku_retired
            release.set()
            assert client.wait(1000)
            app.processEvents()
            assert not window._danmaku_retired
            backend.assert_not_called()
        finally:
            release.set()
            window.close()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    check_motion(app)
    check_routing(app)
    check_settings(app)
    check_cancel(app)
    print("画面弹幕滚动、防追尾、设置、底栏、连接共享、换台、全屏及退出：通过")


if __name__ == "__main__":
    main()
