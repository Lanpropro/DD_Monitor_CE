"""小画面分隔线：相邻两路调整、边界、重置和比例保留；不联网。"""
from unittest.mock import patch

from selfcheck_corner_resize import (
    QApplication, QPoint, QTest, Qt, WallGrid, check_geometry, drag, layouts, theme,
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
        assert len(wall._corner_handles) == 5
        check_geometry(wall, equal_small=True)
        for handle in wall._corner_handles.values():
            image = handle.grab().toImage()
            assert image.pixelColor(image.width() // 2, image.height() // 2).name() in (
                '#526173', '#38bdf8'), '分隔线必须实际填色，不能留下未初始化背景'
        video_ids = [int(tile.video.winId()) for tile in wall.tiles]
        cases = [(wall._corner_right_handle, QPoint(0, 45), (1, 2)),
                 (wall._corner_bottom_handles[0], QPoint(60, 0), (3, 4)),
                 (wall._corner_bottom_handles[1], QPoint(-40, 0), (4, 5))]
        for handle, movement, affected in cases:
            before = sizes(wall)
            positions = [tile.geometry() for tile in wall.tiles]
            drag(app, handle, movement)
            after = sizes(wall)
            assert all(after[i] == before[i] for i in range(6) if i not in affected)
            assert all(wall.tiles[i].geometry() == positions[i]
                       for i in range(6) if i not in affected)
            assert all(after[i] != before[i] for i in affected)
            check_geometry(wall)
            axis = QPoint(0, 1) if handle.orientation == Qt.Vertical else QPoint(1, 0)
            for extreme in (-5000, 5000):
                before = sizes(wall)
                positions = [tile.geometry() for tile in wall.tiles]
                drag(app, handle, axis * extreme)
                assert all(sizes(wall)[i] == before[i] for i in range(6) if i not in affected)
                assert all(wall.tiles[i].geometry() == positions[i]
                           for i in range(6) if i not in affected)
                check_geometry(wall)
            positions = [tile.geometry() for tile in wall.tiles]
            QTest.mouseDClick(handle, Qt.LeftButton, pos=handle.rect().center())
            app.processEvents()
            assert all(wall.tiles[i].geometry() == positions[i]
                       for i in range(6) if i not in affected)
            first, second = (wall.tiles[i] for i in affected)
            first_span = first.height() if handle.orientation == Qt.Vertical else first.width()
            second_span = second.height() if handle.orientation == Qt.Vertical else second.width()
            assert abs(first_span - second_span) <= 1
            check_geometry(wall)

            # 新分隔线也必须合并事件，并在松开时落实最新坐标。
            origin = begin(handle)
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
            assert all(not handle.isVisible() for handle in wall._corner_handles.values())
            wall.set_fullscreen_tile(None, stagger=True, first=target)
            wall.reveal_tiles_staggered()
            for _ in range(8):
                app.processEvents()
            check_geometry(wall)
            assert [tile.geometry() for tile in wall.tiles] == saved
        for preset in layouts.BY_ID.values():
            wall.set_layout(preset['id'])
            app.processEvents()
            if preset['id'] != 'corner':
                assert all(not handle.isVisible() for handle in wall._corner_handles.values())
            wall.set_layout('corner')
            app.processEvents()
            assert ratios(wall) == saved_ratios
            check_geometry(wall)
        for handle, movement, _ in cases:
            old = ratios(wall)
            origin = begin(handle)
            move_to(handle, origin + movement)
            wall.set_layout('3x3')
            QTest.qWait(80)
            assert ratios(wall) == old
            assert handle._press_offset is None
            wall.set_layout('corner')
            app.processEvents()
        assert [int(tile.video.winId()) for tile in wall.tiles[:6]] == video_ids
        print('PASS: three small-screen handles, adjacent pairs only, limits, pair reset, '
              'coalescing, resize/fullscreen/all presets and cancellation')
    finally:
        wall.close()
        app.processEvents()


if __name__ == '__main__':
    main()
