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

        print("\n=== 1. 竖屏（顶部横栏）：浮层必须落在卡片下方、不与卡片重叠 ===")
        window.sidebar.side = "top"
        window.sidebar.card_mode = False           # 收起 / 紧凑
        item.thumb.set_thumb_size(True)
        preview._place_popup(item)                 # noqa: SLF001
        card = item.geometry()
        card.moveTopLeft(item.mapTo(popup.parentWidget(), card.topLeft()))
        box = popup.geometry()
        print(f"  卡片 rect={card.getRect()}　浮层 rect={box.getRect()}")
        print(f"  浮层在卡片下方: {box.top() >= card.bottom()}")
        assert box.top() >= card.bottom() - 1, \
            "竖屏时浮层该在卡片下方，不许压回卡片身上"
        assert not overlaps(box, card), "浮层和卡片不该有重叠"

        print("\n=== 2. 窗口很矮时也不许被夹回卡片 ===")
        window.resize(900, 240)                    # 比"卡片 + 浮层"还矮
        settle(app, 0.3)
        preview._place_popup(item)                 # noqa: SLF001
        card = item.geometry()
        card.moveTopLeft(item.mapTo(popup.parentWidget(), card.topLeft()))
        box = popup.geometry()
        print(f"  窗口高={window.height()}　卡片 bottom={card.bottom()}　浮层 top={box.top()}")
        assert box.top() >= card.bottom() - 1, \
            "窗口再矮也不许把浮层夹回卡片内部（宁可压出窗口底边）"

        print("\n=== 3. 横屏（左侧栏）：浮层探到卡片右侧 ===")
        window.resize(900, 700)
        window.sidebar.side = "left"
        settle(app, 0.3)
        preview._place_popup(item)                 # noqa: SLF001
        card = item.geometry()
        card.moveTopLeft(item.mapTo(popup.parentWidget(), card.topLeft()))
        box = popup.geometry()
        print(f"  卡片 right={card.right()}　浮层 left={box.left()}")
        assert box.left() > card.left(), "横屏时浮层该往右摆、探出侧栏"
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
