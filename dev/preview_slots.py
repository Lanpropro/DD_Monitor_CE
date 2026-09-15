"""渲染"按布局保留空位"的效果。"""
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

ROOMS = [
    {"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True},
    {"room_id": "21452505", "uname": "七海Nana7mi", "title": "和队友最后练一次大米",
     "live": True, "viewers": "1.8万", "muted": True},
]


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
    deadline = time.time() + 2.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    if window.wall.tiles:
        window.wall.tiles[0].set_controls_visible(True)
    deadline = time.time() + 0.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    path = os.path.join(OUT, "ui_empty_slots.png")
    window.grab().save(path, "PNG")
    print("已保存", path)
    window.close()


if __name__ == "__main__":
    main()
