"""Isolated main-window checks for the PiP room picker and draggable preview."""
import faulthandler
import unittest
from unittest.mock import patch

import selfcheck_main_notices as fixtures
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget


class PipPickerTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    setUp = fixtures.MainNoticesTests.setUp
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

    def test_vanity_room_search_survives_status_refresh_and_state_restore(self):
        from ddm import config
        from ddm.widgets import Sidebar
        window = self.window([])
        sidebar = window.sidebar
        room = dict(room_id='douyu:6979222', uname='测试主播', platform='douyu',
                    playback_mode='stream', uid=6657, title='标题含6657', live=True)
        sidebar.add_room(room)
        sidebar.search.setText('6657')
        self.assertEqual(sidebar.visible_items(), [])
        with patch('ddm.bili.requests.get', side_effect=AssertionError('Search must not access the network')):
            status = dict(live=True, uname='测试主播', title='标题含6657', viewers='', face='', display_room_id='6657')
            window._on_status_updated({'douyu:6979222': status})
            self.assertEqual([item.room['room_id'] for item in sidebar.visible_items()], ['douyu:6979222'])
            for query in ('6657', '6979222', '测试 6657'):
                sidebar.search.setText(query)
                self.assertEqual(len(sidebar.visible_items()), 1)
            state = window.current_state()
            self.assertEqual(state['platform_rooms']['douyu:6979222']['display_room_id'], '6657')
            follows, _wall = config.build_rooms(state)
            restored = Sidebar(follows, window, auto_compact=False)
            self.addCleanup(restored.deleteLater)
            restored.apply_filter('6657')
            self.assertEqual([item.room['room_id'] for item in restored.visible_items()], ['douyu:6979222'])
            window.picture_in_picture.manage()
            dialog = window.picture_in_picture.dialog
            dialog.search.setText('6657')
            self.assertFalse(dialog.checks['douyu:6979222'].isHidden())
            dialog.reject()
            sidebar.search.setText('6657')
            window._on_status_updated({'douyu:6979222': dict(status, display_room_id='7788')})
            self.assertEqual(sidebar.visible_items(), [])
            sidebar.search.setText('7788')
            self.assertEqual(len(sidebar.visible_items()), 1)
            window._on_status_updated({'douyu:6979222': dict(status, display_room_id='')})
            self.assertEqual(sidebar.visible_items(), [])

    def test_chat_backing_rooms_only_appear_in_follow_groups(self):
        rooms = [dict(room_id=str(index + 1), uname=f'Room {index + 1}', live=True)
                 for index in range(6)]
        window = self.window(rooms)
        wall, pip = window.wall, window.picture_in_picture
        wall.set_layout('corner')
        window.configure_wall_panes({1: wall.tiles[0], 2: wall.tiles[4]})
        tiles = list(wall.tiles)
        bindings = wall.pane_danmaku.state()
        self.assertTrue(tiles[1].isHidden() and tiles[2].isHidden())
        window.start_tile.reset_mock()
        groups = pip.candidate_groups()
        self.assertEqual([key for key, _room in groups[0][1]], [0, 3, 4, 5])
        pip.manage()
        dialog = pip.dialog
        self.assertEqual(dialog._selected(), [0, 3, 4, 5])
        self.assertNotIn(1, dialog.checks)
        self.assertNotIn(2, dialog.checks)
        self.assertIn('2', dialog.checks)
        self.assertIn('3', dialog.checks)
        dialog.reject()
        self.assertEqual(wall.tiles, tiles)
        self.assertEqual(wall.pane_danmaku.state(), bindings)
        window.start_tile.assert_not_called()

    def test_restored_chat_selection_is_not_checked_and_can_be_selected_as_live_follow(self):
        rooms = [dict(room_id=str(index + 1), uname=f'Room {index + 1}', live=True)
                 for index in range(6)]
        window = self.window(rooms)
        wall, pip = window.wall, window.picture_in_picture
        wall.set_layout('corner')
        window.configure_wall_panes({1: None, 2: None})
        tiles = list(wall.tiles)
        bindings = wall.pane_danmaku.state()
        pip.selection, pip.primary = list(range(6)), 1
        pip.manage()
        dialog = pip.dialog
        self.assertEqual(dialog._selected(), [0, 3, 4, 5])
        self.assertFalse(dialog.checks['2'].isChecked())
        dialog.checks['2'].setChecked(True)
        self.assertEqual(dialog._selected(), [0, 3, 4, 5, '2'])
        self.assertTrue(pip.start(dialog._selected()))
        self.assertNotIn(1, pip.selection)
        self.assertNotIn(2, pip.selection)
        self.assertIsNot(pip._extra_tiles['2'], tiles[1])
        dialog.reject()
        pip.restore(activate=False)
        self.assertEqual(wall.tiles, tiles)
        self.assertEqual(wall.pane_danmaku.state(), bindings)
        self.assertTrue(tiles[1].isHidden() and tiles[2].isHidden())

    def test_managing_active_pip_keeps_unselected_video_cells_available(self):
        window = self.window([dict(room_id=str(index + 1), live=True) for index in range(6)])
        wall, pip = window.wall, window.picture_in_picture
        wall.set_layout('corner')
        window.configure_wall_panes({1: None, 2: None})
        self.assertTrue(pip.start([0, 3]))
        self.assertTrue(wall.tiles[4].isHidden() and wall.tiles[5].isHidden())
        self.assertEqual([key for key, _room in pip.candidate_groups()[0][1]], [0, 3, 4, 5])
        pip.manage()
        dialog = pip.dialog
        self.assertEqual(dialog._selected(), [0, 3])
        self.assertIn(4, dialog.checks)
        self.assertIn(5, dialog.checks)
        dialog.reject()
        pip.restore(activate=False)

    def test_active_external_tile_indices_remain_valid_when_reordering(self):
        window = self.window([dict(room_id='1', live=True)])
        window.sidebar.add_rooms([dict(room_id='2', live=True)])
        pip = window.picture_in_picture
        self.assertTrue(pip.start([0, '2']))
        temporary = pip._extra_tiles['2']
        order = list(reversed(pip.selection))
        self.assertTrue(pip.start(order))
        self.assertEqual(window.wall.picture_in_picture_tiles, [temporary, window.wall.tiles[0]])
        self.assertEqual(pip.external_rooms, ['2'])
        pip.restore(activate=False)

    def test_chat_backing_index_cannot_be_applied_after_picker_layout_changes(self):
        window = self.window([dict(room_id=str(index + 1), live=True) for index in range(6)])
        window.wall.set_layout('corner')
        pip = window.picture_in_picture
        self.assertIn(1, dict(pip.candidate_groups()[0][1]))
        window.configure_wall_panes({1: None, 2: None})
        self.assertFalse(pip.start([0, 1]))
        self.assertFalse(pip.active)

    def test_pip_picker_lists_wall_first_then_live_follows_without_allocating_players(self):
        from ddm.picture_in_picture import FOCUS_LAYOUT
        window = self.window([{'room_id': '1', 'uname': 'Wall', 'live': False},
                              {'room_id': '2', 'uname': 'Wall live', 'live': True}])
        window.settings['close_behavior'] = 'exit'
        window.sidebar.add_rooms([{'room_id': str(index), 'uname': f'Other {index}', 'live': True}
                                  for index in range(3, 7)] +
                                 [{'room_id': '7', 'live': False}, {'room_id': '8', 'live': True, 'live_known': False}])
        pip = window.picture_in_picture
        tiles = list(window.wall.tiles)
        pip.manage()
        dialog = pip.dialog
        self.assertEqual(list(dialog.checks), [0, 1, '3', '4', '5', '6'])
        self.assertEqual([heading.text() for heading, _keys in dialog.sections], ['已入墙', '默认关注'])
        self.assertEqual(dialog._selected(), [0, 1])
        self.assertEqual(dialog.columns.count(), 6)
        for rid in ('3', '4', '5', '6'):
            dialog.checks[rid].setChecked(True)
        dialog.columns.setCurrentIndex(dialog.columns.findData(FOCUS_LAYOUT))
        from selfcheck_picture_in_picture import drag_preview
        drag_preview(dialog, '4', 0)
        self.assertTrue(dialog.start.isEnabled())
        self.assertEqual(dialog.preview.primary, 0)
        dialog.search.setText('Other 4')
        self.assertTrue(dialog.checks[0].isHidden())
        self.assertFalse(dialog.checks['4'].isHidden())
        self.assertEqual(len(dialog._selected()), 6)
        dialog.reject()
        self.assertEqual(window.wall.tiles, tiles)
        self.assertFalse(pip._extra_tiles)
        window.start_tile.assert_not_called()


    def test_pip_external_session_does_not_change_saved_wall_and_releases_on_exit(self):
        window = self.window([{'room_id': '1', 'live': False}])
        window.settings['close_behavior'] = 'exit'
        window.sidebar.add_rooms([{'room_id': '2', 'uname': 'Extra', 'live': True}])
        pip, wall = window.picture_in_picture, window.wall
        tiles = list(wall.tiles)
        snapshot = window.current_state()['wall']
        with patch.object(window, '_stop_tile', wraps=window._stop_tile) as stop:
            self.assertTrue(pip.start([0, '2'], primary='2'))
            temporary = pip._extra_tiles['2']
            self.assertTrue(temporary.property('pictureInPictureTemporary'))
            window.start_tile.assert_called_once_with(temporary)
            self.assertEqual(window.current_state()['wall'], snapshot)
            self.assertEqual(pip.state()['external_rooms'], ['2'])
            self.assertEqual(pip.state()['external_primary'], '2')
            self.assertEqual(pip.state()['choice_order'], [0, '2'])
            window._refresh_meta()
            self.assertEqual(window.sidebar._wall_room_ids, {'1'})
            pip.restore()
            self.assertEqual(wall.tiles, tiles)
            self.assertFalse(pip._extra_tiles)
            stop.assert_called_once_with(temporary)
            self.assertEqual(window.current_state()['wall'], snapshot)
        room = next(room for room in window.sidebar.rooms() if room['room_id'] == '2')
        room['live'] = False
        self.assertFalse(pip.start(['2']))
        self.assertFalse(pip._extra_tiles)


    def test_pip_preview_drag_swaps_positions_and_escape_or_outside_cancels(self):
        from PySide6.QtWidgets import QComboBox
        from selfcheck_picture_in_picture import drag_preview, pointer
        from ddm.picture_in_picture import FOCUS_LAYOUT
        window = self.window([{'room_id': str(i), 'uname': f'Room {i}', 'live': False} for i in range(6)])
        window.settings['close_behavior'] = 'exit'
        window.wall.set_layout('3x2')
        pip = window.picture_in_picture
        pip.manage()
        dialog = pip.dialog
        before = list(pip.selection)
        dialog.columns.setCurrentIndex(dialog.columns.findData(FOCUS_LAYOUT))
        self.assertFalse(hasattr(dialog, 'primary_row'))
        self.assertEqual(len(dialog.findChildren(QComboBox)), 1)
        drag_preview(dialog, 1, 0)
        self.assertEqual(dialog._selected()[:2], [1, 0])
        self.assertEqual(dialog._primary, 1)
        self.assertEqual(dialog.preview.labels[0]._full_text, dialog.checks[1].preview_name)
        drag_preview(dialog, 2, 1, cancel=True)
        self.assertEqual(dialog._primary, 1)
        self.assertEqual(dialog._selected()[:2], [1, 0])
        preview = dialog.preview
        label = preview.labels[0]
        point = label.mapToGlobal(label.rect().center())
        pointer(label, QEvent.MouseButtonPress, label.rect().center(), point, Qt.LeftButton, Qt.LeftButton)
        outside = preview.mapToGlobal(QPoint(-30, -30))
        pointer(preview, QEvent.MouseMove, QPoint(-30, -30), outside, Qt.NoButton, Qt.LeftButton)
        pointer(preview, QEvent.MouseButtonRelease, QPoint(-30, -30), outside, Qt.LeftButton, Qt.NoButton)
        self.assertEqual(dialog._selected()[:2], [1, 0])
        self.assertIsNone(QWidget.mouseGrabber())
        for mode in (0, 16, 1, 2, 3):
            dialog.columns.setCurrentIndex(dialog.columns.findData(mode))
            drag_preview(dialog, 2, 3)
            self.assertEqual(set(dialog._selected()), set(before))
        dialog.reject()
        self.assertEqual(pip.selection, before)
        self.assertFalse(pip.active)
        window.start_tile.assert_not_called()


    def test_pip_room_grid_adapts_and_search_reflows_without_losing_selection(self):
        window = self.window([{'room_id': '1', 'uname': 'Wall', 'live': False}])
        window.settings['close_behavior'] = 'exit'
        window.sidebar.add_rooms([{'room_id': str(5000+i), 'uname': f'主播 {i}', 'live': True} for i in range(80)])
        pixmap = QPixmap(28, 28)
        pixmap.fill(QColor('red'))
        with patch.object(window.sidebar.items()[0].thumb, 'face_pixmap', return_value=pixmap):
            window.picture_in_picture.manage()
        dialog = window.picture_in_picture.dialog
        self.app.processEvents()
        self.assertEqual(dialog.checks[0].avatar._source.cacheKey(), pixmap.cacheKey())
        others = [dialog.checks[str(5000+i)] for i in range(80)]
        self.assertGreaterEqual(len({button.x() for button in others}), 3)
        self.assertLess(others[0].height(), 80)
        self.assertEqual(others[0].y(), others[1].y())
        QTest.mouseClick(others[0], Qt.LeftButton)
        self.assertTrue(others[0].badge.isVisible())
        dialog.search.setText('5079')
        self.app.processEvents()
        self.assertFalse(others[-1].isHidden())
        self.assertTrue(all(button.isHidden() for button in others[:-1]))
        self.assertEqual(dialog.choice_grids[1].getItemPosition(0)[:2], (0, 0))
        self.assertIn('5000', dialog._selected())
        dialog.search.clear()
        dialog.resize(360, 650)
        self.app.processEvents()
        self.assertEqual(len({button.x() for button in others}), 2)
        self.assertTrue(others[0].isChecked())
        for first, second in zip(others, others[1:]):
            self.assertFalse(first.geometry().intersects(second.geometry()))
        self.assertIn('5000', others[0].toolTip())
        dialog.reject()
        self.assertFalse(window.picture_in_picture._extra_tiles)

    def test_pip_folder_blocks_repeat_wall_and_synchronize_selection(self):
        window = self.window([{'room_id': '1', 'uname': 'Wall', 'live': False}])
        sidebar = window.sidebar
        sidebar.add_rooms([{'room_id': '2', 'uname': 'Music', 'live': True},
                           {'room_id': '3', 'uname': 'Game', 'live': True},
                           {'room_id': '4', 'uname': 'Default', 'live': True},
                           {'room_id': '5', 'live': False},
                           {'room_id': '6', 'live': True, 'live_known': False}])
        music = sidebar.create_folder('音乐')
        games = sidebar.create_folder('游戏')
        sidebar.create_folder('空文件夹')
        sidebar.move_to_folder(['1', '2'], music)
        sidebar.move_to_folder(['3'], games)
        sidebar.toggle_folder(music)
        before = sidebar.folder_state()
        pip = window.picture_in_picture
        pip.manage()
        dialog = pip.dialog
        self.app.processEvents()
        self.assertEqual([heading.text() for heading, _buttons in dialog.sections],
                         ['已入墙', '音乐', '游戏', '默认关注'])
        self.assertEqual([[button.choice for button in buttons] for _heading, buttons in dialog.sections],
                         [[0], [0, '2'], ['3'], ['4']])
        top, folder = dialog.choice_buttons[0]
        self.assertIsNot(top.parentWidget(), folder.parentWidget())
        self.assertTrue(top.isChecked() and folder.isChecked())
        QTest.mouseClick(folder, Qt.LeftButton)
        self.assertFalse(top.isChecked() or folder.isChecked())
        self.assertEqual(dialog._selected(), [])
        QTest.mouseClick(top, Qt.LeftButton)
        self.assertTrue(top.isChecked() and folder.isChecked())
        self.assertTrue(top.badge.isVisible() and folder.badge.isVisible())
        QTest.keyClick(folder, Qt.Key_Space)
        self.assertFalse(top.isChecked() or folder.isChecked())
        QTest.keyClick(folder, Qt.Key_Space)
        self.assertTrue(top.isChecked() and folder.isChecked())
        dialog.checks['3'].setChecked(True)
        dialog.search.setText('游戏')
        self.assertTrue(top.isHidden() and folder.isHidden())
        self.assertEqual(dialog._selected(), [0, '3'])
        dialog.search.clear()
        self.assertTrue(folder.isChecked())
        dialog.start.click()
        self.assertTrue(pip.active)
        self.assertEqual(len(window.wall.picture_in_picture_tiles), 2)
        self.assertEqual(pip.selected_choices(), [0, '3'])
        pip.restore()
        self.assertEqual(sidebar.folder_state(), before)

    def test_pip_search_matches_sidebar_chinese_pinyin_initials_and_multiple_words(self):
        window = self.window([{'room_id': '9101', 'uname': '小明', 'title': '深夜音乐', 'live': True}])
        sidebar = window.sidebar
        sidebar.add_rooms([{'room_id': '9102', 'uname': '重庆主播', 'live': True},
                           {'room_id': '9103', 'uname': 'Alice', 'title': 'Morning Coffee', 'live': True},
                           {'room_id': '9104', 'uname': '大橙橙橙子', 'live': True}])
        music = sidebar.create_folder('音乐区')
        sidebar.move_to_folder(['9101'], music)
        window.picture_in_picture.manage()
        dialog = window.picture_in_picture.dialog
        for query in ('小明', 'xiaoming', 'XM', 'xiao ming', 'xiaoming 9101',
                      '音乐区', 'yinyuequ', 'YYQ xm', 'chongqing', 'cqzb',
                      'ALICE', 'dcz', 'dcccz', '9102', 'Morning', '深夜音乐', 'missing'):
            with self.subTest(query=query):
                sidebar.search.setText(query)
                expected = {str(item.room['room_id']) for item in sidebar.visible_items()}
                dialog.search.setText(query)
                actual = {str(dialog.rooms[key]['room_id']) for key, button in dialog.checks.items()
                          if not button.isHidden()}
                self.assertEqual(actual, expected)
                self.assertEqual(dialog._selected(), [0])
        dialog.search.clear()
        dialog.search.setFocus()
        QTest.keyClicks(dialog.search, 'XM')
        self.assertEqual(dialog.search.text(), 'XM')
        self.assertFalse(dialog.checks[0].isHidden())
        self.assertTrue(dialog.checks['9102'].isHidden())
        window._on_status_updated({'9101': {'live': True, 'uname': '小红', 'title': '', 'viewers': '', 'face': ''}})
        dialog.search.setText('xiaohong')
        self.assertFalse(dialog.checks[0].isHidden())
        dialog.search.setText('xiaoming')
        self.assertTrue(dialog.checks[0].isHidden())
        dialog.search.clear()
        self.assertTrue(dialog.checks[0].isChecked())
        dialog.reject()

    def test_pip_smart_folder_copies_share_one_choice_with_the_wall_and_original(self):
        window = self.window([{'room_id': '1', 'uname': 'Wall', 'live': True}])
        sidebar = window.sidebar
        sidebar.add_rooms([{'room_id': '2', 'uname': 'Moved', 'live': True, 'platform': 'huya'}])
        window._on_status_updated({'2': {'live': True, 'uname': 'Moved', 'title': '', 'viewers': '', 'face': ''}})
        sidebar.create_folder('智能复制', rule={'status': 'live', 'sources': [], 'display': 'copy'})
        sidebar.create_folder('智能移入', rule={'status': 'live', 'sources': [],
                                               'platforms': ['huya'], 'display': 'move'})
        window.picture_in_picture.manage()
        dialog = window.picture_in_picture.dialog
        self.assertEqual([heading.text() for heading, _buttons in dialog.sections],
                         ['已入墙', '智能复制', '智能移入', '默认关注'])
        self.assertEqual([[button.choice for button in buttons] for _heading, buttons in dialog.sections],
                         [[0], [0, '2'], ['2'], [0]])
        self.assertEqual(len(dialog.choice_buttons[0]), 3)
        for button in dialog.choice_buttons[0]:
            self.assertTrue(button.isChecked())
        dialog.choice_buttons[0][-1].setChecked(False)
        self.assertTrue(all(not button.isChecked() for button in dialog.choice_buttons[0]))
        dialog.choice_buttons[0][1].setChecked(True)
        self.assertEqual(dialog._selected(), [0])
        dialog.choice_buttons['2'][0].setChecked(True)
        self.assertTrue(all(button.isChecked() for button in dialog.choice_buttons['2']))
        self.assertEqual(dialog._selected(), [0, '2'])
        dialog.search.setText('智能复制')
        self.assertEqual([heading.text() for heading, _buttons in dialog.sections if not heading.isHidden()],
                         ['智能复制'])
        self.assertEqual(dialog._selected(), [0, '2'])
        dialog.reject()

    def test_pip_folder_names_stay_readable_when_theme_changes(self):
        from ddm import theme
        from ddm.ui import ElidedLabel
        window = self.window([{'room_id': '1', 'uname': '主播', 'live': True}])
        window.picture_in_picture.manage()
        dialog = window.picture_in_picture.dialog
        original = theme.mode()
        try:
            for mode in ('dark', 'light', 'dark'):
                theme.apply(mode)
                self.app.processEvents()
                for button in dialog.choice_buttons[0]:
                    label = button.findChild(ElidedLabel)
                    self.assertEqual(label.palette().color(QPalette.WindowText), QColor(theme.TEXT1), mode)
        finally:
            theme.apply(original)
        dialog.reject()



if __name__ == '__main__':
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        unittest.main(verbosity=2)
    finally:
        faulthandler.cancel_dump_traceback_later()
