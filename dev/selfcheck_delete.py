"""自检：多选删除时会不会冒出新窗口（监控顶层窗口数量）。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DDM_NO_SAVE', '1')  # 自检脚本不要动真实配置
sys.path.insert(0, REPO)

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例标题", "live": True,
     "viewers": "3.1万", "muted": True},
    {"room_id": "1002", "uname": "示例主播B", "title": "练大米", "live": True,
     "viewers": "1.8万", "muted": True},
    {"room_id": "1003", "uname": "示例主播C", "title": "吐槽", "live": True,
     "viewers": "6千", "muted": True},
]


def snapshot() -> set:
    return {f"{type(w).__name__}#{id(w)}" for w in QApplication.topLevelWidgets() if w.isVisible()}


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow(list(ROOMS), [dict(room) for room in ROOMS], layout_id="auto")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    deadline = time.time() + 8
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.1)

    before = snapshot()
    print("删除前可见顶层窗口:", len(before))

    window.sidebar.set_select_mode(True)
    for item in window.sidebar._items[:2]:        # noqa: SLF001
        item.check.setChecked(True)
    window.sidebar._update_batch_label()          # noqa: SLF001
    app.processEvents()
    print("已勾选:", sum(1 for i in window.sidebar._items if i.is_checked()))  # noqa: SLF001

    print("触发删除…")
    window.sidebar._emit_delete()                 # noqa: SLF001
    deadline = time.time() + 3
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.1)

    after = snapshot()
    new = after - before
    print("删除后可见顶层窗口:", len(after))
    print("新出现的窗口:", new or "（没有）")
    print("剩余关注:", len(window.sidebar.rooms()), "| 画面墙格子:", len(window.wall.tiles),
          "| 墙上有房间的格子:", len(window.wall.visible_tiles()))
    window.close()


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
