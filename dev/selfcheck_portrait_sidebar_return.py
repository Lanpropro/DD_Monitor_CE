"""回归自检：竖屏展开横栏后回横屏，关注卡片仍应逐行排列。"""
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


def boom(room_id, quality=250):  # noqa: ANN001, ARG001
    raise RuntimeError("selfcheck：不联网")


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def make_rooms(count: int) -> list[dict]:
    return [{
        "room_id": str(9000 + index),
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
    window = MainWindow(rooms, rooms[:7], layout_id="dm_main4")
    window.setGeometry(-9000, -9000, 1000, 900)
    window.show()
    settle(app, 0.8)

    # 先切竖屏，再明确走一遍用户会操作到的「展开横栏」状态。
    window.resize(900, 1000)
    settle(app, 0.6)
    window.sidebar.set_collapsed(True, animate=False)
    settle(app, 0.2)
    window.sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)

    # 回横屏后，卡片不能继续沿用竖屏横栏时的 x 坐标。
    window.resize(1000, 900)
    settle(app, 0.8)
    sidebar = window.sidebar
    items = sidebar.items()
    print(f"回横屏：侧栏={sidebar.width()}x{sidebar.height()} "
          f"列表={sidebar.list_box.width()}x{sidebar.list_box.height()} "
          f"前 5 张位置={[(item.x(), item.y()) for item in items[:5]]}")
    assert sidebar.side == "left"
    assert not sidebar.list_box.horizontal
    assert sidebar.height() > window.wall.height() * 0.9
    assert sidebar.scroll.maximumHeight() > 10_000
    assert not sidebar.scroll.horizontalScrollBar().isVisible()
    assert all(item.x() == 0 for item in items), "回横屏后卡片必须逐行贴左排列"
    assert all(items[index].y() < items[index + 1].y()
               for index in range(len(items) - 1)), "回横屏后卡片必须逐行排列"

    window.close()
    settle(app, 0.2)
    print("竖屏展开横栏后回横屏的关注列表回归通过")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
