"""回归自检：悬停预览浮层的落点。

用户报：「切成竖屏收缩关注栏时出现了一个悬浮画面」+「关注栏收起时，预览卡片
不应该出现在收缩的卡片里面，应该像紧凑卡片布局一样出现在右侧或者下方」。

根因是 `HoverPreview._place_popup()` 末尾那句 clamp：

    y = max(0, min(y, parent.height() - popup.height()))

竖屏的卡片横排在**顶部**，浮层本该落在它下方；但窗口不够高时（竖屏窗口本来就矮）
这个 clamp 会把 y 硬夹回上边 —— 正好压在那排收起的小卡片身上，看起来就像
「预览塞进了收缩的卡片里」。

这里钉住两条不变量：
  1. 竖屏：浮层在卡片**下方**，和卡片不重叠；
  2. 横屏：浮层在卡片**右侧**探出侧栏。
不管窗口多矮、卡片多靠边都不许被夹回卡片内部。
"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config as config_module  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": f"95{index:02d}", "uname": f"主播{index}", "title": "t",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 6)]


def settle(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def overlaps(a, b) -> bool:
    """两个 QRect 有没有重叠面积。"""
    return a.intersects(b)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    settings = dict(config_module.DEFAULT_SETTINGS)
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS],
                        layout_id="2x2", state={"settings": dict(settings)})
    window.setGeometry(-9000, -9000, 900, 700)
    window.show()
    settle(app, 0.5)
    try:
        preview = window.hover_preview
        item = window.sidebar.items()[0]
        preview._item = item                       # noqa: SLF001
        popup = preview._popup                     # noqa: SLF001

        print("\n=== 1. 竖屏（顶部横栏）：浮层要看得见，且落在卡片下方 ===")
        window.sidebar.side = "top"
        window.sidebar.card_mode = False           # 收起 / 紧凑
        item.thumb.set_thumb_size(True)
        preview._place_popup(item)                 # noqa: SLF001
        card = item.geometry()
        card.moveTopLeft(item.mapTo(popup.parentWidget(), card.topLeft()))
        box = popup.geometry()
        print(f"  窗口={window.width()}x{window.height()}　"
              f"卡片 rect={card.getRect()}　浮层 rect={box.getRect()}")
        print(f"  浮层在卡片下方: {box.top() >= card.bottom()}")
        # 竖屏的第一优先级是**看得见**：浮层整块必须在窗口里（用户报过
        # 「竖屏不显示预览」——就是浮层被摆到窗口外面去了）
        parent_rect = popup.parentWidget().rect()
        assert parent_rect.contains(box), \
            f"竖屏时浮层必须整块落在窗口内，实际 浮层={box.getRect()} 窗口={parent_rect.getRect()}"
        assert box.top() >= card.bottom() - 1, \
            "竖屏时浮层该在卡片下方，不许压回卡片身上"

        print("\n=== 2. 窗口很矮时：可以贴底边，但必须仍然可见 ===")
        window.resize(900, 240)                    # 比"卡片 + 浮层"还矮
        settle(app, 0.3)
        preview._place_popup(item)                 # noqa: SLF001
        box = popup.geometry()
        parent_rect = popup.parentWidget().rect()
        print(f"  窗口高={window.height()}　浮层 rect={box.getRect()}")
        assert box.top() >= 0 and box.bottom() <= parent_rect.height(), \
            "窗口再矮也要保证浮层可见（贴底边可以，跑到外面不行）"

        print("\n=== 3. 横屏（左侧栏）：浮层完全贴在卡片右侧、不覆盖卡片 ===")
        window.resize(900, 700)
        window.sidebar.side = "left"
        settle(app, 0.3)
        preview._place_popup(item)                 # noqa: SLF001
        card = item.geometry()
        card.moveTopLeft(item.mapTo(popup.parentWidget(), card.topLeft()))
        box = popup.geometry()
        print(f"  卡片 right={card.right()}　浮层 left={box.left()}")
        # 用户明确要求「横屏应该在右侧」：浮层不许压住卡片右边那 1/3
        assert box.left() >= card.right() - 1, \
            f"横屏时浮层该完全在卡片右侧，实际 浮层 left={box.left()} 卡片 right={card.right()}"
        assert not overlaps(box, card), "横屏时浮层和卡片不该有重叠"
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
