"""离线回归：1+5 布局的格子全屏不能改布局、顺序或房间。"""
import os
import sys

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
    tiles = list(window.wall.tiles)
    room_ids = [tile.room["room_id"] for tile in tiles]
    assert len(tiles) == 6 and all(tile.fullscreen_button.isVisible() for tile in tiles)

    target = tiles[1]
    normal_size = window.size()
    QCursor.setPos(target.mapToGlobal(target.rect().center()))
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window.isFullScreen()
    assert window.wall.fullscreen_tile is target
    assert window.wall.visible_tiles() == [target]
    assert not window.sidebar.isVisible()
    assert window.wall.layout_id == "corner"

    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert not window.isFullScreen() and window.wall.fullscreen_tile is None, \
        "全屏时再按 F 应与 Esc 一样退出"
    if app.platformName() == "windows":
        assert window.size() == normal_size
    assert window.wall.layout_id == "corner" and window.wall.visible_tiles() == tiles

    QCursor.setPos(target.mapToGlobal(target.rect().center()))
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window.isFullScreen()

    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert not window.isFullScreen()
    assert window.wall.fullscreen_tile is None
    assert window.wall.layout_id == "corner"
    assert window.wall.tiles == tiles
    assert [tile.room["room_id"] for tile in tiles] == room_ids
    assert window.wall.visible_tiles() == tiles
    assert window.sidebar.isVisible()

    QTest.mouseClick(tiles[4].fullscreen_button, Qt.LeftButton)
    app.processEvents()
    assert window.isFullScreen() and window.wall.visible_tiles() == [tiles[4]]
    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert not window.isFullScreen() and window.wall.visible_tiles() == tiles

    window.showMaximized()
    app.processEvents()
    assert window.isMaximized()
    QTest.mouseClick(tiles[2].fullscreen_button, Qt.LeftButton)
    app.processEvents()
    assert window.isFullScreen()
    QTest.keyClick(window, Qt.Key_F)
    app.processEvents()
    assert window.isMaximized() and not window.isFullScreen(), \
        "最大化窗口按 F 退出后应恢复最大化"
    QTest.mouseClick(tiles[2].fullscreen_button, Qt.LeftButton)
    app.processEvents()
    assert window.isFullScreen()
    QTest.keyClick(window, Qt.Key_Escape)
    app.processEvents()
    assert window.isMaximized(), "Esc 后应回到进入全屏前的最大化状态"
    window.close()
    print("1+5 全屏快捷键、格子按钮和 Esc 退出：通过")


if __name__ == "__main__":
    main()
