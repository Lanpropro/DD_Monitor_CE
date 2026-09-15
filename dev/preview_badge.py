"""渲染浮标（圆形镂空 + LIVE + 人数）和悬浮控制条。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.images import load_pixmap  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")

ROOMS = [
    {"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
     "viewers": "54.4万", "muted": True},
    {"room_id": "21452505", "uname": "七海Nana7mi", "title": "和队友最后练一次大米",
     "live": True, "viewers": "12.8万", "muted": True},
    {"room_id": "26376408", "uname": "烛不遥", "title": "看新三国吐槽——", "live": True,
     "viewers": "6.1万", "muted": True},
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

    state = config_module.load()
    bili.set_sessdata(state.get("sessdata", ""))

    # 用真实头像和封面，让截图更接近实际
    for room in ROOMS:
        info = bili.room_info(room["room_id"])
        if info:
            room["face"] = info.get("face") or ""
            room["cover_url"] = info.get("cover_url") or ""
            if info.get("viewers"):
                room["viewers"] = info["viewers"]
            if info.get("uname"):
                room["uname"] = info["uname"]
            if info.get("title"):
                room["title"] = info["title"]
            room["cover"] = load_pixmap(room.get("cover_url", ""))
    account = bili.my_account() or {}

    window = MainWindow(ROOMS, ROOMS, layout_id="2x2", state=state)
    window.setGeometry(-8000, -8000, 1600, 900)
    window.show()
    settle(app, 1.5)
    if account:
        window.sidebar.set_account(account.get("uname", ""),
                                   load_pixmap(account.get("face", "")))
    # 第一格显示悬浮控制条，其余保持只显示浮标
    window.wall.tiles[0].set_controls_visible(True)
    settle(app, 0.5)
    window.grab().save(os.path.join(OUT, "ui_badges.png"), "PNG")
    print("已保存 ui_badges.png")
    badge = window.wall.tiles[0].stream_badge
    print(f"浮标尺寸 {badge.width()}x{badge.height()} 位置在画面左上角")
    window.close()


if __name__ == "__main__":
    main()
