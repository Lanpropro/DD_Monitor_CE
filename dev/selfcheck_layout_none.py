"""回归自检：wall_rooms=None 时，布局变大不能把关注列表自动填上墙。"""
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


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def boom(room_id, quality=250, **_kwargs):  # noqa: ANN001, ARG001
    raise RuntimeError("selfcheck：不联网")


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def main() -> None:
    rooms = [{
        "room_id": str(5000 + index),
        "uname": f"关注{index + 1}",
        "title": "标题",
        "live": True,
        "muted": True,
        "volume": 42,
        "quality": 250,
    } for index in range(28)]

    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    # None 表示没有指定墙面房间；应只由布局补出空位，而不是复制 28 个关注。
    window = MainWindow(rooms, None, layout_id="main2")
    window.setGeometry(-9000, -9000, 1600, 900)
    window.show()
    settle(app, 0.8)
    assert len(window.wall.tiles) == 3, (
        f"None 路径应只有布局空位，实际有 {len(window.wall.tiles)} 个格子")
    assert all(not tile.room.get("room_id") for tile in window.wall.tiles), \
        "None 路径不应自动复制关注到墙面"

    # 模拟用户把前三个房间拖入已有空位，再放大布局。
    for tile, room in zip(window.wall.tiles, rooms[:3]):
        tile.set_room(dict(room))
    window.wall.relayout(force=True)
    settle(app, 0.3)

    def visible_names() -> list[str]:
        return [str(tile.room.get("uname") or "")
                for tile in window.wall.tiles if tile.isVisible()]

    assert visible_names() == [room["uname"] for room in rooms[:3]]
    window._on_layout_changed("main3")
    settle(app, 0.4)
    assert visible_names() == [rooms[index]["uname"] for index in range(3)] + [""], \
        f"main3 新格子必须为空位，实际 {visible_names()}"

    window.close()
    settle(app, 0.2)
    print("wall_rooms=None 布局增长空位回归通过")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
