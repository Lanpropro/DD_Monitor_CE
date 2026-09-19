"""自检：浮标圆点遮罩、音量数字、缓冲动画、控件栏、悬浮窗已移除。"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

NOW = int(time.time())
ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例标题", "live": True,
     "viewers": "3.1万", "muted": True, "volume": 55, "live_start_ts": NOW - 4512},
]


def boom(room_id, quality=250, **_kwargs):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class IdlePoller(QThread):
    """自检里别真去问接口：假房间号会被查成「未开播」，把状态机搞乱。"""

    updated = Signal(dict)

    def __init__(self, room_ids=None, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids or [])

    def run(self) -> None:
        return


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
    bili.play_url = boom
    app_module.StatusPoller = IdlePoller
    app_module.StatsPoller = IdlePoller
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

    print("\n=== 直播时长只保留浮标，并且和别的浮标一样自动隐藏 ===")
    tile.start_elapsed_timer()
    settle(app, 1.1)
    print(f"  没悬停时：浮标 {tile.time_badge.text!r} 可见 {tile.time_badge.isVisible()}"
          f" | 信息条里还有 time_label: {hasattr(tile, 'time_label')}")
    assert tile.time_badge.text, "在播、又知道开播时间时要算出时长"
    assert not tile.time_badge.isVisible(), \
        "用户要求：鼠标不在格子上时，右下角的时长不能一直挂着"

    tile.set_controls_visible(True)          # 鼠标移进格子
    settle(app, 0.2)
    print(f"  悬停时：可见 {tile.time_badge.isVisible()}"
          f"（LIVE 浮标 {tile.stream_badge.isVisible()}）")
    assert tile.time_badge.isVisible(), "鼠标在格子上时要和 LIVE 浮标一起露出来"

    tile.set_controls_visible(False)         # 鼠标移开
    settle(app, 0.2)
    print(f"  移开之后：可见 {tile.time_badge.isVisible()}")
    assert not tile.time_badge.isVisible(), "移开要跟着收起来（和别的浮标一致）"

    tile.set_live(False)                     # 下播
    settle(app, 0.2)
    print(f"  下播后：可见 {tile.time_badge.isVisible()} 计时器在跑={tile._elapsed_timer.isActive()}")
    assert not tile.time_badge.isVisible() and not tile._elapsed_timer.isActive()
    tile.set_live(True)

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
