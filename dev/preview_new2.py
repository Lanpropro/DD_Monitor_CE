"""渲染新改动：左上角 LIVE 浮标、侧栏账号栏、导入对话框头像。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import FollowImportDialog  # noqa: E402
from ddm.images import AvatarLoader, load_pixmap  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")


def settle(app, seconds=0.5):
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
    account = bili.my_account() or {}
    print("账号:", account.get("uname"), "| 已登录:", bool(account))

    # 1) 主界面：右上角浮标 + 账号栏
    rooms = []
    for candidate in ("1001", "56237", "1004", "1002", "1003", "8725120"):
        info = bili.room_info(candidate)
        if info and info["live"] and len(rooms) < 4:
            info["muted"] = True
            rooms.append(info)
    print("直播房间:", [room["uname"] for room in rooms])

    window = MainWindow(rooms, rooms, layout_id="2x2", state=state)
    window.setGeometry(-8000, -8000, 1600, 900)
    window.show()
    settle(app, 3.0)          # 等状态轮询把人数和头像拉回来

    if account:
        pixmap = load_pixmap(account.get("face", ""))
        window.sidebar.set_account(account.get("uname", ""), pixmap)
    if window.wall.tiles:
        window.wall.tiles[0].set_controls_visible(True)   # 展示悬浮控制条
    settle(app, 0.6)
    window.grab().save(os.path.join(OUT, "ui_with_account.png"), "PNG")
    print("已保存 ui_with_account.png")

    # 2) 导入对话框（带真实头像）
    follows = []
    try:
        follows = bili.follow_rooms()
    except Exception as error:  # noqa: BLE001
        print("拉取关注失败:", error)
    if follows:
        dialog = FollowImportDialog(follows[:60], set(), window)
        dialog.setGeometry(-8000, -8000, 520, 620)
        dialog.show()
        loader = AvatarLoader({str(room["room_id"]): room.get("face")
                               for room in follows[:60] if room.get("face")})
        loader.loaded.connect(dialog.set_avatar)
        loader.start()
        settle(app, 8)
        dialog._check_live()
        settle(app, 0.4)
        dialog.grab().save(os.path.join(OUT, "dialog_import_avatars.png"), "PNG")
        print(f"已保存 dialog_import_avatars.png（{len(follows)} 个关注）")
        dialog.close()

    window.close()


if __name__ == "__main__":
    main()
