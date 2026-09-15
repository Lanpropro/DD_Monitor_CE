"""渲染新改动：空状态、批量选择、布局选择器（缩略图）。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DDM_NO_SAVE', '1')  # 自检脚本不要动真实配置
sys.path.insert(0, REPO)

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import LayoutPicker  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")

SAMPLE = [
    {"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True},
    {"room_id": "21452505", "uname": "七海Nana7mi", "title": "和队友最后练一次大米",
     "live": True, "viewers": "1.8万", "muted": True},
    {"room_id": "26376408", "uname": "烛不遥", "title": "看新三国吐槽——", "live": True,
     "viewers": "6千", "muted": True},
    {"room_id": "22603245", "uname": "永雏塔菲", "title": "守望先锋/鬼武者（9）", "live": False,
     "muted": True},
    {"room_id": "56237", "uname": "还有醒着的么", "title": "一起英灵神殿开尼2！", "live": False,
     "muted": True},
]


def settle(app, seconds=0.45):
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

    # 1) 空状态
    empty = MainWindow([], [])
    empty.setGeometry(-8000, -8000, 1400, 820)
    empty.show()
    settle(app)
    empty.grab().save(os.path.join(OUT, "empty_state.png"), "PNG")
    print("已保存 empty_state.png")
    empty.close()
    settle(app, 0.2)

    # 2) 批量选择
    window = MainWindow(list(SAMPLE), SAMPLE[:4], layout_id="2x2")
    window.setGeometry(-8000, -8000, 1400, 820)
    window.show()
    settle(app)
    window.sidebar.set_select_mode(True)
    for index, item in enumerate(window.sidebar._items):     # noqa: SLF001
        if index in (1, 3):
            item.check.setChecked(True)
    window.sidebar._update_batch_label()                     # noqa: SLF001
    settle(app, 0.3)
    window.grab().save(os.path.join(OUT, "sidebar_batch.png"), "PNG")
    print("已保存 sidebar_batch.png")
    window.sidebar.set_select_mode(False)

    # 3) 布局选择器
    picker = LayoutPicker("2x2")
    picker.setGeometry(-8000, -8000, 449, 391)
    picker.show()
    settle(app, 0.4)
    picker.grab().save(os.path.join(OUT, "layout_picker.png"), "PNG")
    print("已保存 layout_picker.png")
    picker.close()
    window.close()


if __name__ == "__main__":
    main()
