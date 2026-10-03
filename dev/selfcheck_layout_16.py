"""验证十六分菜单入口、网格几何和切换时保留原格子。"""
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
    print("PASS: sixteen-way menu, grid geometry and existing tiles preserved")


if __name__ == "__main__":
    main()
