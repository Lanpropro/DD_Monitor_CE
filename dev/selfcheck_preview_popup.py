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
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.preview import HoverPreview  # noqa: E402
from ddm.widgets import CAROUSEL_WIDTH, NavThumb  # noqa: E402


class FakePlayer:
    """只挡住预览播放器的创建，不碰真实 libvlc。"""

    def set_muted(self, _muted):
        pass

    def set_volume(self, _volume):
        pass

    def play(self, *_args, **_kwargs):
        pass

    def stop(self):
        pass

    def release(self):
        pass

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
    # 只测浮层位置；假房间的异步取流不应参与这个 UI 自检。
    for method in ("start_tile", "refresh_status", "sync_danmaku"):
        patch.object(MainWindow, method, return_value=None).start()
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
        # 用户明确要求「横屏的时候应该在右侧」：浮层从卡片**右边缘之后**开始摆，
        # 一点都不压住卡片。（旧版是有意压在卡片右侧 1/3 处，已按用户要求改掉。）
        want_x = origin.x() + item.width()
        want_y = origin.y() + (item.height() - popup.height()) // 2
        print(f"  卡片 {item.width()}x{item.height()} @({origin.x()},{origin.y()})　"
              f"卡片右边缘 x={want_x}　侧栏宽={sidebar.width()}")
        print(f"  浮层 {popup.width()}x{popup.height()} @({popup.x()},{popup.y()})　"
              f"期望 x>={want_x}, y={want_y}")
        assert popup.width() == CAROUSEL_WIDTH, \
            f"浮层该用展开卡片那个宽度（横竖屏统一）：{popup.width()} vs {CAROUSEL_WIDTH}"
        assert popup.height() == NavThumb.HEIGHT, \
            f"浮层该和非紧凑卡片上的封面一样高：{popup.height()} vs {NavThumb.HEIGHT}"
        assert popup.x() >= want_x, \
            f"横向该完全贴在卡片右侧、不压住卡片：得到 {popup.x()}，期望 >= {want_x}"
        assert abs(popup.y() - want_y) <= 1, \
            f"纵向该居中于卡片：得到 {popup.y()}，期望 {want_y}"
        # 关键不变量：浮层和卡片**没有任何重叠**
        card_rect = item.geometry()
        card_rect.moveTopLeft(item.mapTo(popup.parentWidget(), card_rect.topLeft()))
        assert not card_rect.intersects(popup.geometry()), \
            f"浮层不该和卡片重叠：卡片={card_rect.getRect()} 浮层={popup.geometry().getRect()}"

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
        # 竖屏是**和卡片中心对齐**（不是贴左边缘）。第一张卡片靠左，居中后会向左
        # 越界而被夹到 0 —— 这是预期；完整不越界的居中在下面用第二张卡片验。
        want_x = max(0, origin.x() + (item.width() - popup.width()) // 2)
        assert popup.x() == want_x, \
            f"竖屏该和卡片中心对齐：{popup.x()} vs {want_x}"
        assert popup.y() >= origin.y() + item.height(), \
            f"竖屏该向下弹（在卡片下方）：{popup.y()} vs 卡底 {origin.y() + item.height()}"
        assert popup.y() <= origin.y() + item.height() + 20, "向下弹的缝别太大"
        assert popup.width() == CAROUSEL_WIDTH and popup.height() == NavThumb.HEIGHT, \
            "竖屏的浮层该和横屏一样大（用户要求两边对齐）"

        # 换一张**不在最左边**的卡片：浮层该和卡片的竖直中线对齐（居中），
        # 而不是贴着卡片左边缘 —— 贴左的话整块预览都偏到一边去了。
        other = sidebar.items()[1]
        preview._place_popup(other)                 # noqa: SLF001
        settle(app, 0.15)
        other_origin = other.mapTo(popup.parentWidget(), QPoint(0, 0))
        want = other_origin.x() + (other.width() - popup.width()) // 2
        want = max(0, min(want, popup.parentWidget().width() - popup.width()))
        print(f"  第二张卡片 @({other_origin.x()},{other_origin.y()})　"
              f"浮层 x={popup.x()}　居中期望={want}")
        assert popup.x() == want, f"竖屏该和卡片中心对齐：{popup.x()} vs {want}"

        print("\n=== 4. 紧凑卡片里不该再有那个小预览窗 ===")
        item = sidebar.items()[0]
        # 直接戳缩略图的播放入口：紧凑时它必须什么都不做。以前这里会在卡片右侧
        # 1/3 画一块 48px 高的小画面（`_preview_rect()` 的那条分支），用户要求删掉。
        with patch.object(NavThumb, "_ensure_player", return_value=FakePlayer()):
            item.thumb.play("https://example.invalid/live.flv")
            print(f"  紧凑卡片 play() 之后：video 可见={item.thumb.video.isVisible()}　"
                  f"_preview_rect={item.thumb._preview_rect().getRect()}　"
                  f"rect={item.thumb.rect().getRect()}")
            assert not item.thumb.video.isVisible(), \
                "紧凑卡片里不该再出现预览小窗"
            assert item.thumb._preview_rect() == item.thumb.rect(), \
                "紧凑卡片不该再算「右侧 1/3」那块预览区"

        print("\n=== 5. 滚轮把卡片滚出指针底下：浮层要收掉，不能贴到软件边缘 ===")
        # 用户报的：预览开着、指针不动，只用滚轮把卡片滚走，浮层还在，而且被夹到
        # 软件上下边缘贴着 —— 因为 _place_popup() 末尾那句 clamp 会把跑到视口外的
        # 条目硬夹回边界。滚动之后指针底下已经不是这张卡片了，必须收掉。
        item = sidebar.items()[0]
        preview._item = item                          # noqa: SLF001
        preview._place_popup(item)                    # noqa: SLF001
        popup.show()
        settle(app, 0.15)
        assert popup.isVisible()
        with patch.object(HoverPreview, "_cursor_on_item", return_value=False):
            preview._update_popup_position()          # noqa: SLF001
            settle(app, 0.15)
        print(f"  指针已不在卡片上时滚动：浮层可见={popup.isVisible()}")
        assert not popup.isVisible(), "指针底下不是这张卡片了，浮层该收掉"

        preview._item = item                          # noqa: SLF001
        preview._place_popup(item)                    # noqa: SLF001
        popup.show()
        settle(app, 0.15)
        with patch.object(HoverPreview, "_cursor_on_item", return_value=True):
            preview._update_popup_position()          # noqa: SLF001
            settle(app, 0.15)
        print(f"  指针还在卡片上时滚动：浮层可见={popup.isVisible()}（该留着并跟着挪）")
        assert popup.isVisible(), "指针还在卡片上，浮层不该收"
        preview._stop_now()                           # noqa: SLF001
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
