"""自检：点击画质 → 重新取流 → 实际画质是否符合请求。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    state = config_module.load()
    bili.set_sessdata(state.get("sessdata", ""))
    print("登录态:", bool(state.get("sessdata")), "| my_uid:", bili.my_uid())

    room = None
    for room_id in [str(item) for item in state.get("rooms", [])] + \
            ["6154037", "56237", "21733448", "22603245"]:
        info = bili.room_info(room_id)
        if info and info["live"]:
            room = info
            break
    if room is None:
        print("当前没有正在直播的房间")
        return
    print(f"测试房间 {room['room_id']}（{room['uname']}）")

    window = MainWindow([room], [dict(room)], layout_id="1x1", state=state)
    window.setGeometry(-8000, -8000, 900, 560)
    window.show()
    settle(app, 10)                       # 等首帧
    tile = window.wall.tiles[0]
    player = window.players.get(tile)
    print(f"初始: 请求={tile.quality} 实际={tile.actual_quality} 按钮={tile.quality_button.text()}"
          f" 状态={player.state if player else '-'}")

    for target, label in ((10000, "原画"), (250, "超清 720P")):
        tile.set_quality(target)          # 等同于点菜单
        settle(app, 8)
        player = window.players.get(tile)
        print(f"切到 {label}: 请求={tile.quality} 实际={tile.actual_quality}"
              f" 按钮={tile.quality_button.text()} 状态={player.state if player else '-'}"
              f" 分辨率={player.player.video_get_size(0) if player else '-'}")

    for p in window.players.values():
        p.release()
    window.close()


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
