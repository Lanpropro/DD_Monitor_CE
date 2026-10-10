"""一大五小拖动回归：实际格子、鼠标事件、几何、全屏和布局切换；不联网。"""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(ROOT / "libvlc.dll"))

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import layouts, theme
from ddm.widgets import WallGrid


def drag(app, handle, movement):
    start = handle.rect().center()
    origin = handle.mapToGlobal(start)
    QTest.mousePress(handle, Qt.LeftButton, pos=start)
    destination = origin + movement
    local = handle.mapFromGlobal(destination)
    event = QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(destination),
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(handle, event)
    QTest.mouseRelease(handle, Qt.LeftButton, pos=handle.rect().center())
    app.processEvents()


def check_geometry(wall):
    tiles = wall.tiles[:6]
    assert wall.visible_tiles() == tiles
    rects = [tile.geometry() for tile in tiles]
    assert all(wall.rect().contains(rect) for rect in rects)
    assert all(not first.intersects(second)
               for i, first in enumerate(rects) for second in rects[i + 1:])
    for tile in tiles:
        assert tile.width() >= tile.minimumWidth()
        assert tile.height() >= tile.minimumHeight()
        assert tile.parentWidget() is wall
    for handle in (wall._corner_width_handle, wall._corner_height_handle):
        assert handle.isVisible()
        assert wall.rect().contains(handle.geometry())
        assert all(not handle.geometry().intersects(rect) for rect in rects)
    assert abs(tiles[1].height() - tiles[2].height()) <= 1
    assert max(tile.width() for tile in tiles[3:]) - min(tile.width() for tile in tiles[3:]) <= 1
    assert tiles[0].x() == tiles[3].x()
    assert tiles[0].y() == tiles[1].y()
    assert tiles[2].geometry().bottom() == tiles[0].geometry().bottom()
    assert tiles[5].geometry().right() == tiles[1].geometry().right()


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + index), "uname": f"Fixture {index}", "live": False}
             for index in range(6)]
    wall = WallGrid(rooms, layout_id="corner")
    wall.resize(1200, 800)
    wall.show()
    app.processEvents()
    try:
        assert hasattr(wall, "_corner_width_handle"), "一大五小尚未接入拖动条"
        check_geometry(wall)
        original_tiles = list(wall.tiles)
        video_ids = [int(tile.video.winId()) for tile in original_tiles]
        before = wall.tiles[0].size()
        drag(app, wall._corner_width_handle, QPoint(90, 0))
        assert wall.tiles[0].width() > before.width()
        assert wall.tiles[0].height() == before.height()
        drag(app, wall._corner_height_handle, QPoint(0, -60))
        assert wall.tiles[0].height() < before.height()
        check_geometry(wall)
        assert [int(tile.video.winId()) for tile in original_tiles] == video_ids
        ratios = (wall._corner_width_ratio, wall._corner_height_ratio)
        wall.resize(1400, 900)
        app.processEvents()
        check_geometry(wall)
        assert (wall._corner_width_ratio, wall._corner_height_ratio) == ratios
        wall.relayout(force=True)
        app.processEvents()
        check_geometry(wall)
        saved_geometry = [tile.geometry() for tile in original_tiles]
        for target in original_tiles:
            wall.set_fullscreen_tile(target)
            app.processEvents()
            assert wall.visible_tiles() == [target]
            assert not wall._corner_width_handle.isVisible()
            assert not wall._corner_height_handle.isVisible()
            wall.set_fullscreen_tile(None, stagger=True, first=target)
            assert target.isVisible()
            assert len(wall._pending_reveal) == 5
            wall.reveal_tiles_staggered()
            for _ in range(8):
                app.processEvents()
            check_geometry(wall)
            assert [tile.geometry() for tile in original_tiles] == saved_geometry
            assert not wall._pending_reveal and not wall._defer_show
        for preset in layouts.BY_ID.values():
            if preset["id"] == "corner":
                continue
            wall.set_layout(preset["id"])
            for _ in range(4):
                app.processEvents()
            assert not wall._corner_width_handle.isVisible()
            assert not wall._corner_height_handle.isVisible()
            assert all(tile.parentWidget() is wall for tile in wall.tiles)
            wall.set_layout("corner")
            app.processEvents()
            check_geometry(wall)
            assert wall.tiles[:6] == original_tiles
            assert (wall._corner_width_ratio, wall._corner_height_ratio) == ratios
        assert [int(tile.video.winId()) for tile in original_tiles] == video_ids
        for handle, movement in ((wall._corner_width_handle, QPoint(-5000, 0)),
                                 (wall._corner_width_handle, QPoint(5000, 0)),
                                 (wall._corner_height_handle, QPoint(0, -5000)),
                                 (wall._corner_height_handle, QPoint(0, 5000))):
            drag(app, handle, movement)
            check_geometry(wall)
        for handle in (wall._corner_width_handle, wall._corner_height_handle):
            QTest.mouseDClick(handle, Qt.LeftButton, pos=handle.rect().center())
            app.processEvents()
        assert wall._corner_width_ratio == wall._corner_height_ratio == 2 / 3
        wall.resize(100, 100)
        app.processEvents()
        check_geometry(wall)
        assert wall.tiles[:6] == original_tiles
        print("PASS: mouse drag, minimum sizes, resize, stable video handles, "
              "all six fullscreen targets/staggered restore, all presets and reset")
    finally:
        wall.close()
        app.processEvents()


if __name__ == "__main__":
    main()
