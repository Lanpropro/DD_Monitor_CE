"""回归自检：紧凑（长条）布局下的悬停预览浮层——位置和大小。

背景：非紧凑卡片上那块封面是**铺满条目**的（约 206x116），预览直接播在里面最自然；
紧凑（长条）卡片的缩略图只有 `NavThumb.LIST_HEIGHT`(48) 高，塞进去画面被压扁。
所以紧凑 / 竖屏改成弹一个浮层，尺寸和**非紧凑卡片上的封面**一样。

用户要的三点：
  1. 横屏：浮层压在卡片**右侧 1/3**（左边界在卡片右边 1/3 处，其余探出侧栏）；
  2. 垂直**居中**于卡片；
  3. 竖屏：改成**向下弹出**。
"""
import os
import sys
import time

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import NavThumb  # noqa: E402

ROOMS = [{"room_id": f"99{index:02d}", "uname": f"主播{index}", "title": f"标题{index}",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 9)]


def settle(app, seconds: float = 0.4) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS], state={})
    window.setGeometry(-9000, -9000, 1300, 800)
    window.show()
    settle(app, 0.6)
    try:
        sidebar = window.sidebar
        preview = window.hover_preview
        popup = preview._popup                     # noqa: SLF001

        print("=== 1. 横屏 + 紧凑（长条）列表：该弹浮层 ===")
        sidebar.set_compact_policy(card_mode=False, auto_compact=False,
                                  compact_threshold=99)
        settle(app, 0.5)
        assert sidebar.side == "left" and not sidebar.card_mode
        assert preview._needs_popup(), "紧凑列表该用浮层，不该塞进 48px 的缩略图"  # noqa: SLF001

        # 挑一个上下都留得下、不会被 clamp 干扰的条目
        item = None
        for candidate in sidebar.items():
            origin = candidate.mapTo(popup.parentWidget(), QPoint(0, 0))
            if origin.y() >= 40 and origin.y() + candidate.height() + 80 < window.height():
                item = candidate
                break
        assert item is not None, "没找到位置合适的条目，窗口开大一点"
        preview._place_popup(item)                 # noqa: SLF001
        settle(app, 0.2)
        origin = item.mapTo(popup.parentWidget(), QPoint(0, 0))
        want_x = origin.x() + item.width() * 2 // 3     # 左边界落在卡片右侧 1/3 处
        want_y = origin.y() + (item.height() - popup.height()) // 2
        print(f"  卡片 {item.width()}x{item.height()} @({origin.x()},{origin.y()})　"
              f"卡片右侧 1/3 处 x={want_x}　侧栏宽={sidebar.width()}")
        print(f"  浮层 {popup.width()}x{popup.height()} @({popup.x()},{popup.y()})　"
              f"期望 @({want_x},{want_y})")
        assert popup.width() == item.width(), \
            f"浮层该和卡片一样宽：{popup.width()} vs {item.width()}"
        assert popup.height() == NavThumb.HEIGHT, \
            f"浮层该和非紧凑卡片上的封面一样高：{popup.height()} vs {NavThumb.HEIGHT}"
        assert abs(popup.x() - want_x) <= 1, \
            f"横向该压在卡片右侧 1/3：得到 {popup.x()}，期望 {want_x}"
        assert abs(popup.y() - want_y) <= 1, \
            f"纵向该居中于卡片：得到 {popup.y()}，期望 {want_y}"
        # 关键不变量：左边界落在卡片右边 1/3 之后
        assert popup.x() >= origin.x() + item.width() * 2 // 3 - 1, \
            "浮层左边界该在卡片右侧 1/3 区域里"

        print("\n=== 2. 非紧凑（卡片）列表：还是播在缩略图里，不弹浮层 ===")
        sidebar.set_compact_policy(card_mode=True, auto_compact=False,
                                  compact_threshold=99)
        settle(app, 0.5)
        assert sidebar.card_mode
        assert not preview._needs_popup(), \
            "非紧凑的封面本来就够大，不该再弹浮层"      # noqa: SLF001
        print(f"  非紧凑 card_mode={sidebar.card_mode}　需要浮层="
              f"{preview._needs_popup()}")              # noqa: SLF001

        print("\n=== 3. 竖屏 + 紧凑：改成向下弹出 ===")
        sidebar.set_compact_policy(card_mode=False, auto_compact=False,
                                  compact_threshold=99)
        window.resize(560, 1000)
        settle(app, 0.6)
        assert window.orientation == "portrait", window.orientation
        assert sidebar.side == "top"
        assert preview._needs_popup()               # noqa: SLF001
        item = sidebar.items()[0]
        preview._place_popup(item)                  # noqa: SLF001
        settle(app, 0.2)
        origin = item.mapTo(popup.parentWidget(), QPoint(0, 0))
        print(f"  卡片 {item.width()}x{item.height()} @({origin.x()},{origin.y()})　"
              f"浮层 @({popup.x()},{popup.y()}) 高={popup.height()}")
        assert popup.x() == origin.x(), \
            f"竖屏该和卡片左对齐：{popup.x()} vs {origin.x()}"
        assert popup.y() >= origin.y() + item.height(), \
            f"竖屏该向下弹（在卡片下方）：{popup.y()} vs 卡底 {origin.y() + item.height()}"
        assert popup.y() <= origin.y() + item.height() + 20, "向下弹的缝别太大"
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
