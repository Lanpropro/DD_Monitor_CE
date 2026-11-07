"""回归自检：布局切换时暂缓封面重裁，侧栏同步切换到最终状态。"""
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.widgets import Sidebar  # noqa: E402
from ddm.sidebar_navigation import RAIL_WIDTH

ROOMS = [{"room_id": f"94{index:02d}", "uname": f"主播{index}", "title": "t",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 9)]


def settle(app, seconds: float = 0.3) -> None:
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
    window = Sidebar([dict(room) for room in ROOMS], auto_compact=False)
    window.setGeometry(-9000, -9000, 1100, 700)
    window.show()
    settle(app, 0.5)
    try:
        sidebar = window
        assert sidebar.side == "left", "先决条件：横屏才有收起成窄条这回事"
        item = sidebar.items()[0]
        thumb = item.thumb

        # 先给一张封面，好观察"会不会被重裁"
        source = QPixmap(400, 225)
        source.fill(Qt.darkCyan)
        thumb.set_cover(source)
        settle(app, 0.2)
        before = thumb.cover.pixmap()
        assert before is not None and not before.isNull(), "先决条件：封面该已经画上了"
        before_size = (before.width(), before.height())

        print("\n=== 1. 挂起期间：封面不许被重裁 ===")
        thumb.set_cover_hold(True)
        keep = thumb.cover.pixmap()
        print(f"  挂起中：_cover_hold={thumb._cover_hold}　"
              f"setScaledContents={thumb.cover.hasScaledContents()}")
        assert thumb._cover_hold, "挂起标志该生效"
        assert thumb.cover.hasScaledContents(), \
            "挂起时要让 QLabel 拉伸旧图顶着，否则封面会露白"
        # 故意改尺寸，逼 resizeEvent 走一遍 _render_cover
        thumb.resize(thumb.width() + 30, thumb.height())
        app.processEvents()
        after = thumb.cover.pixmap()
        print(f"  改尺寸后 pixmap 是否被换掉: {after.cacheKey() != keep.cacheKey()}")
        assert after.cacheKey() == keep.cacheKey(), \
            "挂起期间不该重裁封面"
        assert (after.width(), after.height()) == before_size, "尺寸也不该变"

        print("\n=== 2. 解除挂起 + refresh_cover：按新尺寸重裁一次 ===")
        thumb.set_cover_hold(False)
        thumb.refresh_cover()
        settle(app, 0.2)
        fresh = thumb.cover.pixmap()
        print(f"  解除后：_cover_hold={thumb._cover_hold}　"
              f"setScaledContents={thumb.cover.hasScaledContents()}　"
              f"pixmap={fresh.width()}x{fresh.height()}")
        assert not thumb._cover_hold, "解除后标志该复位"
        assert not thumb.cover.hasScaledContents(), \
            "解除后该关掉拉伸，恢复精确裁剪"
        assert (fresh.width(), fresh.height()) == (thumb.width(), thumb.height()), \
            "重裁后封面该跟上条目当前尺寸"

        print("\n=== 3. 收起/展开在返回前完成 ===")
        sidebar.set_collapsed(True, animate=True)
        assert not thumb._cover_hold and not sidebar._collapse_animating
        assert sidebar.width() == theme.SIDEBAR_RAIL_WIDTH + RAIL_WIDTH
        sidebar.set_collapsed(False, animate=False)
        assert not thumb._cover_hold and not sidebar._collapse_animating
        assert sidebar.width() == theme.SIDEBAR_WIDTH + RAIL_WIDTH
        assert thumb.cover.pixmap().size() == thumb.size()
        settle(app, 0.3)
        assert sidebar.width() == theme.SIDEBAR_WIDTH + RAIL_WIDTH
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
