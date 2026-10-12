"""小画面边框：相邻两路调整、边界、重置和比例保留；不联网。"""
from unittest.mock import patch

from selfcheck_corner_resize import (
    QApplication, QPoint, QTest, Qt, WallGrid, check_geometry, drag, layouts, theme,
    border_for, CORNER_KEYS,
)
from selfcheck_corner_drag_updates import begin, move_to, release_at


def sizes(wall):
    return [tile.size() for tile in wall.tiles[:6]]


def ratios(wall):
    return (wall._corner_width_ratio, wall._corner_height_ratio,
            wall._corner_right_ratio, tuple(wall._corner_bottom_ratios))


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + index), "uname": f"Fixture {index}", "live": False}
             for index in range(6)]
    wall = WallGrid(rooms, layout_id="corner")
    wall.resize(1600, 1100)
    wall.show()
    app.processEvents()
    try:
        assert len(wall._divider_rects) == 5
        check_geometry(wall, equal_small=True)
        image = wall.grab().toImage()
        for rect in wall._divider_rects.values():
            assert image.pixelColor(rect.center()) == theme.qcolor(theme.BG)
        video_ids = [int(tile.video.winId()) for tile in wall.tiles]
        cases = [("right", QPoint(0, 45), (1, 2)),
                 ("bottom_left", QPoint(60, 0), (3, 4)),
                 ("bottom_right", QPoint(-40, 0), (4, 5))]
        for target, movement, affected in cases:
            handle, point = border_for(wall, CORNER_KEYS[target])
            before = sizes(wall)
            positions = [tile.geometry() for tile in wall.tiles]
            drag(app, handle, movement, pos=point)
            after = sizes(wall)
            assert all(after[i] == before[i] for i in range(6) if i not in affected)
            assert all(wall.tiles[i].geometry() == positions[i]
                       for i in range(6) if i not in affected)
            assert all(after[i] != before[i] for i in affected)
            check_geometry(wall)
            axis = QPoint(0, 1) if target == "right" else QPoint(1, 0)
            for extreme in (-5000, 5000):
                before = sizes(wall)
                positions = [tile.geometry() for tile in wall.tiles]
                handle, point = border_for(wall, CORNER_KEYS[target])
                drag(app, handle, axis * extreme, pos=point)
                assert all(sizes(wall)[i] == before[i] for i in range(6) if i not in affected)
                assert all(wall.tiles[i].geometry() == positions[i]
                           for i in range(6) if i not in affected)
                check_geometry(wall)
            positions = [tile.geometry() for tile in wall.tiles]
            handle, point = border_for(wall, CORNER_KEYS[target])
            QTest.mouseDClick(handle, Qt.LeftButton, pos=point)
            app.processEvents()
            assert all(wall.tiles[i].geometry() == positions[i]
                       for i in range(6) if i not in affected)
            first, second = (wall.tiles[i] for i in affected)
            first_span = first.height() if target == "right" else first.width()
            second_span = second.height() if target == "right" else second.width()
            assert abs(first_span - second_span) <= 1
            check_geometry(wall)

            # 边框也必须合并事件，并在松开时落实最新坐标。
            handle, point = border_for(wall, CORNER_KEYS[target])
            origin = begin(handle, pos=point)
            with patch.object(wall, "_relayout_corner", wraps=wall._relayout_corner) as layout:
                for sample in range(30):
                    move_to(handle, origin + axis * sample)
                assert layout.call_count == 0
                QTest.qWait(80)
                assert layout.call_count == 1
                release_at(handle, origin + axis * 35)
                assert layout.call_count == 2
            check_geometry(wall)

        saved_ratios = ratios(wall)
        for size in ((1800, 1200), (648, 498), (1600, 1100)):
            wall.resize(*size)
            app.processEvents()
            assert ratios(wall) == saved_ratios
            check_geometry(wall)
        saved = [tile.geometry() for tile in wall.tiles]
        for target in wall.tiles:
            wall.set_fullscreen_tile(target)
            app.processEvents()
            assert all(not border.isVisible() for border in wall._pane_borders.values())
            wall.set_fullscreen_tile(None, stagger=True, first=target)
            wall.reveal_tiles_staggered()
            for _ in range(8):
                app.processEvents()
            check_geometry(wall)
            assert [tile.geometry() for tile in wall.tiles] == saved
        for preset in layouts.BY_ID.values():
            wall.set_layout(preset['id'])
            app.processEvents()
            wall.set_layout('corner')
            app.processEvents()
            assert ratios(wall) == saved_ratios
            check_geometry(wall)
        for target, movement, _ in cases:
            old = ratios(wall)
            handle, point = border_for(wall, CORNER_KEYS[target])
            origin = begin(handle, pos=point)
            move_to(handle, origin + movement)
            wall.set_layout('3x3')
            QTest.qWait(80)
            assert ratios(wall) == old
            assert wall._border_drag is None
            wall.set_layout('corner')
            app.processEvents()
        assert [int(tile.video.winId()) for tile in wall.tiles[:6]] == video_ids
        print('PASS: three small-screen borders, adjacent pairs only, limits, pair reset, '
              'coalescing, resize/fullscreen/all presets and cancellation')
    finally:
        wall.close()
        app.processEvents()


if __name__ == '__main__':
    main()
