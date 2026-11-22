"""验证空位数量、提示、十六分几何和切换时保留原格子。"""
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import layouts
from ddm.widgets import LayoutPicker, WallGrid


def resize_picker(picker, local, delta):
    pressed = picker.mapToGlobal(local)
    for kind, point, button, buttons in (
            (QEvent.MouseButtonPress, pressed, Qt.LeftButton, Qt.LeftButton),
            (QEvent.MouseMove, pressed + delta, Qt.NoButton, Qt.LeftButton),
            (QEvent.MouseButtonRelease, pressed + delta, Qt.LeftButton, Qt.NoButton)):
        event = QMouseEvent(kind, QPointF(picker.mapFromGlobal(point)), QPointF(point), button, buttons, Qt.NoModifier)
        QApplication.sendEvent(picker, event)


def check_picker_dismissal():
    host = QWidget()
    host.show()
    picker = LayoutPicker('4x4', host)
    picker.show()
    outside = picker.frameGeometry().bottomRight() + QPoint(24, 24)

    for target, kind in ((picker, QEvent.MouseButtonPress), (host, QEvent.MouseButtonPress),
                         (host.windowHandle(), QEvent.MouseButtonPress),
                         (host.windowHandle(), QEvent.NonClientAreaMouseButtonPress)):
        picker.show()
        event = QMouseEvent(kind, QPointF(target.mapFromGlobal(outside)), QPointF(outside),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(target, event)
        assert not picker.isVisible(), (target, kind)
    picker.show()
    QTest.keyClick(picker, Qt.Key_Escape)
    assert not picker.isVisible()
    host.close()


def main():
    app = QApplication([])
    assert layouts.capacity("4x4") == 16
    picker = LayoutPicker("4x4")
    assert "4x4" in picker.card_ids()
    assert picker.size() == LayoutPicker.DEFAULT_SIZE
    screen = Mock(availableGeometry=lambda: QRect(0, 0, 540, 380))
    with patch.object(LayoutPicker, 'screen', return_value=screen):
        compact = LayoutPicker('corner')
    compact.move(30, 10)
    compact.show()
    app.processEvents()
    bounds = compact.size()
    assert bounds.width() <= 528 and bounds.height() <= 368
    assert compact.scroll.verticalScrollBar().maximum() > 0
    assert compact.scroll.horizontalScrollBar().maximum() == 0
    assert compact.current_label.text().startswith('当前')
    assert compact.edit_button is None
    emitted = []
    compact.sizeChanged.connect(emitted.append)
    original = compact.geometry()
    cards = compact._cards[compact.group()]
    initial_columns = len({card.x() for card in cards})
    resize_picker(compact, QPoint(4, 4), QPoint(100, 60))
    app.processEvents()
    assert compact.geometry().bottomRight() == original.bottomRight()
    assert len({card.x() for card in cards}) < initial_columns and emitted == [compact.size()]
    assert compact.scroll.horizontalScrollBar().maximum() == 0
    resize_picker(compact, compact.rect().bottomRight() - QPoint(4, 4), QPoint(1000, 1000))
    assert compact.geometry().bottomRight() == screen.availableGeometry().adjusted(6, 6, -6, -6).bottomRight()
    assert emitted[-1] == compact.size()
    bounds = compact.size()
    compact._tabs['竖屏布局'].click()
    assert compact.size() == bounds and compact.group() == '竖屏布局'
    selected = []
    compact.chosen.connect(selected.append)
    compact._cards['竖屏布局'][0].click()
    assert selected == [layouts.PORTRAIT_LAYOUTS[0]['id']]
    assert not compact.isVisible()
    restored = LayoutPicker('corner', preferred_size=QSize(550, 470), available=QRect(0, 0, 420, 340))
    assert restored.size() == QSize(408, 328)
    restored.close()
    wall = WallGrid([], layout_id="3x3")
    wall.resize(1280, 800)
    wall.show()
    app.processEvents()
    original = list(wall.tiles)
    wall.set_layout("4x4")
    app.processEvents()
    assert wall.tiles[:len(original)] == original
    assert len(wall.tiles) == 16
    rects = [tile.geometry() for tile in wall.tiles]
    assert all(tile.isVisible() for tile in wall.tiles)
    assert len({rect.x() for rect in rects}) == 4
    assert len({rect.y() for rect in rects}) == 4
    assert all(not a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1:])
    wall.close()
    picker.close()

    rooms = [{"room_id": rid, "uname": rid, "live": False} for rid in ("1001", "1002")]
    occupied_wall = WallGrid(rooms, layout_id="3x3")
    occupied_wall.resize(1280, 800)
    occupied_wall.show()
    original_rooms = list(occupied_wall.tiles[:2])
    try:
        for layout, count in (("3x3", 9), ("4x4", 16), ("1x2", 2)):
            occupied_wall.set_layout(layout)
            app.processEvents()
            assert len(occupied_wall.tiles) == count, layout
            assert len(occupied_wall.visible_tiles()) == count, layout
            assert occupied_wall.tiles[:2] == original_rooms, layout
            assert [tile.room.get("room_id") for tile in occupied_wall.tiles[:2]] == ["1001", "1002"]
            empty = occupied_wall.tiles[2:]
            assert len(empty) == count - 2, layout
            assert all(not tile.room.get("room_id") for tile in empty), layout
            assert all(tile.add_room_button.isVisible() and tile.add_room_button.isEnabled()
                       and "添加直播间" in tile.add_room_button.text() for tile in empty), layout
            assert all(tile.replace_room_button.isVisible() and tile.replace_room_button.text() == ''
                       for tile in original_rooms), layout
    finally:
        occupied_wall.close()
    check_picker_dismissal()
    print("PASS: sixteen-way geometry, existing rooms and empty-slot add buttons across layout switches")


if __name__ == "__main__":
    main()
