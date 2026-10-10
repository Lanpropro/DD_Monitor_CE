"""所有预设的实际鼠标拖动、边界、独立比例、全屏及弹幕换位；不联网。"""
from copy import deepcopy
from unittest.mock import patch

from selfcheck_corner_resize import QApplication, QPoint, QTest, Qt, WallGrid, drag, layouts, theme
from selfcheck_corner_drag_updates import begin, move_to, release_at


def check(wall):
    visible = wall.visible_tiles()
    assert len(visible) == wall._capacity(), (wall.layout_id, len(visible))
    panes = visible + ([wall.danmaku] if wall.has_danmaku else [])
    rects = [pane.geometry() for pane in panes]
    assert all(wall.rect().contains(rect) for rect in rects), (wall.layout_id, wall.size(), rects)
    for index, first in enumerate(rects):
        assert all(not first.intersects(second) for second in rects[index + 1:]), wall.layout_id
    for tile in visible:
        assert tile.width() >= 200 and tile.height() >= 150
        assert tile.parentWidget() is wall
    handles = [handle for handle in wall._preset_handles.values() if handle.isVisible()]
    if wall.layout_id != 'corner':
        assert len(handles) == len(panes) - 1, (wall.layout_id, len(handles))
    for handle in handles:
        assert wall.rect().contains(handle.geometry())
        assert all(not handle.geometry().intersects(rect) for rect in rects)
        image = handle.grab().toImage()
        assert image.pixelColor(image.width() // 2, image.height() // 2).name() in ('#526173', '#38bdf8')


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [dict(room_id=str(1000 + index), uname=f'Fixture {index}', live=False)
             for index in range(16)]
    wall = WallGrid(rooms, layout_id='1x1')
    wall.setGeometry(-9000, -9000, 1800, 1500)
    wall.show()
    app.processEvents()
    originals = list(wall.tiles)
    identities = [int(tile.video.winId()) for tile in originals]
    saved = {}
    try:
        for identifier in layouts.BY_ID:
            if identifier == 'corner':
                continue
            wall.set_layout(identifier)
            wall.resize(900 if layouts.is_portrait_layout(identifier) else 1800, 1500)
            app.processEvents()
            check(wall)
            default_geometry = [tile.geometry() for tile in wall.visible_tiles()]
            if layouts.is_portrait_layout(identifier):
                assert abs(wall.tiles[0].height() - int((wall.width() - 32) * 9 / 16)) <= 1
            for key in list(wall._preset_dividers):
                handle = wall._preset_handles[key]
                node, area, before = wall._preset_dividers[key]
                direction = QPoint(1, 0) if node.axis == Qt.Horizontal else QPoint(0, 1)
                before = list(before)
                drag(app, handle, direction * 24)
                check(wall)
                after = wall._preset_dividers[key][2]
                assert after[key[1]] == before[key[1]] + 24, (identifier, key, before, after)
                assert sum(after) == sum(before)
                assert all(after[index] == value for index, value in enumerate(before)
                           if index not in (key[1], key[1] + 1))
                # 极端坐标不能越过相邻区域，双击恢复相邻默认比例。
                drag(app, handle, direction * 10000)
                check(wall)
                drag(app, handle, direction * -20000)
                check(wall)
                QTest.mouseDClick(handle, Qt.LeftButton, pos=handle.rect().center())
                app.processEvents()
                check(wall)
            saved[identifier] = deepcopy(wall.layout_ratios().get(identifier, {}))
            geometry_before = [tile.geometry() for tile in wall.visible_tiles()]
            target = wall.tiles[0]
            wall.set_fullscreen_tile(target)
            app.processEvents()
            assert not any(handle.isVisible() for handle in wall._preset_handles.values())
            wall.set_fullscreen_tile(None, stagger=True, first=target)
            wall.resize(wall.width() + 10, wall.height() + 10)
            app.processEvents()
            assert all(not tile.isVisible() for tile in wall._pending_reveal)
            wall.reveal_tiles_staggered()
            for _ in range(100):
                if not wall._pending_reveal:
                    break
                QTest.qWait(20)
            check(wall)
            wall.resize(wall.width() - 10, wall.height() - 10)
            app.processEvents()
            assert [tile.geometry() for tile in wall.visible_tiles()] == geometry_before
            if wall.has_danmaku:
                wall.move_danmaku_to_tile(wall.tiles[1] if wall._capacity() > 1 else wall.tiles[0])
                app.processEvents()
                check(wall)
            wall.reset_layout_ratios()
            check(wall)
            assert not wall.layout_ratios().get(identifier)
            if not wall.has_danmaku:
                assert [tile.geometry() for tile in wall.visible_tiles()] == default_geometry
            old_size = wall.size()
            wall.resize(100, 100)
            app.processEvents()
            check(wall)
            wall.resize(old_size)
            app.processEvents()
            print(f'PASS {identifier}: {len(wall._preset_dividers)} dividers', flush=True)

        # 快速拖动只处理最新坐标，释放落实最后位置；切布局丢弃未完成事件。
        wall.set_layout('3x3')
        wall.resize(1800, 1500)
        app.processEvents()
        key = ('root', 0)
        handle = wall._preset_handles[key]
        original = list(wall._preset_dividers[key][2])
        with patch.object(wall, '_relayout_preset', wraps=wall._relayout_preset) as relayout:
            origin = begin(handle)
            for step in range(1, 121):
                move_to(handle, origin + QPoint(0, step))
            assert relayout.call_count == 0
            QTest.qWait(80)
            assert relayout.call_count == 1
            release_at(handle, origin + QPoint(0, 125))
            assert relayout.call_count == 2
        assert wall._preset_dividers[key][2][0] == original[0] + 125
        origin = begin(handle)
        move_to(handle, origin + QPoint(0, 70))
        wall.set_layout('corner')
        QTest.qWait(80)
        assert wall._preset_pending_drag is None and not wall._preset_dividers
        assert set(wall.tiles) == set(originals)
        assert [int(tile.video.winId()) for tile in originals] == identities

        # 重启模型读取各预设自己的比例，导出值与输入值不共享列表。
        restored = WallGrid(rooms, layout_id='3x3', layout_ratios=saved)
        try:
            exported = restored.layout_ratios()
            assert exported == {key: value for key, value in saved.items() if value}
            exported['3x3']['root'][0] = .9
            assert restored.layout_ratios()['3x3']['root'] == saved['3x3']['root']
        finally:
            restored.close()
        print('PASS: 25 presets, all dividers, geometry/limits/fullscreen/swap/coalescing/persistence/IDs')
    finally:
        wall.close()


if __name__ == '__main__':
    main()
