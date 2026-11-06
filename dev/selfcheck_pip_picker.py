"""Isolated main-window checks for the PiP room picker and draggable preview."""
import faulthandler
import unittest
from unittest.mock import patch

import selfcheck_main_notices as fixtures
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget


class PipPickerTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    setUp = fixtures.MainNoticesTests.setUp
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

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
        self.assertEqual([heading.text() for heading, _keys in dialog.sections], ['已入墙', '其他已开播'])
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



if __name__ == '__main__':
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        unittest.main(verbosity=2)
    finally:
        faulthandler.cancel_dump_traceback_later()
