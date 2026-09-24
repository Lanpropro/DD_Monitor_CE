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
        assert first.thumb.video.isVisible()
        assert first.thumb.video.geometry() == first.thumb.rect()
        assert not first.thumb.face.isVisible() and not first.name_label.isVisible()
        first.thumb.stop()
        assert not first.thumb.video.isVisible()
        assert first.name_label.isVisible()

    with patch("ddm.preview.TilePlayer", FakePlayer):
        preview = HoverPreview(sidebar)
        preview._item = first
        preview._room = first.room
        preview._on_resolved(0, "0", "https://example.invalid/live.flv", 80, "web", None)
        assert preview._popup.parentWidget() is sidebar.scroll.viewport()
        assert preview._popup.isVisible()
        assert preview._popup.size().width() == PORTRAIT_LIST_WIDTH
        assert preview._popup.size().height() == PORTRAIT_LIST_HEIGHT
        anchor = first.mapTo(sidebar.scroll.viewport(), QPoint(first.width() * 2 // 3, 0))
        expected_x = max(0, min(anchor.x(), sidebar.scroll.viewport().width() - PORTRAIT_LIST_WIDTH))
        assert preview._popup.x() == expected_x, \
            f"popup x={preview._popup.x()} expected={expected_x} viewport={sidebar.scroll.viewport().width()}"
        expected_y = first.mapTo(sidebar.scroll.viewport(), QPoint(0, 0)).y()
        expected_y = max(0, min(expected_y, sidebar.scroll.viewport().height() - PORTRAIT_LIST_HEIGHT))
        assert preview._popup.y() == expected_y, "预览窗应和窄竖卡垂直居中"
        assert first.name_label.isVisible(), "悬浮预览不该盖掉卡片信息"
        sidebar.scroll.horizontalScrollBar().setValue(
            sidebar.scroll.horizontalScrollBar().maximum())
        app.processEvents()
        last = sidebar.items()[-1]
        preview._item = last
        preview._place_popup(last)
        last_x = last.mapTo(sidebar.scroll.viewport(), QPoint(0, 0)).x()
        assert preview._popup.x() == max(0, last_x - PORTRAIT_LIST_WIDTH), \
            "靠右卡片的预览应翻到左侧，不能钉在视口边缘"
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
