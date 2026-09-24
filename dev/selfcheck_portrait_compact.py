"""竖屏简洁列表：窄竖条、横向滚动、悬停预览和横屏还原。"""
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.widgets import (CAROUSEL_WIDTH, NAV_LIST_ITEM_HEIGHT, NavThumb,
                         PORTRAIT_LIST_HEIGHT, PORTRAIT_LIST_WIDTH, Sidebar)  # noqa: E402
from ddm.preview import HoverPreview  # noqa: E402


class FakePlayer:
    def __init__(self, *_args, **_kwargs):
        self.freeze_watch = True

    def set_muted(self, _value):
        pass

    def set_volume(self, _value):
        pass

    def play(self, *_args, **_kwargs):
        pass

    def stop(self):
        pass

    def release(self):
        pass


def main():
    app = QApplication(sys.argv)
    rooms = [{"room_id": str(i), "uname": f"主播{i}", "live": True}
             for i in range(28)]
    sidebar = Sidebar(rooms, card_mode=True, auto_compact=True, compact_threshold=18)
    sidebar.resize(1080, 196)
    sidebar.show()
    sidebar.set_side("top")
    sidebar.resize(1080, 196)
    app.processEvents()
    first, second = sidebar.items()[:2]
    box = sidebar.list_box
    assert not sidebar.card_mode and box.horizontal
    assert (first.width(), first.height()) == (PORTRAIT_LIST_WIDTH, PORTRAIT_LIST_HEIGHT)
    assert first.thumb.height() == PORTRAIT_LIST_HEIGHT - 12
    assert first.name_label.geometry().bottom() <= first.thumb.height()
    assert first.thumb.face.width() == NavThumb.PORTRAIT_AVATAR_SIZE
    assert first.thumb.face.geometry().bottom() < first.name_label.geometry().top()
    assert first.name_label.geometry().bottom() < first.sub.geometry().top()
    assert first.sub.isVisible() and first.sub.text() == "直播中"
    assert (second.x(), second.y()) == (PORTRAIT_LIST_WIDTH + 2, 0)
    assert first.thumb.face.y() < first.name_label.y()
    assert not first.live_dot.isHidden(), "头像加载后应显示直播状态圆点"
    assert first.thumb._preview_rect() == first.thumb.rect()
    assert box.index_at(PORTRAIT_LIST_WIDTH + 2) == 1
    assert sidebar.scroll.horizontal_only
    assert sidebar.scroll.viewport().width() > 300

    with patch.object(NavThumb, "_ensure_player", return_value=FakePlayer()):
        first.thumb.play("https://example.invalid/live.flv")
        # 紧凑（竖屏窄条 / 横屏长条）卡片里**不播预览**：这行只有几十像素高，
        # 塞进去画面会被压扁 —— 用户要求把卡片里那个小预览窗删掉。预览改成在
        # 卡片旁边弹浮层，见 ddm/preview.py 的 _needs_popup()。
        assert not first.thumb.video.isVisible(), "紧凑卡片里不该再出现预览小窗"
        # 竖屏窄条用的是头像圆点（live_dot），face 本来就不显示，这里只看文字
        assert first.name_label.isVisible(), "不播预览时卡片文字该照常露着"
        first.thumb.stop()
        assert not first.thumb.video.isVisible()
        assert first.name_label.isVisible()

    with patch("ddm.preview.TilePlayer", FakePlayer):
        preview = HoverPreview(sidebar)
        preview._item = first
        preview._room = first.room
        preview._on_resolved(0, "0", "https://example.invalid/live.flv", 80, "web", None)
        # 浮层挂在**主窗口**上（这里是个纯 Sidebar，window() 就是它自己）：滚动视口
        # 会裁掉探出侧栏的部分，而竖屏要向下弹，必须能越出视口。
        assert preview._popup.parentWidget() is sidebar.window()
        assert preview._popup.isVisible()
        assert preview._popup.size().width() == CAROUSEL_WIDTH, \
            "浮层该用展开卡片那个宽度（横竖屏统一，不再跟窄条同宽）"
        assert preview._popup.size().height() == NavThumb.HEIGHT, \
            "浮层该和展开卡片上那块封面一样高"
        # 竖屏的浮层是**向下弹**的（卡片右边没空间），得给够高度才验得了：
        # 真实里它的父控件是主窗口、够高，这个自检的 sidebar 只有横栏那么高。
        sidebar.resize(1080, 640)
        app.processEvents()
        preview._place_popup(first)
        origin = first.mapTo(sidebar, QPoint(0, 0))
        # 竖屏是**和卡片的竖直中线对齐**（不再是贴左边缘）；卡片靠左时居中会向左
        # 越界，照样夹回窗口内。
        want_x = max(0, origin.x() + (first.width() - preview._popup.width()) // 2)
        assert preview._popup.x() == want_x, \
            f"竖屏该和卡片中心对齐：popup={preview._popup.x()} want={want_x}"
        assert origin.y() + first.height() <= preview._popup.y() \
            <= origin.y() + first.height() + 20, "竖屏该向下弹出（落在卡片正下方）"
        assert first.name_label.isVisible(), "悬浮预览不该盖掉卡片信息"
        sidebar.scroll.horizontalScrollBar().setValue(
            sidebar.scroll.horizontalScrollBar().maximum())
        app.processEvents()
        last = sidebar.items()[-1]
        preview._item = last
        preview._place_popup(last)
        parent = preview._popup.parentWidget()
        assert preview._popup.x() <= parent.width() - preview._popup.width(), \
            "浮层不能跑出窗口右边"
        preview.stop()
        assert not preview._popup.isVisible()

    sidebar.set_side("left")
    app.processEvents()
    assert (first.height(), first.thumb.height()) == (NAV_LIST_ITEM_HEIGHT, NavThumb.LIST_HEIGHT)
    sidebar.set_side("top")
    sidebar.set_card_mode(True)
    app.processEvents()
    assert first.width() == CAROUSEL_WIDTH
    assert first.height() == PORTRAIT_LIST_HEIGHT
    sidebar.close()
    print("竖屏窄竖条、预览和方向往返：通过")


if __name__ == "__main__":
    main()
