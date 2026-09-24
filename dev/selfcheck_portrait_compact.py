"""竖屏简洁列表：窄竖条、横向滚动、悬停预览和横屏还原。"""
import os
import sys
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.widgets import (CAROUSEL_WIDTH, NAV_LIST_ITEM_HEIGHT, NavThumb,
                         PORTRAIT_LIST_HEIGHT, PORTRAIT_LIST_WIDTH, Sidebar)  # noqa: E402


class FakePlayer:
    def set_muted(self, _value):
        pass

    def set_volume(self, _value):
        pass

    def play(self, *_args, **_kwargs):
        pass

    def stop(self):
        pass


def main():
    app = QApplication(sys.argv)
    rooms = [{"room_id": str(i), "uname": f"主播{i}", "live": True}
             for i in range(28)]
    sidebar = Sidebar(rooms, card_mode=True, auto_compact=True, compact_threshold=18)
    sidebar.resize(1080, 160)
    sidebar.show()
    sidebar.set_side("top")
    app.processEvents()
    first, second = sidebar.items()[:2]
    box = sidebar.list_box
    assert not sidebar.card_mode and box.horizontal
    assert (first.width(), first.height()) == (PORTRAIT_LIST_WIDTH, PORTRAIT_LIST_HEIGHT)
    assert first.thumb.height() == NavThumb.LIST_HEIGHT
    assert first.name_label.geometry().bottom() <= first.thumb.height()
    assert (second.x(), second.y()) == (PORTRAIT_LIST_WIDTH + 2, 0)
    assert first.thumb.face.y() < first.name_label.y()
    assert not first.live_dot.isHidden(), "头像加载后应显示直播状态圆点"
    assert first.thumb._preview_rect() == first.thumb.rect()
    assert box.index_at(PORTRAIT_LIST_WIDTH + 2) == 1
    assert sidebar.scroll.horizontal_only

    with patch.object(NavThumb, "_ensure_player", return_value=FakePlayer()):
        first.thumb.play("https://example.invalid/live.flv")
        assert first.thumb.video.isVisible()
        assert first.thumb.video.geometry() == first.thumb.rect()
        assert not first.thumb.face.isVisible() and not first.name_label.isVisible()
        first.thumb.stop()
        assert not first.thumb.video.isVisible()
        assert first.name_label.isVisible()

    sidebar.set_side("left")
    app.processEvents()
    assert (first.height(), first.thumb.height()) == (NAV_LIST_ITEM_HEIGHT, NavThumb.LIST_HEIGHT)
    sidebar.set_side("top")
    sidebar.set_card_mode(True)
    app.processEvents()
    assert first.width() == CAROUSEL_WIDTH
    assert first.height() > PORTRAIT_LIST_HEIGHT
    sidebar.close()
    print("竖屏窄竖条、预览和方向往返：通过")


if __name__ == "__main__":
    main()
