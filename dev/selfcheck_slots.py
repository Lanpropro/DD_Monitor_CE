"""自检：布局是否按格子数保留空位。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [
    {"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True},
    {"room_id": "21452505", "uname": "七海Nana7mi", "title": "练大米", "live": True,
     "viewers": "1.8万", "muted": True},
]


def describe(window) -> str:
    used = sum(1 for tile in window.wall.tiles if tile.room.get("room_id"))
    empty = len(window.wall.tiles) - used
    visible = sum(1 for tile in window.wall.tiles if tile.isVisible())
    return f"格子 {len(window.wall.tiles)}（有房间 {used} / 空位 {empty}，可见 {visible}）"


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow(list(ROOMS), [dict(room) for room in ROOMS], layout_id="3x3")
    window.setGeometry(-8000, -8000, 1600, 900)
    window.show()
    deadline = time.time() + 3
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.1)
    print("3×3 布局、2 个房间 ->", describe(window))

    window.wall.set_layout("4x4")
    app.processEvents()
    print("切到 4×4 ->", describe(window))

    window.wall.set_layout("1x2")
    app.processEvents()
    print("切到左右两分 ->", describe(window))

    window.wall.set_layout("auto")
    app.processEvents()
    print("切回自动 ->", describe(window))

    first = window.wall.tiles[0]
    print("空位提示文字:", [tile.cover.text() for tile in window.wall.tiles
                            if not tile.room.get("room_id")][:2] or "（没有空位）")
    for player in window.players.values():
        player.release()
    window.close()


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
