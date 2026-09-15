"""自查画质切换：把取流函数换成记录器，看点击后到底请求了哪一档。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

CALLS: list[tuple[str, int]] = []


def fake_play_url(room_id, quality=250):        # noqa: ANN001, ANN201
    CALLS.append((str(room_id), int(quality)))
    return f"http://127.0.0.1:9/{quality}.flv", int(quality), "app"


ROOMS = [
    {"room_id": "1001", "uname": "主播A", "title": "房间A", "live": True,
     "viewers": "1万", "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "主播B", "title": "房间B", "live": True,
     "viewers": "2万", "muted": True, "quality": 250},
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
    bili.play_url = fake_play_url            # 打桩，不联网
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    state = dict(config_module.load())
    state["sessdata"] = "dummy"
    window = MainWindow([dict(r) for r in ROOMS], [dict(r) for r in ROOMS],
                        layout_id="main2", state=state)
    window.setGeometry(-8000, -8000, 1200, 700)
    window.show()
    settle(app, 3)

    print("=== 启动后的画质策略 ===")
    for index, tile in enumerate(window.wall.tiles):
        print(f"  格子{index} 房间={tile.room.get('room_id')} 请求={tile.quality}"
              f" 按钮={tile.quality_button.text()}")
    print("  取流调用:", CALLS)

    print("\n=== 手动切换非主画面（格子1）===")
    target = window.wall.tiles[1]
    for quality, label in ((10000, "原画"), (400, "蓝光"), (80, "流畅")):
        CALLS.clear()
        target.set_quality(quality)
        print(f"    点击后 room['quality']={target.room.get('quality')}"
              f" tile.quality={target.quality}")
        settle(app, 2.5)
        requested = [item for item in CALLS if item[0] == "1002"]
        print(f"  点 {label}({quality}): 实际发起请求={requested}"
              f" | tile.quality={target.quality}"
              f" | actual={target.actual_quality}"
              f" | 按钮={target.quality_button.text()}")

    print("\n=== 主格子（格子0）切换 ===")
    main_tile = window.wall.tiles[0]
    CALLS.clear()
    main_tile.set_quality(400)
    settle(app, 2.5)
    print(f"  点蓝光(400): 请求={[c for c in CALLS if c[0] == '1001']}"
          f" | 按钮={main_tile.quality_button.text()}")

    for player in window.players.values():
        player.release()
    window.close()
    print("\n完成")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
