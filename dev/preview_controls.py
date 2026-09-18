"""渲染：直播时长浮标、悬浮控制条、右键菜单（含音量滑条）。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")
NOW = int(time.time())

ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例标题", "live": True,
     "viewers": "3.1万", "muted": True, "volume": 60, "live_start_ts": NOW - 3725},
    {"room_id": "1002", "uname": "示例主播B", "title": "示例标题二",
     "live": True, "viewers": "1.8万", "muted": True, "live_start_ts": NOW - 890},
]


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="1x2")
    window.setGeometry(-8000, -8000, 1500, 820)
    window.show()
    settle(app, 1.5)

    for tile in window.wall.tiles:
        tile.start_elapsed_timer()
    window.wall.tiles[0].set_controls_visible(True)
    settle(app, 1.2)
    window.grab().save(os.path.join(OUT, "ui_controls.png"), "PNG")
    print("已保存 ui_controls.png；时长浮标:", window.wall.tiles[0].time_badge.text)

    menu = window.wall.tiles[0].build_menu()
    menu.setGeometry(-8000, -8000, 220, 260)
    menu.show()
    settle(app, 0.6)
    menu.grab().save(os.path.join(OUT, "ui_tile_menu.png"), "PNG")
    print("已保存 ui_tile_menu.png")
    menu.close()
    window.close()


if __name__ == "__main__":
    main()
