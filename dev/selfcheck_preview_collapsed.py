"""收起关注栏的悬停预览：横屏走右侧浮层，竖屏跟随头像排。"""
import os
import sys
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.preview import HoverPreview  # noqa: E402
from ddm.widgets import Sidebar  # noqa: E402


class FakePlayer:
    plays = 0
    releases = 0

    def __init__(self, *_args, **_kwargs):
        self.freeze_watch = True

    def set_muted(self, _value):
        pass

    def set_volume(self, _value):
        pass

    def play(self, *_args, **_kwargs):
        FakePlayer.plays += 1

    def stop(self):
        pass

    def release(self):
        FakePlayer.releases += 1


class FakeDrag:
    started = False

    def __init__(self, _parent):
        pass

    def setMimeData(self, _mime):
        pass

    def exec(self, _action):
        FakeDrag.started = True


def resolved(preview, item):
    preview._item = item
    preview._room = item.room
    preview._on_resolved(preview._generation, str(item.room["room_id"]),
                         "https://example.invalid/live.flv", 80, "web", None)


def move_mouse(widget, point, buttons=Qt.NoButton):
    event = QMouseEvent(QEvent.MouseMove, QPointF(point),
                        QPointF(widget.mapToGlobal(point)),
                        Qt.NoButton, buttons, Qt.NoModifier)
    QApplication.sendEvent(widget, event)


def main():
    app = QApplication(sys.argv)
    rooms = [{"room_id": str(index), "uname": f"主播{index}", "live": True}
             for index in range(1, 9)]
    host = QWidget()
    host.resize(900, 650)
    sidebar = Sidebar(rooms, parent=host, card_mode=True, auto_compact=False)
    sidebar.resize(240, 600)
    sidebar.refresh_strip()
    preview = HoverPreview(sidebar)
    sidebar.previewHovered.connect(preview.on_hover)
    sidebar.previewUnhovered.connect(preview.on_unhover)
    host.show()
    sidebar.show()
    app.processEvents()
    item = sidebar.items()[2]

    with patch("ddm.preview.TilePlayer", FakePlayer):
        sidebar.set_collapsed(True, animate=False)
        app.processEvents()
        assert preview._needs_popup(), "横屏收起后应走浮层，即使偏好是大卡片"
        resolved(preview, item)
        assert preview._popup.isVisible() and FakePlayer.plays == 1
        assert preview._popup.parentWidget() is host and not preview._popup.isWindow()
        assert not item.thumb.video.isVisible(), "32px 头像里不能播放预览"
        cover = QPixmap(320, 180)
        cover.fill("#345678")
        item.thumb.set_cover(cover)
        assert not item.thumb.cover.pixmap(), "收起后隐藏的封面无需立即裁切"
        origin = item.mapTo(host, QPoint(0, 0))
        assert preview._popup.x() == origin.x() + item.width() * 2 // 3

        old_generation = preview._generation
        sidebar.set_collapsed(False, animate=False)
        app.processEvents()
        assert not preview._popup.isVisible(), "展开时应收掉旧浮层"
        assert preview._generation > old_generation and FakePlayer.releases == 0, \
            "切换侧栏应作废旧取流，但保留播放器供后续悬停复用"
        assert item.thumb.cover.pixmap(), "展开后应补上收起期间收到的封面"
        assert not preview._needs_popup(), "展开的大卡片仍在卡片内预览"

        sidebar.set_side("top")
        sidebar.resize(900, 200)
        app.processEvents()
        assert sidebar.card_mode and not preview._needs_popup(), \
            "竖屏展开的大卡片应和横屏一样在封面内预览"
        with patch.object(item.thumb, "play") as play_in_card:
            resolved(preview, item)
        play_in_card.assert_called_once()
        assert not preview._popup.isVisible()
        preview.cancel()

        strip = sidebar._head_strip
        with patch.object(strip, "rebuild", wraps=strip.rebuild) as rebuild, \
                patch.object(item, "set_compact", wraps=item.set_compact) as compact, \
                patch.object(sidebar.list_box, "relayout",
                             wraps=sidebar.list_box.relayout) as relayout:
            sidebar.set_collapsed(True, animate=False)
        assert not rebuild.called and not compact.called and not relayout.called, \
            "竖屏收起不应重建头像排或排版已隐藏的卡片"
        app.processEvents()
        assert preview._needs_popup()
        avatar = strip._avatars[str(item.room["room_id"])]
        assert avatar.isVisible() and not item.isVisible()
        move_mouse(strip, QPoint(strip.width() - 2, strip.height() // 2))
        hovered = []
        sidebar.previewHovered.connect(lambda room: hovered.append(str(room["room_id"])))
        move_mouse(strip, avatar.geometry().center())
        app.processEvents()
        assert hovered and hovered[-1] == str(item.room["room_id"]), \
            "竖屏收起后头像排必须触发预览悬停"
        preview._delay.stop()
        resolved(preview, item)
        assert preview._popup.isVisible() and FakePlayer.plays == 2
        origin = avatar.mapTo(host, QPoint(0, 0))
        assert preview._popup.y() == origin.y() + avatar.height() + 6, \
            "竖屏浮层应在当前头像下方，不能沿用隐藏卡片的位置"
        assert not item.thumb.video.isVisible()
        unhovered = []
        sidebar.previewUnhovered.connect(lambda room: unhovered.append(str(room["room_id"])))
        move_mouse(strip, QPoint(strip.width() - 2, strip.height() // 2))
        app.processEvents()
        assert unhovered and unhovered[-1] == str(item.room["room_id"])

        strip._press_room = str(item.room["room_id"])
        strip._press_pos = QPoint(0, 0)
        point = avatar.geometry().center()
        with patch("ddm.widgets.QDrag", FakeDrag):
            move_mouse(strip, point, Qt.LeftButton)
        assert FakeDrag.started, "头像排原有的拖到画面墙行为必须保留"

        sidebar.set_collapsed(False, animate=False)
        app.processEvents()
        assert not preview._popup.isVisible(), "头像排隐藏后旧浮层不能悬在画面墙上"

    preview.stop()
    assert FakePlayer.releases == 1
    host.close()
    print("收起关注栏预览：通过")


if __name__ == "__main__":
    main()
