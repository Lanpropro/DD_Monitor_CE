"""渲染：浮标圆点、信息条音量条、置顶三角标、悬浮窗。"""
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
    {"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True, "volume": 55, "live_start_ts": NOW - 4512},
    {"room_id": "21452505", "uname": "七海Nana7mi", "title": "和队友最后练一次大米",
     "live": True, "viewers": "1.8万", "muted": True, "volume": 42, "live_start_ts": NOW - 890},
    {"room_id": "26376408", "uname": "烛不遥", "title": "看新三国吐槽——", "live": True,
     "viewers": "6.1万", "muted": True, "volume": 70, "live_start_ts": NOW - 12800},
    {"room_id": "22603245", "uname": "永雏塔菲", "title": "守望先锋（9）", "live": False,
     "muted": True},
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
                        layout_id="2x2")
    window.setGeometry(-8000, -8000, 1500, 840)
    window.show()
    settle(app, 1.2)
    for tile in window.wall.tiles:
        tile.start_elapsed_timer()
    if len(window.wall.tiles) > 1:
        window.wall.tiles[1].set_status("连接中…")      # 展示缓冲动画
    window.wall.tiles[0].set_watched("7429")            # 展示"看过"人数
    window.sidebar.toggle_pin(window.sidebar.rooms()[1])  # 展示置顶三角标
    window.wall.tiles[0].set_controls_visible(True)
    settle(app, 1.2)
    window.grab().save(os.path.join(OUT, "ui_v3.png"), "PNG")
    print("已保存 ui_v3.png")
    window.close()


if __name__ == "__main__":
    main()

