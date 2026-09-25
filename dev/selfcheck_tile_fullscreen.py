"""离线回归：1+5 布局的格子全屏不能改布局、顺序或房间。"""
import os
import sys
import time

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QCursor, QPixmap
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


def wait_cover_released(window, app, timeout: float = 3.0) -> bool:
    """等遮挡层自己走掉。

    它现在是「保持 → 淡出 → 释放」三段，总时长还取决于抓屏耗时（4K 上抓一张
    全屏就要 40 ms 上下），所以不能钉死等某个毫秒数。这里要的是它**一定会**
    自己释放，而不是漏在那里不走。
    """
    end = time.time() + timeout
    while time.time() < end:
        if window._fullscreen_cover is None:
            return True
        app.processEvents()
        time.sleep(0.02)
    return window._fullscreen_cover is None


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
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner")
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    if app.platformName() == "windows":
        # 本地 CI 没有可截取的交互桌面；用一张有效画面检查遮挡与释放时序。
        frame = QPixmap(32, 32)
        frame.fill(Qt.darkGray)
        captures = []
        def grab_frame():
            captures.append(True)
            return frame, window.screen().geometry()
        window._grab_fullscreen_frame = grab_frame
    tiles = list(window.wall.tiles)
    room_ids = [tile.room["room_id"] for tile in tiles]
    assert len(tiles) == 6 and all(tile.fullscreen_button.isVisible() for tile in tiles)

    target = tiles[1]
    normal_size = window.size()
    saved_geometry = window.current_state()["geometry"]
    window_hwnd = int(window.winId())
    QCursor.setPos(target.mapToGlobal(target.rect().center()))
    video_hwnd = int(target.video.winId())
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window._fullscreen_tile is target
    if app.platformName() == "windows":
        assert captures
        assert window._fullscreen_cover is None or window._fullscreen_cover_timer.isActive()
    assert window.isFullScreen() or window._native_fullscreen_state is not None
    assert int(window.winId()) == window_hwnd
    assert int(target.video.winId()) == video_hwnd
    assert window.current_state()["geometry"] == saved_geometry
    assert window.centralWidget().updatesEnabled()
    assert not window.wall._relayout_timer.isActive()
    if app.platformName() == "windows":
        assert window.size() == app.primaryScreen().geometry().size()
    assert window.wall.fullscreen_tile is target
    assert window.wall.visible_tiles() == [target]
    assert not window.sidebar.isVisible()
    assert window.wall.layout_id == "corner"
    if app.platformName() == "windows":
        assert wait_cover_released(window, app), "切换后旧画面的遮挡层必须自动释放"

    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window._fullscreen_tile is None and window.wall.fullscreen_tile is None, \
        "全屏时再按 F 应与 Esc 一样退出"
    if app.platformName() == "windows":
        assert len(captures) >= 2
        assert window._fullscreen_cover is None or window._fullscreen_cover_timer.isActive()
    assert window._native_fullscreen_state is None
    assert window.centralWidget().updatesEnabled()
    assert not window.wall._relayout_timer.isActive()
    assert int(target.video.winId()) == video_hwnd
    if app.platformName() == "windows":
        assert window.size() == normal_size
    assert wait_tiles_revealed(window, app), "退出全屏后格子要分批回来，等它们到齐"
    assert window.wall.layout_id == "corner" and window.wall.visible_tiles() == tiles

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
    window._clear_fullscreen_cover()
    assert window._fullscreen_cover is None
    assert not window._fullscreen_cover_timer.isActive()
    window.close()
    print("1+5 全屏快捷键、格子按钮和 Esc 退出：通过")


if __name__ == "__main__":
    main()
