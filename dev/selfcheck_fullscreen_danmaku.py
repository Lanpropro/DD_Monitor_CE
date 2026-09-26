"""离线检查全屏弹幕连接、透明浮层和开关。"""
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme, window_fullscreen  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": "1001", "uname": "甲", "live": False},
             {"room_id": "1002", "uname": "乙", "live": False}]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="main2")
    window.resize(1000, 700)
    window.show()
    app.processEvents()
    tile = window.wall.tiles[1]
    tile.room["live"] = True
    sources = []
    source = object()

    def start(room_id, _uname=""):
        sources.append(room_id)
        window._danmaku = source
        window._danmaku_room = room_id

    def stop():
        window._danmaku = None
        window._danmaku_room = ""

    with (patch.object(window, "_hold_fullscreen_frame", return_value=None),
          patch.object(window_fullscreen, "enter", return_value="fake"),
          patch.object(window_fullscreen, "exit", return_value=None),
          patch.object(window, "start_danmaku", side_effect=start),
          patch.object(window, "stop_danmaku", side_effect=stop)):
        window._on_fullscreen(tile)
        app.processEvents()
        assert sources == ["1002"], "全屏弹幕应连接放大的直播间"
        assert tile.fullscreen_danmaku.isVisible()
        assert tile.fullscreen_danmaku.isWindow(), "弹幕应使用透明工具窗口盖过 VLC 视频"
        assert tile.fullscreen_danmaku.windowFlags() & Qt.WindowTransparentForInput
        assert tile.fullscreen_danmaku.testAttribute(Qt.WA_TranslucentBackground)
        assert tile.fullscreen_danmaku_button.x() < tile.volume_button.x(), \
            "弹幕按钮应放在音量条左侧"
        assert int(tile.fullscreen_danmaku.winId()) != int(tile.video.winId())
        assert tile.fullscreen_danmaku.geometry().topLeft() == tile.video.mapToGlobal(QPoint())
        assert tile.fullscreen_danmaku.size() == tile.video.size()
        window._on_danmaku_message(source, {"kind": "danmaku", "text": "测试弹幕"})
        assert len(tile.fullscreen_danmaku._items) == 1
        tile.fullscreen_danmaku._items[0]["started"] -= 1.0
        tile.fullscreen_danmaku.update()
        app.processEvents()
        image = tile.fullscreen_danmaku.grab().toImage()
        assert image.pixelColor(0, 0).alpha() == 0, "弹幕浮层不能遮黑视频"
        assert any(image.pixelColor(x, y).red() > 180
                   and image.pixelColor(x, y).alpha() > 180
                   for x in range(max(0, image.width() - 200), image.width(), 4)
                   for y in range(0, image.height(), 4)), "弹幕文字应以亮色绘制出来"
        window.settings["danmaku_block_words"] = ["广告"]
        window._on_danmaku_message(source, {"kind": "danmaku", "text": "广告弹幕"})
        assert len(tile.fullscreen_danmaku._items) == 1
        QTest.mouseClick(tile.fullscreen_danmaku_button, Qt.LeftButton)
        assert not tile.fullscreen_danmaku.isVisible()
        assert not tile.fullscreen_danmaku._items
        QTest.mouseClick(tile.fullscreen_danmaku_button, Qt.LeftButton)
        assert tile.fullscreen_danmaku.isVisible()
        window._exit_fullscreen()
        app.processEvents()
        assert not tile.fullscreen_danmaku.isVisible()
        assert window._danmaku is None
    window.close()
    print("全屏弹幕来源、显示、屏蔽与开关：通过")


if __name__ == "__main__":
    main()
