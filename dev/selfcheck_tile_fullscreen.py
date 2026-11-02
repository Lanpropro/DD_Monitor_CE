"""离线回归：1+5 布局的格子全屏不能改布局、顺序或房间。"""
import os
import sys
import time
from unittest.mock import patch

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def wait_tiles_revealed(window, app, timeout: float = 3.0) -> bool:
    """等「分批露面」跑完。

    退出全屏时其余格子是一帧两格回来的（4K 下单格 VLC 窗口重配约 23 ms，
    一次做完主线程会僵住，遮盖图也就淡不动），所以退出之后不能立刻要求
    全部可见。
    """
    end = time.time() + timeout
    while time.time() < end:
        if not window.wall._pending_reveal:
            return True
        app.processEvents()
        time.sleep(0.02)
    return not window.wall._pending_reveal


def main() -> None:
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + i), "uname": f"主播{i}", "live": False}
             for i in range(6)]
    # 此测试只验证全屏布局，不启动真实直播取流或自动提升画质。
    with patch.object(MainWindow, "start_all"):
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner")
    window._upgrade_fullscreen_quality = lambda _tile: False
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    tiles = list(window.wall.tiles)
    room_ids = [tile.room["room_id"] for tile in tiles]
    assert len(tiles) == 6 and all(tile.fullscreen_button.isVisible() for tile in tiles)
    assert all(tile.volume_label.x() < tile.fullscreen_button.x()
               for tile in tiles), "全屏按钮应在音量条右侧"

    target = tiles[1]
    target.set_focused(True)
    target.room["live"] = True
    normal_size = window.size()
    saved_geometry = window.current_state()["geometry"]
    window_hwnd = int(window.winId())
    QCursor.setPos(target.mapToGlobal(target.rect().center()))
    video_hwnd = int(target.video.winId())
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window._fullscreen_tile is target
    assert target.isWindow() and window._fullscreen_presentation.tile is target
    assert int(window.winId()) == window_hwnd
    assert int(target.video.winId()) == video_hwnd
    assert window.current_state()["geometry"] == saved_geometry
    assert window.centralWidget().updatesEnabled()
    assert not window.wall._relayout_timer.isActive()
    if app.platformName() == "windows":
        assert target.size() == window.screen().geometry().size() and window.size() == normal_size
    assert window.wall.fullscreen_tile is target
    assert target.property("fullscreen") is True
    assert target.property("focused") is True
    assert window.wall.visible_tiles() == [target]
    assert not hasattr(target, "fullscreen_danmaku")
    assert not hasattr(target, "fullscreen_danmaku_button")
    assert window._danmaku is None, "普通布局全屏时不应额外连接弹幕"
    assert window.sidebar.isVisible(), "The original sidebar stays in place behind the independent presentation"
    assert window.wall.layout_id == "corner"

    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window._fullscreen_tile is None and window.wall.fullscreen_tile is None, \
        "全屏时再按 F 应与 Esc 一样退出"
    assert window._fullscreen_presentation.tile is None
    assert target.property("fullscreen") is False
    assert target.property("focused") is True
    assert window.centralWidget().updatesEnabled()
    assert not window.wall._relayout_timer.isActive()
    assert int(target.video.winId()) == video_hwnd
    if app.platformName() == "windows":
        assert window.size() == normal_size
    assert wait_tiles_revealed(window, app), "退出全屏后格子要分批回来，等它们到齐"
    assert window.wall.layout_id == "corner" and window.wall.visible_tiles() == tiles
    target.room["live"] = False

    QCursor.setPos(target.mapToGlobal(target.rect().center()))
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window._fullscreen_tile is target

    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert window._fullscreen_tile is None
    assert window.wall.fullscreen_tile is None
    assert window.wall.layout_id == "corner"
    assert window.wall.tiles == tiles
    assert [tile.room["room_id"] for tile in tiles] == room_ids
    assert wait_tiles_revealed(window, app), "退出全屏后格子要分批回来，等它们到齐"
    assert window.wall.visible_tiles() == tiles
    assert window.sidebar.isVisible()

    QTest.mouseClick(tiles[4].fullscreen_button, Qt.LeftButton)
    app.processEvents()
    assert window._fullscreen_tile is tiles[4] and window.wall.visible_tiles() == [tiles[4]]
    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert window._fullscreen_tile is None
    assert wait_tiles_revealed(window, app), "退出全屏后格子要分批回来，等它们到齐"
    assert window.wall.visible_tiles() == tiles

    window.showMaximized()
    app.processEvents()
    assert window.isMaximized()
    QTest.mouseClick(tiles[2].fullscreen_button, Qt.LeftButton)
    app.processEvents()
    assert window._fullscreen_tile is tiles[2]
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window.isMaximized() and window._fullscreen_tile is None, \
        "最大化窗口按 F 退出后应恢复最大化"
    QTest.mouseClick(tiles[2].fullscreen_button, Qt.LeftButton)
    app.processEvents()
    assert window._fullscreen_tile is tiles[2]
    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert window.isMaximized(), "Esc 后应回到进入全屏前的最大化状态"
    window.close()
    print("1+5 全屏快捷键、格子按钮和 Esc 退出：通过")


if __name__ == "__main__":
    main()
