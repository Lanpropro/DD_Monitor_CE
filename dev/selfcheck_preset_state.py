"""实际主窗口保存全部预设比例，重启恢复、按当前预设重置；临时配置，不联网。"""
from contextlib import ExitStack
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from selfcheck_corner_resize import QApplication, QPoint, QTest, Qt, WallGrid, drag, layouts, theme, border_for
from selfcheck_corner_drag_updates import begin, move_to, release_at
from selfcheck_pane_borders import press, point_on
from ddm import bili, config, resize_layout
from ddm.app import MainWindow


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    tree = resize_layout.build_partition([(0, 0, 1, 1), (0, 1, 1, 1)])
    for invalid in (None, [], True, {}, {'root': [.5]}, {'root': [True, .5]},
                    {'root': ['.5', .5]}, {'root': [0, 1]}, {'root': [-1, 2]},
                    {'root': [float('nan'), .5]}, {'root': [float('inf'), .5]},
                    {'root': [1e308, 1e308]}, {'root': [10 ** 500, 1]},
                    {'root': [1e-300, 1e300]}, {'unknown': [.5, .5]}):
        assert not resize_layout.validated_weights(invalid, tree), repr(invalid)
    assert resize_layout.validated_weights({'root': [2, 1]}, tree) == {'root': [2/3, 1/3]}
    for length, weights, minimums in ((999, [1, 2, 3], [150, 150, 150]),
                                      (450, [.01, .49, .5], [150, 150, 150]),
                                      (800, [.98, .01, .01], [200, 200, 200])):
        sizes = resize_layout.allocate(length, weights, minimums)
        assert sum(sizes) == length and all(a >= b for a, b in zip(sizes, minimums))

    directory = Path(__file__).resolve().parents[1] / 'work/corner-resize-tmp'
    directory.mkdir(parents=True, exist_ok=True)
    rooms = [dict(room_id=str(1000 + index), uname=f'Fixture {index}', live=False,
                  muted=True, volume=40) for index in range(16)]
    initial_state = dict(plugins_enabled=[], settings=dict(recording_enabled=False,
                         recording_replay_enabled=False, preview_on_hover=False, auto_update=False))

    def window(state):
        result = MainWindow(deepcopy(rooms), deepcopy(rooms), layout_id='3x3', state=deepcopy(state))
        result.setGeometry(-9000, -9000, 1800, 1500)
        result.show()
        QTest.qWait(900)
        return result

    with tempfile.TemporaryDirectory(dir=directory) as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')))
        stack.enter_context(patch.dict(os.environ, {'DDM_NO_SAVE': ''}))
        stack.enter_context(patch.object(bili, 'SESSION_DATA', ''))
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method))
        first = window(initial_state)
        try:
            before_slots = first.current_state()['wall']
            # 所有可拖预设各写一次，各自的比例互不覆盖。
            for identifier in layouts.BY_ID:
                if identifier in ('corner', '1x1'):
                    continue
                first.wall.set_layout(identifier)
                app.processEvents()
                key = next(iter(first.wall._preset_dividers))
                handle, point = border_for(first.wall, key)
                node = first.wall._preset_dividers[key][0]
                direction = QPoint(1, 0) if node.axis == Qt.Horizontal else QPoint(0, 1)
                drag(app, handle, direction * 25, pos=point)
            first.wall.set_layout('3x3')
            key = ('root', 0)
            handle, point = border_for(first.wall, key)
            QTest.qWait(850)
            with patch.object(config, 'save', wraps=config.save) as save:
                origin = begin(handle, pos=point)
                move_to(handle, origin + QPoint(0, 30))
                QTest.qWait(850)
                save.assert_not_called()
                release_at(handle, origin + QPoint(0, 35))
                QTest.qWait(850)
                assert save.call_count == 1
            border = first.wall._pane_borders[first.wall.tiles[0]]
            with patch.object(config, 'save', wraps=config.save) as save:
                origin = press(border, ["right", "bottom"])
                move_to(border, origin + QPoint(20, 20))
                QTest.qWait(850)
                save.assert_not_called()
                release_at(border, origin + QPoint(35, 35))
                QTest.qWait(850)
                assert save.call_count == 1
            with patch.object(config, 'save', wraps=config.save) as save:
                QTest.mouseDClick(border, Qt.LeftButton, pos=point_on(border, ["right", "bottom"]))
                QTest.qWait(850)
                assert save.call_count == 1, "two-axis reset must save only once"
                QTest.mouseDClick(border, Qt.LeftButton, pos=point_on(border, ["right", "bottom"]))
                QTest.qWait(850)
                assert save.call_count == 1, "repeating an unchanged reset must not write again"
            saved = first.wall.layout_ratios()
            assert len(saved) == 24
            assert config.load()['ui']['layout_ratios'] == saved
            assert first.current_state()['wall'] == before_slots
            geometries = {}
            for identifier in saved:
                first.wall.set_layout(identifier)
                geometries[identifier] = [tile.geometry() for tile in first.wall.visible_tiles()]
        finally:
            first.close()
            app.processEvents()
        second = window(config.load())
        try:
            assert second.wall.layout_ratios() == saved
            for identifier, rectangles in geometries.items():
                second.wall.set_layout(identifier)
                assert [tile.geometry() for tile in second.wall.visible_tiles()] == rectangles, identifier
            second.wall.set_layout('3x3')
            # Sidebar 当前布局由应用信号同步，而非仅给 WallGrid 设置 ID。
            second.sidebar.set_layout_name('3x3')
            slots = second.current_state()['wall']
            originals = list(second.wall.tiles)
            ids = [int(tile.video.winId()) for tile in originals]
            handle, point = border_for(second.wall, key)
            origin = begin(handle, pos=point)
            move_to(handle, origin + QPoint(0, 80))
            second.sidebar.open_layout_picker()
            picker = second.sidebar._picker
            assert picker.reset_button.isVisible()
            card = next(card for cards in picker._cards.values() for card in cards
                        if card.property('layoutId') == '3x3')
            assert '再次点击恢复默认比例' in card.toolTip()
            with patch.object(config, 'save', wraps=config.save) as save:
                QTest.mouseClick(card, Qt.LeftButton)
                QTest.qWait(850)
                assert save.call_count == 1
                assert not picker.isVisible()
            expected = {identifier: ratios for identifier, ratios in saved.items() if identifier != '3x3'}
            assert second.wall.layout_ratios() == expected
            assert config.load()['ui']['layout_ratios'] == expected
            assert second.current_state()['wall'] == slots and second.wall.tiles == originals
            assert [int(tile.video.winId()) for tile in originals] == ids
            assert second.wall._border_pending is None
        finally:
            second.close()
            app.processEvents()
        third = window(config.load())
        try:
            assert third.wall.layout_ratios() == expected
            # 密集横屏网格的最小宽度不能挡住切竖屏，也不能污染各方向的布局记忆。
            third._on_layout_changed('4x4')
            third._on_layout_changed('portrait_main4')
            app.processEvents()
            assert third.orientation == 'portrait' and third.height() > third.width()
            assert third._layout_by_orientation['landscape'] == '4x4'
            third._on_layout_changed('4x4')
            app.processEvents()
            assert third.orientation == 'landscape'
            assert third._layout_by_orientation['portrait'] == 'portrait_main4'
            third.showMaximized()
            app.processEvents()
            third._on_layout_changed('portrait_main2')
            app.processEvents()
            assert not third.isMaximized() and third.orientation == 'portrait'
            assert third.wall.layout_ratios() == expected
        finally:
            third.close()
            app.processEvents()
    print('PASS: malformed config, all 24 presets disk/restart, release-only save, current-only popup reset, stable rooms/audio/IDs')


if __name__ == '__main__':
    main()
