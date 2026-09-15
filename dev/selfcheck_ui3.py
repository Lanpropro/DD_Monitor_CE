"""自检：浮标圆点遮罩、音量数字、缓冲动画、控件栏、悬浮窗已移除。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

NOW = int(time.time())
ROOMS = [
    {"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True, "volume": 55, "live_start_ts": NOW - 4512},
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

    window = MainWindow([dict(r) for r in ROOMS], [dict(r) for r in ROOMS], layout_id="1x1")
    window.setGeometry(-8000, -8000, 1200, 700)
    window.show()
    settle(app, 1.2)
    tile = window.wall.tiles[0]

    print("=== 浮标（圆孔里应有实心圆点）===")
    from PySide6.QtCore import QPoint
    badge = tile.stream_badge
    dot_center = QPoint(4 + 8, 12)
    print(f"  尺寸 {badge.width()}x{badge.height()} | 遮罩包含圆点中心:",
          badge.mask().contains(dot_center))

    print("\n=== 音量条数字 ===")
    print(f"  初始 {tile.volume_label.text()}（滑条 {tile.volume_slider.value()}）")
    tile.volume_slider.setValue(72)
    print(f"  拖动后 {tile.volume_label.text()}（房间记录 {tile.room.get('volume')}）")

    print("\n=== 缓冲动画 ===")
    tile.set_status("连接中…")
    settle(app, 0.3)
    print(f"  可见 {tile.spinner.isVisible()} | 动画有效 {tile.spinner._movie.isValid()}"
          f" | 文案 {tile.spinner._text.text()!r} | 尺寸 {tile.spinner.width()}x{tile.spinner.height()}")
    tile.set_video_active(True)
    print(f"  播放后隐藏 {not tile.spinner.isVisible()}")

    print("\n=== 直播时长只保留浮标 ===")
    tile.start_elapsed_timer()
    settle(app, 1.1)
    print(f"  浮标 {tile.time_badge.text!r} 可见 {tile.time_badge.isVisible()}"
          f" | 信息条里还有 time_label: {hasattr(tile, 'time_label')}")

    print("\n=== 控制条 ===")
    labels = [button.text() for button in tile.controls.findChildren(type(tile.close_button))]
    print(f"  按钮: {labels}")
    print(f"  容器有遮罩: {not tile.controls.mask().isEmpty()}")

    print("\n=== 账号栏与底部按钮 ===")
    print(f"  账号栏高度 {window.sidebar.account_row.height()} | 添加按钮高度 "
          f"{window.sidebar.add_button.height()} | 导入按钮高度 {window.sidebar.import_button.height()}")

    print("\n=== 悬浮窗已移除 ===")
    print("  ddm/floating.py 存在:", os.path.isfile(os.path.join(REPO, "ddm", "floating.py")))
    print("  tile 有 popOutRequested:", hasattr(tile, "popOutRequested"))

    window.close()
    print("\n完成")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
