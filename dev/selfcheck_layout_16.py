"""验证空位数量、提示、十六分几何和切换时保留原格子。"""
import os
from pathlib import Path
import sys

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from ddm import layouts
from ddm.widgets import LayoutPicker, WallGrid


def main():
    app = QApplication([])
    assert layouts.capacity("4x4") == 16
    picker = LayoutPicker("4x4")
    assert "4x4" in picker.card_ids()
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
            assert all(tile.add_room_button.isHidden() for tile in original_rooms), layout
    finally:
        occupied_wall.close()
    print("PASS: sixteen-way geometry, existing rooms and empty-slot add buttons across layout switches")


if __name__ == "__main__":
    main()
