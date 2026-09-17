"""回归自检：跨屏切竖屏不产生悬浮格子，已有播放器继续显示画面。"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module  # noqa: E402
from ddm import bili, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import Tile  # noqa: E402


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


class SpyPlayer:
    def __init__(self):
        self.bind_count = 0

    def bind(self) -> None:
        self.bind_count += 1

    def release(self) -> None:
        return


def boom(room_id, quality=250):  # noqa: ANN001, ARG001
    raise RuntimeError("selfcheck：不联网")


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def make_rooms(count: int) -> list[dict]:
    return [{
        "room_id": str(10000 + index),
        "uname": f"关注{index + 1}",
        "title": "标题",
        "live": True,
        "viewers": "1",
        "muted": True,
        "volume": 42,
        "quality": 250,
    } for index in range(count)]


def main() -> None:
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    rooms = make_rooms(28)
    window = MainWindow(rooms, rooms[:3], layout_id="dm_main3")
    window.setGeometry(-9000, -9000, 1600, 900)
    window.show()
    settle(app, 0.8)

    tile = window.wall.tiles[0]
    spy = SpyPlayer()
    window.players[tile] = spy
    tile.video.show()

    window.resize(914, 1463)
    settle(app, 0.8)
    visible_strays = [widget for widget in app.topLevelWidgets()
                      if isinstance(widget, Tile) and widget.isVisible()]
    print(f"竖屏：格子={len(window.wall.tiles)} 顶层可见 Tile={len(visible_strays)} "
          f"播放器绑定={spy.bind_count} 视频可见={tile.video.isVisible()}")
    assert window.orientation == "portrait"
    assert all(item.parentWidget() is window.wall for item in window.wall.tiles), \
        "竖屏手动摆放的格子必须预先挂在 WallGrid 下"
    assert not visible_strays, "竖屏切换不能产生顶层悬浮格子"
    assert spy.bind_count > 0, "方向切换后播放器必须重新绑定视频区"
    assert tile.video.isVisible(), "方向切换后已有直播的视频区必须保持可见"

    window.resize(1600, 900)
    settle(app, 0.8)
    print(f"回横屏：方向={window.orientation} 播放器绑定={spy.bind_count} "
          f"视频可见={tile.video.isVisible()}")
    assert window.orientation == "landscape"
    assert spy.bind_count > 1, "回横屏也必须重新绑定播放器"
    assert tile.video.isVisible(), "回横屏后已有直播的视频区必须保持可见"

    window.close()
    settle(app, 0.2)
    print("跨屏方向切换原生窗口/播放器回归通过")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
