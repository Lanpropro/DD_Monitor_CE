"""Isolated main-window checks for the PiP room picker and draggable preview."""
import faulthandler
import json
import sys
import unittest
from unittest.mock import patch

import selfcheck_main_notices as fixtures
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu, QScrollArea, QWidget


class PipPickerTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    setUp = fixtures.MainNoticesTests.setUp
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

    def test_toolbar_picker_stays_inside_the_main_window_on_open_drag_and_resize(self):
        from ddm.pip_composition import FREE_LAYOUT
        from selfcheck_picture_in_picture import pointer

        window = self.window([dict(room_id='1', uname='Wall', live=True)])
        window.sidebar.add_rooms([dict(room_id=str(i), uname=f'Followed {i}', live=True) for i in range(2, 7)])
        button = window.sidebar.picture_in_picture_button
        self.assertTrue(button.isVisible())
        available = window.screen().availableGeometry()
        window.move(available.topLeft() + QPoint(22, 22))
        self.app.processEvents()
        def bounds():
            return QRect(window.mapToGlobal(QPoint()), window.size()).intersected(available).adjusted(8, 8, -8, -8)
        anchor = QRect(button.mapToGlobal(QPoint()), button.size())
        button.click()
        pip = window.picture_in_picture
        dialog = pip.dialog
        self.assertIsNotNone(dialog)
        self.assertLessEqual(dialog.width(), 424)
        self.assertLessEqual(dialog.height(), 516)
        self.assertTrue(bounds().contains(dialog.geometry()))
        self.assertEqual(dialog.grab().toImage().pixelColor(0, 0).alpha(), 0)
        if anchor.right() + 8 + dialog.width() <= bounds().right():
            self.assertEqual(dialog.x(), anchor.right() + 9)

        for room in ('2', '3', '4', '5', '6'):
            dialog.checks[room].setChecked(True)
        self.app.processEvents()
        self.assertTrue(dialog.arrangements.buttons[FREE_LAYOUT].isVisible())
        self.assertTrue(dialog.rect().contains(QRect(dialog.start.mapTo(dialog, QPoint()), dialog.start.size())))

        header = dialog.titlebar
        local = header.rect().center()
        pressed = header.mapToGlobal(local)
        outside = bounds().bottomRight() + QPoint(150, 150)
        pointer(header, QEvent.MouseButtonPress, local, pressed, Qt.LeftButton, Qt.LeftButton)
        pointer(header, QEvent.MouseMove, header.mapFromGlobal(outside), outside, Qt.NoButton, Qt.LeftButton)
        pointer(header, QEvent.MouseButtonRelease, header.mapFromGlobal(outside), outside, Qt.LeftButton, Qt.NoButton)
        self.assertEqual(dialog.geometry().bottomRight(), bounds().bottomRight())
        moved_position = dialog.pos()
        pip.manage(anchor=button)
        self.assertIs(pip.dialog, dialog)
        self.assertEqual(dialog.pos(), moved_position)

        window.resize(390, 370)
        self.app.processEvents()
        self.assertTrue(bounds().contains(dialog.geometry()))
        outer = dialog.findChild(QScrollArea, 'PipToolbarViewport')
        self.assertGreater(outer.verticalScrollBar().maximum(), 0)
        self.assertTrue(dialog.rect().contains(QRect(dialog.start.mapTo(dialog, QPoint()), dialog.start.size())))
        dialog.reject()

    def test_toolbar_picker_dismisses_on_outside_click_or_lost_activation(self):
        from PySide6.QtWidgets import QApplication

        window = self.window([dict(room_id='1', uname='Wall', live=True)])
        pip = window.picture_in_picture
        button = window.sidebar.picture_in_picture_button
        QTest.mouseClick(button, Qt.LeftButton)
        dialog = pip.dialog
        QTest.mouseClick(dialog.search, Qt.LeftButton)
        QTest.keyClicks(dialog.search, 'Wall')
        self.assertEqual(dialog.search.text(), 'Wall')
        self.assertIs(pip.dialog, dialog)

        menu = QMenu(dialog.search)
        item = menu.addAction('Search action')
        menu.popup(dialog.search.mapToGlobal(dialog.search.rect().bottomLeft()))
        self.app.processEvents()
        self.assertIs(QApplication.activePopupWidget(), menu)
        QTest.mouseClick(menu.windowHandle(), Qt.LeftButton, pos=menu.actionGeometry(item).center())
        self.assertFalse(menu.isVisible())
        self.assertIs(pip.dialog, dialog)

        QTest.mouseClick(window.windowHandle(), Qt.LeftButton, pos=QPoint(window.width() - 30, 60))
        self.assertIsNone(pip.dialog)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertIsNotNone(pip.dialog)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertIsNone(pip.dialog)
        self.assertFalse(pip.active)

        QTest.mouseClick(button, Qt.LeftButton)
        dialog = pip.dialog
        other = QWidget()
        self.addCleanup(other.close)
        other.setAttribute(Qt.WA_ShowWithoutActivating)
        other.show()
        # Deliver the Qt activation transition even when Windows denies foreground focus to CI.
        QApplication.setActiveWindow(dialog)
        self.assertIs(QApplication.activeWindow(), dialog)
        QApplication.setActiveWindow(other)
        self.assertIs(QApplication.activeWindow(), other)
        self.app.processEvents()
        self.assertIsNone(pip.dialog)

    def test_toolbar_picker_remembers_resized_dimensions_after_reopen_and_restore(self):
        from selfcheck_picture_in_picture import pointer

        room = dict(room_id='1', uname='Wall', live=True)
        window = self.window([room])
        available = window.screen().availableGeometry()
        window.move(available.topLeft() + QPoint(22, 22))
        self.app.processEvents()
        button = window.sidebar.picture_in_picture_button
        pip = window.picture_in_picture
        button.click()
        dialog = pip.dialog

        def drag(local, delta):
            pressed = dialog.mapToGlobal(local)
            target = pressed + delta
            pointer(dialog, QEvent.MouseButtonPress, local, pressed, Qt.LeftButton, Qt.LeftButton)
            pointer(dialog, QEvent.MouseMove, dialog.mapFromGlobal(target), target, Qt.NoButton, Qt.LeftButton)
            pointer(dialog, QEvent.MouseButtonRelease, dialog.mapFromGlobal(target), target, Qt.LeftButton, Qt.NoButton)

        original = dialog.geometry()
        window._save_timer.stop()
        drag(QPoint(dialog.width() - 7, dialog.height() - 7), QPoint(55, -34))
        resized = dialog.geometry()
        self.assertEqual(resized.topLeft(), original.topLeft())
        self.assertEqual(resized.height(), original.height() - 34)
        self.assertGreater(resized.width(), original.width())
        self.assertTrue(window._save_timer.isActive())
        drag(QPoint(6, 6), QPoint(36, 25))
        self.assertEqual(dialog.geometry().bottomRight(), resized.bottomRight())
        self.assertEqual(dialog.geometry().topLeft(), resized.topLeft() + QPoint(36, 25))
        remembered = dialog.size()
        self.assertEqual(pip.picker_size, remembered.toTuple())

        drag(QPoint(dialog.width() - 4, dialog.height() // 2), QPoint(2000, 0))
        bounds = QRect(window.mapToGlobal(QPoint()), window.size()).intersected(available).adjusted(8, 8, -8, -8)
        self.assertEqual(dialog.geometry().right(), bounds.right())
        self.assertEqual(dialog.height(), remembered.height())
        remembered = dialog.size()
        window.resize(390, 370)
        self.app.processEvents()
        small_bounds = QRect(window.mapToGlobal(QPoint()), window.size()).intersected(available).adjusted(8, 8, -8, -8)
        self.assertEqual(dialog.size(), remembered.boundedTo(small_bounds.size()))
        self.assertNotEqual(dialog.size(), remembered)
        self.assertEqual(pip.picker_size, remembered.toTuple())
        dialog.reject()
        window.resize(1000, 700)
        self.app.processEvents()
        button.click()
        self.assertEqual(pip.dialog.size(), remembered)
        pip.dialog.reject()

        state = {'ui': json.loads(json.dumps(window.current_state()['ui']))}
        state.update(plugins_enabled=[], settings={'close_behavior': 'exit'})
        window.hide()
        restored = fixtures.MainWindow([room], [room], layout_id='2x2', state=state)
        self.addCleanup(self.close_window, restored)
        restored.resize(window.size())
        restored.move(window.pos())
        restored.show()
        self.app.processEvents()
        restored.sidebar.picture_in_picture_button.click()
        self.assertEqual(restored.picture_in_picture.dialog.size(), remembered)
        restored.picture_in_picture.dialog.reject()

    def test_anchored_picker_flips_at_screen_edges(self):
        window = self.window([])
        window.picture_in_picture.manage()
        dialog = window.picture_in_picture.dialog
        available = QRect(-1400, -150, 1200, 1000)
        bounds = available.adjusted(8, 8, -8, -8)
        anchor = QRect(bounds.left() + 240, bounds.top() + 45, 36, 32)
        dialog.place_near(anchor, available, below=True)
        self.assertEqual(dialog.pos(), QPoint(anchor.left(), anchor.bottom() + 9))
        self.assertTrue(bounds.contains(dialog.geometry()))
        anchor.moveBottom(bounds.bottom() - 10)
        dialog.place_near(anchor, available, below=True)
        self.assertEqual(dialog.y() + dialog.height(), anchor.top() - 8)
        self.assertTrue(bounds.contains(dialog.geometry()))
        anchor.moveTopRight(bounds.topRight() + QPoint(-16, 100))
        dialog.place_near(anchor, available, below=False)
        self.assertEqual(dialog.x() + dialog.width(), anchor.left() - 8)
        self.assertTrue(bounds.contains(dialog.geometry()))
        dialog.reject()

    def test_picker_replaces_the_native_caption_without_losing_window_controls(self):
        window = self.window([dict(room_id='1', uname='Main', live=True)])
        pip = window.picture_in_picture
        pip.manage()
        dialog = pip.dialog
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
        if self.app.platformName() == 'windows':
            import ctypes
            from ctypes import wintypes
            window_style = ctypes.windll.user32.GetWindowLongW
            window_style.argtypes = (wintypes.HWND, ctypes.c_int)
            self.assertFalse(window_style(int(dialog.winId()), -16) & 0x00C00000)  # WS_CAPTION
        self.assertTrue(dialog.titlebar.close_button.isVisible())
        self.assertFalse(dialog.arrangements.isVisible())
        image = dialog.grab().toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(image.pixelColor(image.width() // 2, 4).alpha(), 255)
        self.assertTrue(dialog.search.isVisible())
        handle = dialog.windowHandle()
        with patch.object(handle, 'startSystemMove', return_value=True) as move:
            QTest.mouseClick(dialog.titlebar, Qt.LeftButton, pos=dialog.titlebar.rect().center())
            move.assert_called_once_with()
        with patch.object(handle, 'startSystemResize', return_value=True) as resize:
            QTest.mouseClick(dialog, Qt.LeftButton, pos=QPoint(dialog.width() - 1, dialog.height() - 1))
            resize.assert_called_once_with(Qt.RightEdge | Qt.BottomEdge)
        dialog.parallel.setChecked(True)
        dialog.titlebar.close_button.click()
        self.assertIsNone(pip.dialog)
        self.assertFalse(pip.active)
        self.assertFalse(pip.parallel_preference)

    def test_layout_cards_adapt_and_preview_snaps_near_a_target(self):
        from ddm.pip_composition import FOCUS_LAYOUT, FREE_LAYOUT, GRID_LAYOUT, MAIN_LAYOUT
        from selfcheck_picture_in_picture import pointer

        window = self.window([dict(room_id='1', uname='Main', live=True)])
        window.sidebar.add_rooms([dict(room_id=str(i), uname=f'Followed {i}', live=True) for i in (2, 3)])
        window.picture_in_picture.columns = FOCUS_LAYOUT
        window.picture_in_picture.manage()
        dialog = window.picture_in_picture.dialog
        cards = dialog.arrangements
        self.assertFalse(cards.isVisible())
        self.assertTrue(dialog.start.isEnabled())
        dialog.checks['2'].setChecked(True)
        self.assertEqual({mode for mode, button in cards.buttons.items() if button.isVisible()},
                         {0, 1, 16, FREE_LAYOUT})
        self.assertEqual(cards.mode, 0)
        cards.buttons[16].click()

        preview = dialog.preview
        source, target = preview.labels
        start = source.rect().center()
        bounds = target.geometry()
        near = QPoint(bounds.right() + 6, bounds.center().y())
        pointer(source, QEvent.MouseButtonPress, start, source.mapToGlobal(start), Qt.LeftButton, Qt.LeftButton)
        pointer(preview, QEvent.MouseMove, near, preview.mapToGlobal(near), Qt.NoButton, Qt.LeftButton)
        self.assertIs(preview._drop_target, target)
        self.assertEqual(preview._ghost.geometry(), bounds.adjusted(2, 2, -2, -2))
        pointer(preview, QEvent.MouseButtonRelease, near, preview.mapToGlobal(near), Qt.LeftButton, Qt.NoButton)
        self.assertEqual(dialog._selected(), ['2', 0])

        dialog.checks['3'].setChecked(True)
        self.assertEqual({mode for mode, button in cards.buttons.items() if button.isVisible()},
                         {0, 16, GRID_LAYOUT, MAIN_LAYOUT, FREE_LAYOUT})
        cards.buttons[MAIN_LAYOUT].click()
        self.assertEqual(cards.mode, MAIN_LAYOUT)
        primary = preview.labels[preview.primary].geometry()
        self.assertGreater(primary.height(), min(label.height() for label in preview.labels))
        dialog.reject()

    def test_first_picker_uses_wall_and_keeps_new_selections_in_the_top_group(self):
        from ddm.pip_composition import FOCUS_LAYOUT, FREE_LAYOUT
        rooms = [dict(room_id=str(i), uname=f'Wall {i}', live=True) for i in (1, 2)]
        window = self.window(rooms)
        window.sidebar.add_rooms([dict(room_id=str(i), uname=f'Followed {i}', live=True) for i in range(3, 7)])
        pip = window.picture_in_picture
        pip.selection = [1]
        pip.external_rooms = ['3']
        pip._choice_order = ['3', 1]
        pip.manage()
        dialog = pip.dialog
        heading, top = dialog.sections[0]
        self.assertEqual(heading.text(), '已入墙')
        self.assertEqual([button.choice for button in top], [0, 1])
        self.assertEqual(dialog._selected(), [0, 1])
        self.assertFalse(dialog.checks['3'].isChecked())

        dialog.arrangements.buttons[FREE_LAYOUT].click()
        for key in ('3', '4', '5', '6'):
            dialog.checks[key].setChecked(True)
        QTest.qWait(40)
        self.assertEqual([button.choice for button in top], [0, 1, '3', '4', '5', '6'])
        self.assertEqual(heading.text(), '已入墙与已选')
        cards = dialog.arrangements.buttons
        self.assertTrue(cards[FOCUS_LAYOUT].isVisible())
        self.assertGreater(cards[FREE_LAYOUT].x(), cards[FOCUS_LAYOUT].x())
        top[2].click()
        self.assertEqual([button.choice for button in top], [0, 1, '4', '5', '6'])
        self.assertFalse(dialog.checks['3'].isChecked())
        dialog.checks['3'].setChecked(True)
        dialog.parallel.setChecked(True)
        dialog.start.click()
        QTest.qWait(60)
        pip.restore()
        pip.manage()
        self.assertEqual([button.choice for button in pip.dialog.sections[0][1]],
                         [0, 1, '4', '5', '6', '3'])
        pip.dialog.reject()

    def test_parallel_picker_keeps_the_main_wall_and_local_audio_independent(self):
        window = self.window([dict(room_id='1', uname='Main', live=True, muted=False, volume=35)])
        window.sidebar.add_room(dict(room_id='2', uname='Followed', live=True))
        wall, pip = window.wall, window.picture_in_picture
        main = wall.tiles[0]
        parent, layout_id, old_tiles = wall.parentWidget(), wall.layout_id, list(wall.tiles)
        pip.manage()
        dialog = pip.dialog
        self.assertFalse(dialog.parallel.isChecked())
        dialog.parallel.setChecked(True)
        dialog.checks['2'].setChecked(True)
        with patch.object(window, '_stop_tile', wraps=window._stop_tile) as stop:
            dialog.start.click()
            QTest.qWait(60)
            self.assertTrue(pip.active)
            self.assertFalse(pip.moves_main_wall)
            self.assertTrue(window.isVisible() and not window.isMinimized())
            self.assertIs(wall.parentWidget(), parent)
            self.assertEqual(wall.layout_id, layout_id)
            self.assertEqual(wall.tiles, old_tiles)
            self.assertTrue(wall.isVisible() and main.isVisible())
            clones = pip.audio_tiles()
            self.assertEqual([tile.room['room_id'] for tile in clones], ['1', '2'])
            self.assertTrue(all(tile.muted for tile in clones))
            self.assertIsNot(clones[0], main)
            self.assertIsNot(clones[0].room, main.room)
            self.assertTrue(window.current_state()['ui']['picture_in_picture']['parallel'])
            pip.floating.audio_panel.rebuild()
            pip.floating.audio_panel._tile_volume(clones[0], 68)
            pip.floating.audio_panel._tile_mute(clones[0], False)
            self.assertEqual((main.volume, main.muted), (35, False))
            self.assertEqual((clones[0].volume, clones[0].muted), (68, False))
            pip.swap_positions(*clones)
            QTest.qWait(60)
            self.assertEqual(pip.audio_tiles(), clones[::-1])
            self.assertEqual(pip.audio_tiles()[1].volume, 68)
            window._on_status_updated({'2': dict(live=False, viewers='', title='', live_known=True)})
            self.assertFalse(clones[1].room['live'])
            pip.floating.close()
            self.assertFalse(pip.active)
            self.assertEqual(wall.tiles, old_tiles)
            self.assertIs(wall.parentWidget(), parent)
            self.assertTrue(wall.isVisible())
            self.assertNotIn(main, [call.args[0] for call in stop.call_args_list])
        pip.manage()
        self.assertTrue(pip.dialog.parallel.isChecked())
        pip.dialog.reject()

    def test_custom_layout_moves_a_portrait_view_without_swapping_and_reuses_vacancy(self):
        from ddm.pip_composition import FREE_LAYOUT
        from ddm.pip_geometry import pane_rectangles
        from selfcheck_picture_in_picture import pointer

        window = self.window([dict(room_id='1', uname='Landscape', live=True)])
        window.sidebar.add_rooms([dict(room_id=str(i), uname=f'Portrait {i}', live=True) for i in (2, 3)])
        pip = window.picture_in_picture
        with patch.object(pip, 'aspects_for', side_effect=lambda keys: [
                16 / 9 if key == 0 else 9 / 16 for key in keys]):
            pip.manage()
            dialog = pip.dialog
            dialog.checks['2'].setChecked(True)
            dialog.arrangements.buttons[FREE_LAYOUT].click()
            preview = dialog.preview
            before = preview.placement
            first, second = preview.labels
            self.assertLess(first.height(), second.height())
            start = second.rect().center()
            pressed = second.mapToGlobal(start)
            target = pressed + QPoint(7, 26)
            pointer(second, QEvent.MouseButtonPress, start, pressed, Qt.LeftButton, Qt.LeftButton)
            pointer(preview, QEvent.MouseMove, preview.mapFromGlobal(target), target, Qt.NoButton, Qt.LeftButton)
            pointer(preview, QEvent.MouseButtonRelease, preview.mapFromGlobal(target), target, Qt.LeftButton, Qt.NoButton)
            after = preview.placement
            self.assertEqual(dialog._selected(), [0, '2'])
            self.assertEqual(after[0], before[0])
            self.assertEqual(after[1][0], after[0][0] + after[0][2])
            self.assertNotEqual(after[1][1], before[1][1])
            second = preview.labels[1]
            start = second.rect().center()
            pressed = second.mapToGlobal(start)
            target = pressed + QPoint(25, 0)
            pointer(second, QEvent.MouseButtonPress, start, pressed, Qt.LeftButton, Qt.LeftButton)
            pointer(preview, QEvent.MouseMove, preview.mapFromGlobal(target), target, Qt.NoButton, Qt.LeftButton)
            QTest.keyClick(preview, Qt.Key_Escape)
            self.assertEqual(preview.placement, after)
            self.assertIsNone(preview._ghost)
            dialog.checks['2'].setChecked(False)
            dialog.checks['3'].setChecked(True)
            self.assertEqual(preview.placement, after)
            dialog.parallel.setChecked(True)
            dialog.start.click()
            QTest.qWait(60)
            self.assertTrue(pip.active)
            self.assertEqual(pip.state()['placement'], after)
            self.assertEqual([tile.geometry() for tile in pip.audio_tiles()], pane_rectangles(
                2, pip.display_wall.rect(), FREE_LAYOUT, placement=after))
            pip.manage()
            self.assertEqual(pip.dialog.preview.placement, after)
            pip.dialog.reject()
            pip.restore()

    def test_parallel_toggle_applies_only_on_confirmation_and_returns_to_shared_wall(self):
        window = self.window([dict(room_id='1', uname='Main', live=False)])
        wall, pip = window.wall, window.picture_in_picture
        pip.manage()
        pip.dialog.parallel.setChecked(True)
        pip.dialog.reject()
        self.assertFalse(pip.parallel_preference)
        self.assertFalse(pip.active)

        if self.app.platformName() != 'windows':
            self.skipTest('Changing the mode while the native window is active requires Windows Qt')
        self.assertTrue(pip.start([0]))
        QTest.qWait(60)
        self.assertTrue(pip.moves_main_wall)
        pip.manage()
        pip.dialog.parallel.setChecked(True)
        pip.dialog.start.click()
        QTest.qWait(60)
        self.assertFalse(pip.moves_main_wall)
        self.assertTrue(window.isVisible() and not window.isMinimized())
        self.assertIsNot(pip.display_wall, wall)

        pip.manage()
        pip.dialog.parallel.setChecked(False)
        pip.dialog.start.click()
        QTest.qWait(60)
        self.assertTrue(pip.moves_main_wall)
        self.assertIs(pip.display_wall, wall)
        self.assertFalse(pip.parallel_preference)
        pip.restore(activate=True)
        self.assertTrue(wall.isVisible())

    def test_vanity_room_search_survives_status_refresh_and_state_restore(self):
        from ddm import config
        from ddm.widgets import Sidebar
        window = self.window([])
        sidebar = window.sidebar
        room = dict(room_id='douyu:6979222', uname='测试主播', platform='douyu',
                    playback_mode='stream', uid=6657, title='直播回顾', live=True)
        sidebar.add_room(room)
        sidebar.search.setText('6657')
        self.assertEqual(sidebar.visible_items(), [])
        with patch('ddm.bili.requests.get', side_effect=AssertionError('Search must not access the network')):
            status = dict(live=True, uname='测试主播', title='直播回顾', viewers='', face='', display_room_id='6657')
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

    def test_old_six_slot_wall_can_open_one_video_and_add_a_followed_room(self):
        from ddm.picture_in_picture import FOCUS_LAYOUT
        window = self.window([dict(room_id='1', uname='Wall', live=True)])
        wall, pip = window.wall, window.picture_in_picture
        wall.set_layout('corner')
        window.configure_wall_panes({1: wall.tiles[0], 2: None})
        window.sidebar.add_room(dict(room_id='7', uname='Followed', live=True))
        pip.selection = list(range(6))
        pip.columns = FOCUS_LAYOUT
        pip.manage()
        dialog = pip.dialog
        self.assertEqual(dialog._selected(), [0])
        self.assertEqual(len(dialog.preview.labels), 1)
        self.assertTrue(dialog.start.isEnabled())
        dialog.start.click()
        QTest.qWait(60)
        self.assertTrue(pip.moves_main_wall)
        self.assertEqual(len(pip.audio_tiles()), 1)
        self.assertEqual(pip.columns, 0)
        pip.manage()
        dialog = pip.dialog
        dialog.checks['7'].setChecked(True)
        self.assertTrue(dialog.start.isEnabled())
        self.assertEqual(len(dialog.preview.labels), 2)
        dialog.start.click()
        QTest.qWait(60)
        self.assertEqual([tile.room['room_id'] for tile in pip.audio_tiles()], ['1', '7'])
        pip.restore(activate=True)
        self.assertEqual(set(wall.pane_danmaku.bindings()), {1, 2})

    def test_pip_hides_separate_chat_and_restores_the_same_wall_documents(self):
        from ddm.picture_in_picture import FOCUS_LAYOUT
        from selfcheck_video_danmaku import Client, Snapshot
        with patch('ddm.app.DanmakuClient', Client), patch('ddm.app.SuperChatSnapshot', Snapshot), \
                patch('ddm.bili._cookies', return_value={}):
            window = self.window([dict(room_id=str(i + 1), uname=f'Room {i + 1}', live=False) for i in range(6)])
            wall, pip = window.wall, window.picture_in_picture
            wall.set_layout('corner')
            window.configure_wall_panes({1: wall.tiles[0], 2: wall.tiles[4]})
            window.danmaku_lifecycle.sync_danmaku()
            panes = wall.pane_danmaku
            panels = dict(panes.panels)
            bindings = panes.state()
            documents = {cell: panel.body.document() for cell, panel in panels.items()}
            clients = dict(window._danmaku_clients)
            window._on_danmaku_message(clients['1'], dict(kind='danmaku', uname='Fixture', text='before PiP'))
            self.assertTrue(pip.start([0, 3, 4, 5], FOCUS_LAYOUT))
            QTest.qWait(60)
            self.assertFalse(wall.has_danmaku)
            self.assertEqual(len(wall.picture_in_picture_aspects), 4)
            self.assertTrue(all(panel.isHidden() for panel in panels.values()))
            for cell, panel in panels.items():
                self.assertIs(panel.body.document(), documents[cell])
            pip.swap_positions(wall.tiles[0], wall.tiles[3])
            self.assertIs(panes.target(panels[1]), wall.tiles[0])
            self.assertEqual(panes.state(), bindings)
            wall.resize(900, 540)
            wall.relayout(force=True)
            self.assertTrue(all(panel.isHidden() for panel in panels.values()))
            pip.restore(activate=False)
            self.assertEqual(panes.state(), bindings)
            for cell, panel in panels.items():
                self.assertIs(panel.body.document(), documents[cell])
            self.assertIn('before PiP', panels[1].body.toPlainText())
            self.assertTrue(wall.tiles[1].isHidden() and wall.tiles[2].isHidden())

    def test_focus_chat_preserves_shared_source_merged_document(self):
        from ddm.picture_in_picture import FOCUS_LAYOUT
        window = self.window([dict(room_id=str(i + 1), live=False) for i in range(6)])
        wall, pip = window.wall, window.picture_in_picture
        wall.set_layout('corner')
        window.configure_wall_panes({1: wall.tiles[0], 2: wall.tiles[0]})
        panes = wall.pane_danmaku
        self.assertEqual(len(panes.rendered()), 1)
        panel = panes.rendered()[0]
        panel.add_message('Fixture', 'shared source history')
        document = panel.body.document()
        self.assertTrue(pip.start([0, 3, 4, 5], FOCUS_LAYOUT))
        QTest.qWait(60)
        self.assertEqual(panes.rendered(), [panel])
        self.assertTrue(panel.isHidden())
        self.assertIs(panel.body.document(), document)
        self.assertEqual(set(next(iter(panes.groups.values()))), {1, 2})
        pip.restore(activate=False)
        self.assertIs(panel.body.document(), document)
        self.assertIn('shared source history', panel.body.toPlainText())

    def test_old_six_slot_mode_accepts_other_video_counts(self):
        from ddm.picture_in_picture import FOCUS_LAYOUT
        window = self.window([dict(room_id=str(i + 1), live=False) for i in range(6)])
        wall, pip = window.wall, window.picture_in_picture
        wall.set_layout('corner')
        window.configure_wall_panes({1: None, 2: None})
        window.sidebar.add_rooms([dict(room_id='7', live=True), dict(room_id='8', live=True)])
        window.start_tile.reset_mock()
        self.assertTrue(pip.start([0, 3, 4, '7', '8'], FOCUS_LAYOUT))
        QTest.qWait(60)
        self.assertEqual(set(pip._extra_tiles), {'7', '8'})
        self.assertEqual(len(wall.picture_in_picture_tiles), 5)
        self.assertFalse(wall.has_danmaku)
        self.assertTrue(all(panel.isHidden() for panel in wall.pane_danmaku.all_panels()))
        pip.restore(activate=False)

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
        self.app.processEvents()
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
        self.app.processEvents()
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
        from ddm.pip_composition import FOCUS_LAYOUT, FREE_LAYOUT
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
        self.assertEqual({mode for mode, button in dialog.arrangements.buttons.items() if button.isVisible()},
                         {0, 1, 16, FREE_LAYOUT})
        for rid in ('3', '4', '5', '6'):
            dialog.checks[rid].setChecked(True)
        dialog.arrangements.buttons[FOCUS_LAYOUT].click()
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
            self.app.processEvents()
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
        from selfcheck_picture_in_picture import drag_preview, pointer
        from ddm.picture_in_picture import FOCUS_LAYOUT
        from ddm.pip_composition import GRID_LAYOUT, MAIN_LAYOUT
        window = self.window([{'room_id': str(i), 'uname': f'Room {i}', 'live': False} for i in range(6)])
        window.settings['close_behavior'] = 'exit'
        window.wall.set_layout('3x2')
        pip = window.picture_in_picture
        pip.manage()
        dialog = pip.dialog
        before = list(pip.selection)
        dialog.arrangements.buttons[FOCUS_LAYOUT].click()
        self.assertFalse(hasattr(dialog, 'primary_row'))
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
        for mode in (GRID_LAYOUT, MAIN_LAYOUT):
            dialog.arrangements.buttons[mode].click()
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
        self.app.processEvents()
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
                      'ALICE', 'dcz', 'dcccz', '9102', 'Morning', '深夜音乐',
                      'shenyeyinyue', '9101 深夜', 'missing'):
            with self.subTest(query=query):
                sidebar.search.setText(query)
                expected = {str(item.room['room_id']) for item in sidebar.visible_items()}
                dialog.search.setText(query)
                actual = {str(dialog.rooms[key]['room_id']) for key, button in dialog.checks.items()
                          if not button.isHidden()}
                self.assertEqual(actual, expected)
                self.assertEqual(dialog._selected(), [0])
        dialog.search.setText('Morning')
        self.assertFalse(dialog.checks['9103'].isHidden())
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
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(PipPickerTests, __file__))
    else:
        faulthandler.dump_traceback_later(60, repeat=True)
        try:
            unittest.main(verbosity=2)
        finally:
            faulthandler.cancel_dump_traceback_later()
