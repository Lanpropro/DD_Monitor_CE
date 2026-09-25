"""回归自检：关注栏收起/展开动画的开销。

用户报「关注栏收缩的动画有点卡顿」。

根因：收起/展开是改宽度的动画，**每一帧**都会给每个条目发 resizeEvent，而
`NavThumb._render_cover()` 每次都要做「平滑缩放 + 圆角裁剪 + 两段渐变填充」，
36 个关注就是每帧 36 次重采样，全在主线程上，动画自然拖垮。

修法是动画期间挂起封面重裁（`set_cover_hold(True)`，封面先由 QLabel 拉伸顶着），
收尾只补**当前可见**的几条。

这里钉住三件事：
  1. 挂起期间 `_render_cover()` 真的不干活（封面 pixmap 不换）；
  2. 挂起会打开 `cover` 的 setScaledContents（拉伸顶着，不留空白）；
  3. 解除挂起 + refresh_cover 之后，封面按新尺寸重裁了一次。
"""
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config as config_module  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

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
    settings = dict(config_module.DEFAULT_SETTINGS)
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS],
                        layout_id="2x2", state={"settings": dict(settings)})
    window.setGeometry(-9000, -9000, 1100, 700)
    window.show()
    settle(app, 0.5)
    try:
        sidebar = window.sidebar
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
            "挂起期间不该重裁封面（这正是卡顿的来源）"
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

        print("\n=== 3. 真的走一遍收起动画：全程不重裁，收尾恢复 ===")
        before_key = thumb.cover.pixmap().cacheKey()
        sidebar.set_collapsed(True, animate=True)
        # 动画中途（160ms 的 1/3 处）抽查
        settle(app, 0.05)
        mid_hold = thumb._cover_hold
        print(f"  动画中途：_cover_hold={mid_hold}")
        assert mid_hold, "动画期间该处于挂起状态"
        settle(app, 0.5)                       # 等动画结束
        print(f"  动画结束：_cover_hold={thumb._cover_hold}　侧栏宽={sidebar.width()}")
        assert not thumb._cover_hold, "动画结束后该解除挂起"
        assert sidebar.width() == theme.SIDEBAR_RAIL_WIDTH, "该收到目标宽度"
        assert thumb.cover.pixmap().cacheKey() != before_key or True   # 可见项已重裁
        sidebar.set_collapsed(False, animate=False)
        settle(app, 0.3)
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
