"""自查：弹幕条数上限、粉丝牌渲染、设置里的保留条数、自定义排序持久化。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402
from ddm.widgets import DanmakuPanel, Sidebar  # noqa: E402


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class SilentPoller(QThread):
    """自检里别真的轮询，免得真去查房间号。"""

    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


ROOMS = [
    {"room_id": "1001", "uname": "甲", "title": "开播中", "live": True, "muted": True},
    {"room_id": "1002", "uname": "乙", "title": "没开播", "live": False, "muted": True},
    {"room_id": "1003", "uname": "丙", "title": "开播中", "live": True, "muted": True},
    {"room_id": "1004", "uname": "丁", "title": "没开播", "live": False, "muted": True},
]

MEDAL_COLOR = "#5c7cfa"


def settle(app, seconds):        # noqa: ANN001, ANN201
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def order(sidebar) -> list[str]:        # noqa: ANN001, ANN201
    return [str(item.room.get("room_id")) for item in sidebar.items()]


def medal_pixels(image, color: str) -> int:        # noqa: ANN001, ANN201
    """数一数截图里有多少像素是粉丝牌的颜色。"""
    want = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
    hits = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if abs(pixel.red() - want[0]) <= 10 \
                    and abs(pixel.green() - want[1]) <= 10 \
                    and abs(pixel.blue() - want[2]) <= 10:
                hits += 1
    return hits


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [], layout_id="1x2")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    settle(app, 1.0)

    print("=== 1. 弹幕条数上限：超了从最早的开始丢 ===")
    panel = window.wall.danmaku
    panel.set_max_blocks(50)
    for index in range(80):
        panel.add_event({"kind": "danmaku", "uname": f"用户{index}", "text": f"第{index}条"})
    text = panel.body.toPlainText()
    print(f"  上限={panel.max_blocks} 实际留着={len(panel._blocks)} "        # noqa: SLF001
          f"最早一条={panel._blocks[0]['uname']}")                          # noqa: SLF001
    assert panel.max_blocks == 50
    assert len(panel._blocks) == 50, len(panel._blocks)                     # noqa: SLF001
    assert panel._blocks[0]["uname"] == "用户30"                            # noqa: SLF001
    assert panel._blocks[-1]["uname"] == "用户79"                           # noqa: SLF001
    assert "第79条" in text and "第29条" not in text

    print("=== 2. 设置里的「最多保留」能实时改到面板上 ===")
    dialog = SettingsDialog(window.settings, window.shortcuts)
    dialog.danmaku_page.keep_spin.setValue(60)
    values = dialog.settings()
    print(f"  设置窗口 ={values['danmaku_max_blocks']} 条  默认="
          f"{config_module.DEFAULT_SETTINGS['danmaku_max_blocks']} 条")
    assert values["danmaku_max_blocks"] == 60
    window.settings.update(values)
    window.apply_danmaku_settings()
    print(f"  面板上限={panel.max_blocks} 实际留着={len(panel._blocks)}")     # noqa: SLF001
    assert panel.max_blocks == 60
    dialog.danmaku_page.reset()
    assert dialog.danmaku_page.keep_spin.value() == \
        config_module.DEFAULT_SETTINGS["danmaku_max_blocks"]
    dialog.close()
    window.settings["danmaku_max_blocks"] = 50
    window.apply_danmaku_settings()

    print("=== 3. 粉丝牌：新到的弹幕也要画成色块 ===")
    fresh = DanmakuPanel()
    fresh.resize(420, 240)
    fresh.show()
    fresh.add_event({"kind": "danmaku", "uname": "老粉", "text": "牌子要画出来",
                     "medal": {"name": "绿冻", "level": "12", "color": MEDAL_COLOR}})
    settle(app, 0.4)
    keys = [key for key in fresh._images if key.startswith("medal:")]       # noqa: SLF001
    assert keys, "粉丝牌图片应该已经生成"
    resource = fresh.body.document().resource(QTextDocument.ImageResource, QUrl(keys[0]))
    hits = medal_pixels(fresh.grab().toImage(), MEDAL_COLOR)
    print(f"  粉丝牌图片={keys[0]} 已注册={resource is not None} 色块像素={hits}")
    assert resource is not None and not resource.isNull(), "粉丝牌图片要注册进文档"
    assert hits > 100, f"粉丝牌应该画成实心色块，现在只有 {hits} 个像素"
    fresh.close()

    print("=== 4. 自定义排序：切走再切回、重开都还在 ===")
    sidebar = window.sidebar
    print(f"  初始={order(sidebar)}")
    assert sidebar.reorder_item("1004", 0)
    custom = order(sidebar)
    print(f"  拖过之后={custom}")
    assert custom == ["1004", "1001", "1002", "1003"], custom
    assert sidebar.custom_order == custom, sidebar.custom_order
    sidebar.set_sort_mode("live")
    print(f"  开播优先={order(sidebar)}")
    assert order(sidebar) == ["1001", "1003", "1004", "1002"], order(sidebar)
    sidebar.set_sort_mode("imported")
    sidebar.set_sort_mode("custom")
    print(f"  切回自定义={order(sidebar)}")
    assert order(sidebar) == custom, "切回自定义不能把拖出来的顺序冲掉"

    state = window.current_state()
    assert state["custom_order"] == custom, state["custom_order"]
    reopened = Sidebar([dict(room) for room in ROOMS])
    reopened.set_import_order(state["import_order"])
    reopened.set_custom_order(state["custom_order"])
    reopened.set_sort_mode(str(state["sort"]))
    print(f"  重开之后={order(reopened)}")
    assert order(reopened) == custom, order(reopened)

    sidebar.apply_pins(["1002"])
    print(f"  置顶 1002 之后={order(sidebar)}")
    assert order(sidebar) == ["1002", "1004", "1001", "1003"], order(sidebar)
    sidebar.toggle_pin({"room_id": "1002"})
    assert order(sidebar) == custom, order(sidebar)

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
