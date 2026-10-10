"""比例磁盘保存、重启恢复、配置校验和整体重置；使用临时配置，不联网。"""
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from selfcheck_corner_resize import QApplication, QPoint, QTest, Qt, WallGrid, drag, theme
from selfcheck_corner_drag_updates import begin, move_to, release_at
from ddm import bili, config
from ddm.app import MainWindow
from ddm.widgets import LayoutPicker


DEFAULT = dict(width=2 / 3, height=2 / 3, right=1 / 2, bottom=[1 / 3, 2 / 3])


def make_window(state):
    rooms = [{"room_id": str(1000 + index), "uname": f"Fixture {index}", "live": False,
              "muted": True, "volume": 40} for index in range(6)]
    window = MainWindow(rooms, deepcopy(rooms), layout_id="corner", state=deepcopy(state))
    window.setGeometry(-9000, -9000, 1600, 1100)
    window.show()
    QTest.qWait(900)
    return window


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    wall = WallGrid([], layout_id="corner")
    try:
        assert wall.corner_ratios() == DEFAULT, "旧配置应继续使用默认比例"
        valid = dict(width=.6, height=.7, right=.55, bottom=[.25, .7])
        wall.restore_corner_ratios(valid)
        assert wall.corner_ratios() == valid
        detached = wall.corner_ratios()
        detached['bottom'][0] = .9
        assert wall.corner_ratios() == valid, "导出的配置不能修改内部状态"
        invalid = [None, [], 'bad', 1, True]
        for data in invalid:
            wall.restore_corner_ratios(data)
            assert wall.corner_ratios() == DEFAULT
        for value in (None, True, False, '0.5', -1, 0, 1, 2, float('nan'), float('inf'), {}):
            wall.restore_corner_ratios(dict(width=value, height=value, right=value, bottom=[value, .7]))
            assert wall.corner_ratios() == DEFAULT
        for bottom in ([], [.3], [.2, .4, .6], [.7, .3], [.3, .3], 'bad', None):
            wall.restore_corner_ratios(dict(bottom=bottom))
            assert wall.corner_ratios() == DEFAULT
        wall.restore_corner_ratios(dict(width=.6, height='bad'))
        assert wall.corner_ratios() == dict(DEFAULT, width=.6)
    finally:
        wall.close()

    directory = Path(__file__).resolve().parents[1] / 'work/corner-resize-tmp'
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=directory) as temporary, ExitStack() as stack:
        path = Path(temporary) / 'config.json'
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(path)))
        stack.enter_context(patch.dict(os.environ, {'DDM_NO_SAVE': ''}))
        stack.enter_context(patch.object(bili, 'SESSION_DATA', ''))
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars'):
            stack.enter_context(patch.object(MainWindow, method))
        state = dict(plugins_enabled=[], settings=dict(recording_enabled=False,
                     recording_replay_enabled=False, preview_on_hover=False, auto_update=False))
        window = make_window(state)
        try:
            assert window.wall.corner_ratios() == DEFAULT
            with patch.object(config, 'save', wraps=config.save) as save:
                origin = begin(window.wall._corner_width_handle)
                move_to(window.wall._corner_width_handle, origin + QPoint(40, 0))
                QTest.qWait(80)
                save.assert_not_called()
                release_at(window.wall._corner_width_handle, origin + QPoint(50, 0))
                for handle, movement in ((window.wall._corner_height_handle, QPoint(0, -40)),
                                         (window.wall._corner_right_handle, QPoint(0, 35)),
                                         (window.wall._corner_bottom_handles[0], QPoint(35, 0)),
                                         (window.wall._corner_bottom_handles[1], QPoint(-25, 0))):
                    drag(app, handle, movement)
                save.assert_not_called()
                QTest.qWait(850)
                assert save.call_count == 1, "连续松开操作应由现有保存定时器合并"
            ratios = window.wall.corner_ratios()
            saved_rectangles = [tile.geometry() for tile in window.wall.tiles]
            saved = config.load()
            assert saved['ui']['corner_ratios'] == ratios
            window.wall.set_layout('3x3')
            assert window.current_state()['ui']['corner_ratios'] == ratios
        finally:
            window.close()
            app.processEvents()

        restarted = make_window(config.load())
        try:
            assert restarted.wall.corner_ratios() == ratios
            assert [tile.geometry() for tile in restarted.wall.tiles] == saved_rectangles
            tiles = list(restarted.wall.tiles)
            video_ids = [int(tile.video.winId()) for tile in tiles]
            slots = restarted.current_state()['wall']
            # 重置还要取消已经排队、但尚未应用的拖动，避免稍后改回旧位置。
            origin = begin(restarted.wall._corner_width_handle)
            move_to(restarted.wall._corner_width_handle, origin + QPoint(40, 0))
            restarted.sidebar.open_layout_picker()
            picker = restarted.sidebar._picker
            assert picker.reset_button.isVisible() and picker.reset_button.isEnabled()
            picker.grab().save(str(directory.parent / 'corner-reset-picker.png'))
            QTest.mouseClick(picker.reset_button, Qt.LeftButton)
            app.processEvents()
            assert restarted.wall.corner_ratios() == DEFAULT
            assert not picker.isVisible()
            assert restarted.wall.tiles == tiles
            assert [int(tile.video.winId()) for tile in tiles] == video_ids
            assert restarted.current_state()['wall'] == slots
            QTest.qWait(850)
            assert config.load()['ui']['corner_ratios'] == DEFAULT
            # 其他布局没有这个入口，但会继续记住一大五小的比例。
            other = LayoutPicker('3x3')
            other.show()
            app.processEvents()
            assert not other.reset_button.isVisible()
            other.close()
            restarted.wall._drag_corner(Qt.Horizontal, restarted.wall.tiles[0].x() + 500)
            restarted.wall.set_fullscreen_tile(restarted.wall.tiles[0])
            restarted.wall.reset_corner_ratios()
            assert restarted.wall.fullscreen_tile is restarted.wall.tiles[0]
            restarted.wall.set_fullscreen_tile(None)
            assert restarted.wall.corner_ratios() == DEFAULT
        finally:
            restarted.close()
            app.processEvents()
        restarted_again = make_window(config.load())
        try:
            assert restarted_again.wall.corner_ratios() == DEFAULT
        finally:
            restarted_again.close()
            app.processEvents()
        assert json.loads(path.read_text(encoding='utf-8'))['ui']['corner_ratios'] == DEFAULT
    print('PASS: validated ratios, release-only debounced disk save, restart/other layouts, '
          'reset popup, unchanged slots/native handles and reset survives restart')


if __name__ == '__main__':
    main()
