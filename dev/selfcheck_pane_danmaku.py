"""Wall-only chat pane actions, shared subscriptions, identity and persistence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

NATIVE = '--native' in sys.argv
if NATIVE:
    sys.argv.remove('--native')
    os.environ['QT_QPA_PLATFORM'] = 'windows'
    os.environ['DDM_QTQUICK_DANMAKU'] = '1'

import selfcheck_main_notices as fixtures
from PySide6.QtCore import QAbstractAnimation, QEvent, QMimeData, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QDragEnterEvent, QDropEvent, QImage, QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTabBar, QWidget
from ddm import config, layouts, room_presets, theme
from ddm.app import MainWindow
from ddm.bili_interaction.composer import DanmakuComposer
from ddm.danmaku_float_snap import snapped_position
from ddm.danmaku_float_window import DanmakuFloatWindow
from ddm.widget_support import TILE_MIME
from ddm.widgets import DanmakuPanel, WallGrid
from selfcheck_video_danmaku import Client, Snapshot


REAL_SYNC = MainWindow.sync_danmaku
FLOAT_SHOW = DanmakuFloatWindow.show
FULLSCREEN_RECT = QRect(-10000, -10000, 960, 620)


def show_float_offscreen(floating):
    floating.setAttribute(Qt.WA_ShowWithoutActivating)
    floating.move(FULLSCREEN_RECT.topLeft() + QPoint(20, 50))
    FLOAT_SHOW(floating)


class PaneDanmakuTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

    def setUp(self):
        fixtures.MainNoticesTests.setUp(self)
        self.stack.enter_context(patch.object(MainWindow, "sync_danmaku", REAL_SYNC))
        self.stack.enter_context(patch("ddm.app.bili._cookies", return_value={}))
        self.stack.enter_context(patch('ddm.app.DanmakuClient', Client))
        self.stack.enter_context(patch('ddm.app.SuperChatSnapshot', Snapshot))

    def wall_window(self):
        window = self.window([dict(room_id=str(1001 + i), uname=f'主播 {i + 1}',
                                 live=True, volume=20 + 10 * i, muted=bool(i % 2)) for i in range(4)], offscreen=True)
        window.settings["close_behavior"] = "exit"
        return window

    def drop_video(self, panel, tile, cell):
        wall = panel.parentWidget()
        point = wall.mapToGlobal(wall.pane_danmaku.rectangles[cell].center())
        position = panel.mapFromGlobal(point)
        mime = QMimeData()
        room_id = tile.room['room_id']
        mime.setData(TILE_MIME, room_id.encode())
        mime.setText(room_id)
        enter = QDragEnterEvent(position, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        drop = QDropEvent(QPointF(position), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.app.sendEvent(panel, enter)
        self.assertTrue(enter.isAccepted())
        self.app.sendEvent(panel, drop)
        self.assertTrue(drop.isAccepted())

    def test_live_source_capability_preserves_offline_rooms(self):
        from ddm import plugins as api
        from ddm.danmaku_sources import is_live_danmaku_source
        self.assertEqual(api.ROOM_SUPPORTS_LIVE_DANMAKU, 'supports_live_danmaku')
        self.assertTrue(is_live_danmaku_source(dict(room_id='1001', live=False)))
        self.assertTrue(is_live_danmaku_source(dict(room_id='1001', supports_live_danmaku=True)))
        self.assertFalse(is_live_danmaku_source(dict(room_id='1001', supports_live_danmaku=False)))
        self.assertFalse(is_live_danmaku_source(dict(room_id='')))
        self.assertFalse(is_live_danmaku_source(None))

    def test_live_source_opt_out_filters_picker_and_subscription(self):
        window = self.wall_window()
        wall = window.wall
        source = wall.tiles[0]
        source.set_room({**source.room, 'live':False, 'supports_live_danmaku':False})
        window.configure_wall_panes({3: source})
        panes = wall.pane_danmaku
        panel = panes.panels[3]
        panel.source_picker.refresh()
        self.assertNotIn(source, panel.source_picker.buttons)
        self.assertIsNone(panes.target(panel))
        window.sync_danmaku()
        self.assertNotIn('1001', window._danmaku_clients)

    def test_automatic_source_and_direct_requests_skip_opted_out_tiles(self):
        window = self.wall_window()
        wall = window.wall
        source = wall.tiles[0]
        source.set_room({**source.room, 'supports_live_danmaku':False})
        window.configure_wall_panes({3: None})
        panes = wall.pane_danmaku
        panel = panes.panels[3]
        self.assertIs(panes.automatic_target(), wall.tiles[1])
        changes = []
        wall.paneApplyRequested.connect(changes.append)
        panes.request(3, source)
        panes.room_dropped(panel, '1001')
        panes.choose_source(panel, source)
        self.assertFalse(changes)

    def test_legacy_source_opt_out_does_not_select_a_different_main(self):
        window = self.wall_window()
        wall = window.wall
        wall.set_layout('dm_main2')
        main = wall.tiles[wall.main_index()]
        main.set_room({**main.room, 'supports_live_danmaku':False})
        self.assertIsNone(wall.danmaku_target_tile())
        self.assertIsNone(wall.pane_danmaku.automatic_target())
        with patch.object(wall, 'move_danmaku_to_tile') as move:
            wall.pane_danmaku.room_dropped(wall.danmaku, main.room['room_id'])
        move.assert_not_called()

    def test_replacing_selected_live_with_opt_out_then_restoring_updates_sources(self):
        window = self.wall_window()
        source = window.wall.tiles[0]
        original = dict(source.room)
        window.configure_wall_panes({3:source})
        panes = window.wall.pane_danmaku
        panel = panes.panels[3]
        source.set_room({**original, 'supports_live_danmaku':False})
        source.set_video_active(True)
        source.danmaku_button.setChecked(True)
        window.sync_danmaku()
        panes.refresh_sources()
        self.assertIsNone(panes.target(panel))
        self.assertNotIn(source, panel.source_picker.buttons)
        self.assertNotIn('1001', window._danmaku_clients)
        source.set_room(original)
        window.sync_danmaku()
        panes.refresh_sources()
        self.assertIs(panes.target(panel),source)
        self.assertIn(source,panel.source_picker.buttons)
        self.assertIn('1001', window._danmaku_clients)

    def test_float_uses_the_same_panel_and_returns_the_composer_to_video(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        source = wall.tiles[0]
        window.configure_wall_panes({2: source, 3: source})
        panel, = panes.rendered()
        original_size, document = panel.size(), panel.body.document()
        composer = source._plugin_controls
        builtin, = composer.widget.findChildren(DanmakuComposer)
        editor = builtin.edit
        editor.setText('未发送草稿')
        client = window._danmaku_clients['1001']
        client.message.emit(dict(kind='danmaku', text='浮出前'))
        self.assertIs(composer.widget.parentWidget(), panel.composer_bar)

        panel.float_button.click()
        floated = panes.floating[panel]
        self.assertIs(panel.parentWidget(), floated.window)
        self.assertTrue(floated.window.isVisible() and floated.slot.isVisible())
        self.assertEqual(floated.window.size(), original_size)
        self.assertIs(panel.body.document(), document)
        self.assertIs(composer.widget.parentWidget(), source.bottom)
        self.assertEqual(editor.text(), '未发送草稿')
        self.assertIs(window._danmaku_clients['1001'], client)
        client.message.emit(dict(kind='danmaku', text='浮出后'))
        self.assertEqual([event['text'] for event in panel._blocks[-2:]], ['浮出前', '浮出后'])
        handle = floated.window.windowHandle()
        with patch.object(handle, 'startSystemMove', return_value=True) as move, \
                patch.object(handle, 'startSystemResize', return_value=True) as resize:
            QTest.mouseClick(panel.title, Qt.LeftButton)
            QTest.mouseClick(floated.window, Qt.LeftButton, pos=QPoint(floated.window.width() - 2, 40))
            move.assert_called_once_with()
            resize.assert_called_once_with(Qt.RightEdge)
        floated.window.resize(original_size + QSize(10, 30))
        self.assertEqual(floated.window.size(), original_size + QSize(10, 30))
        floated.slot.findChild(QPushButton).click()
        self.assertFalse(panes.floating)
        self.assertIs(panel.parentWidget(), wall)
        self.assertIs(composer.widget.parentWidget(), panel.composer_bar)
        self.assertEqual(editor.text(), '未发送草稿')
        panel.float_button.click()
        self.assertEqual(panes.floating[panel].window.size(), original_size)
        wall._fullscreen_layout_pending = True
        panes.floating[panel].window.close()
        self.assertFalse(panes.floating[panel].window.isVisible())
        wall._fullscreen_layout_pending = False
        panes.finish_pending_returns()
        self.assertFalse(panes.floating)

        window.configure_wall_panes({1: source, 2: source})
        diagonal = panes.panels[2]
        diagonal.float_button.click()
        self.assertIs(composer.widget.parentWidget(), source.bottom)
        self.assertTrue(panes.panels[1].isVisible())
        panes.floating[diagonal].window.close()

    def test_drag_floating_tabs_preserves_history_and_original_slots(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second, third = wall.tiles[:3]
        window.configure_wall_panes({3: first})
        docked = panes.panels[3]
        with patch.object(DanmakuFloatWindow, 'show', show_float_offscreen):
            docked.float_button.click()
            panes.open_for_tile(second)
            panes.open_for_tile(third)
        grouped = panes.floating[docked].window
        incoming, last = [panel for panel in panes.floating if panel is not docked]
        source, extra = (panes.floating[panel].window for panel in (incoming, last))
        grouped.resize(430, 240)
        source.move(grouped.x() - 500, grouped.y())
        extra.move(grouped.x() - 500, grouped.y() - 350)
        self.app.processEvents()

        def drag(bar, index, point, target=None, *, cancel=False):
            start = bar.mapToGlobal(bar.tabRect(index).center())
            QTest.mousePress(bar, Qt.LeftButton, pos=bar.mapFromGlobal(start))
            with patch.object(QApplication, 'topLevelAt', return_value=target):
                for kind, button, buttons in ((QEvent.MouseMove, Qt.NoButton, Qt.LeftButton),
                                              (QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton)):
                    event = QMouseEvent(kind, QPointF(bar.mapFromGlobal(point)), QPointF(point),
                                        button, buttons, Qt.NoModifier)
                    self.app.sendEvent(bar, event)
                    if kind == QEvent.MouseMove:
                        self.assertIsNotNone(bar._ghost)
                        if target is not None:
                            self.assertIsNotNone(target.tabs._insertion)
                        if cancel:
                            QTest.keyClick(bar, Qt.Key_Escape)
            self.assertIsNone(bar._ghost)
            if target is not None:
                self.assertIsNone(target.tabs._insertion)

        client = window._danmaku_clients['1001']
        for number in range(32):
            client.message.emit(dict(kind='danmaku', text=f'历史消息 {number}'))
        self.app.processEvents()
        scroll = docked.body.verticalScrollBar()
        self.assertGreater(scroll.maximum(), 90)
        scroll.setValue(64)
        docked.scroll_control.on_user_scroll()
        document = docked.body.document()
        with patch.object(window, '_sync_tile_playback') as playback:
            end = grouped.tabs.mapToGlobal(QPoint(grouped.tabs.width()-4, 14))
            drag(source.tabs, 0, end, grouped, cancel=True)
            self.assertEqual(grouped.tabs.panels(), [docked])
            drag(source.tabs, 0, end, grouped)
            drag(extra.tabs, 0, end, grouped)
            playback.assert_not_called()
        self.assertEqual(panes.floating_windows(), (grouped,))
        self.assertEqual(grouped.tabs.panels(), [docked, incoming, last])
        self.assertIs(grouped.stack.currentWidget(), last)
        self.assertFalse(docked.isVisible())
        self.assertTrue(last.isVisible())
        client.message.emit(dict(kind='danmaku', text='后台标签仍接收'))
        QTest.mouseClick(grouped.tabs, Qt.LeftButton, pos=grouped.tabs.tabRect(0).center())
        self.app.processEvents()
        self.assertIs(docked.body.document(), document)
        self.assertEqual(docked._blocks[-1]['text'], '后台标签仍接收')
        self.assertEqual(scroll.value(), 64)
        self.assertIs(window._danmaku_clients['1001'], client)

        left = grouped.tabs.mapToGlobal(QPoint(2, 14))
        drag(grouped.tabs, 2, left, grouped)
        self.assertEqual(grouped.tabs.panels(), [last, docked, incoming])
        with patch.object(DanmakuFloatWindow, 'show', show_float_offscreen):
            drag(grouped.tabs, 0, grouped.frameGeometry().bottomLeft() + QPoint(20, 60))
        detached = panes.floating[last].window
        self.assertIsNot(detached, grouped)
        self.assertEqual(detached.tabs.panels(), [last])
        self.assertEqual(grouped.tabs.panels(), [docked, incoming])

        incoming.source_picker.choose(first)
        self.assertEqual(grouped.tabs.tabText(1), '主播 1')
        wall._fullscreen_layout_pending = True
        grouped.select_panel(docked)
        QTest.mouseClick(grouped.tabs.tabButton(0, QTabBar.RightSide), Qt.LeftButton)
        self.assertEqual(grouped.tabs.panels(), [incoming])
        self.assertTrue(grouped.isVisible())
        self.assertIn(docked, panes.floating)
        wall._fullscreen_layout_pending = False
        panes.finish_pending_returns()
        self.assertIs(panes.panels[3], docked)
        self.assertIs(docked.parentWidget(), wall)
        self.assertIs(panes.target(docked), first)
        panes.move_floating_tab(last, grouped, 1)
        grouped.close()
        self.assertFalse(panes.floating)
        self.app.processEvents()

    def test_floating_window_snaps_on_release_and_respects_the_switch(self):
        area = QRect(-1200, -600, 1200, 570)
        other = QRect(-800, -450, 260, 230)
        frame = QRect(-531, -420, 240, 200)
        self.assertEqual(snapped_position(frame, area, [other]), (QPoint(-540, -420), Qt.LeftEdge))
        self.assertEqual(snapped_position(frame.translated(0, 215), area, [other]),
                         (QPoint(-531, -205), Qt.Edge(0)))
        corner = QRect(-1194, -595, 240, 200)
        self.assertEqual(snapped_position(corner, area, []), (area.topLeft(), Qt.LeftEdge | Qt.TopEdge))

        window = self.wall_window()
        panes = window.wall.pane_danmaku
        with patch.object(DanmakuFloatWindow, 'show', show_float_offscreen):
            panes.open_for_tile(window.wall.tiles[0])
        floating, = panes.floating_windows()
        self.assertTrue(floating.snap.isChecked())
        with patch.object(floating.windowHandle(), 'startSystemMove', return_value=True), \
                patch.object(floating, '_snap_candidate', side_effect=lambda: snapped_position(
                    floating.frameGeometry(), area, [])):
            floating.move(area.topLeft() + QPoint(25, 30))
            self.assertTrue(floating.start_move())
            floating.move(corner.topLeft())
            self.assertEqual(floating._snap_edges, Qt.LeftEdge | Qt.TopEdge)
            if NATIVE:
                import ctypes
                from ctypes import wintypes
                send_message = ctypes.windll.user32.SendMessageW
                send_message.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
                send_message(int(floating.winId()), 0x0232, 0, 0)  # WM_EXITSIZEMOVE
                self.app.processEvents()
            else:
                floating._finish_move()
            self.assertEqual(floating.pos(), area.topLeft())
            self.assertFalse(floating._snap_edges)
            floating.snap.trigger()
            self.assertFalse(floating.snap.isChecked())
            self.assertTrue(floating.start_move())
            floating.move(corner.topLeft())
            floating._finish_move()
            self.assertEqual(floating.pos(), corner.topLeft())

    def test_reuse_float_cell_only_reclaims_an_empty_video_slot(self):
        window = self.wall_window()
        window.settings['danmaku_float_reuse_cell'] = True
        wall, panes = window.wall, window.wall.pane_danmaku
        source, other, _third, slot = wall.tiles[:4]
        slot.set_room(None)
        window.configure_wall_panes({3: source})
        panel = panes.panels[3]
        panel.float_button.click()
        self.assertTrue(slot.isVisible())
        self.assertFalse(panes.bindings())
        self.assertIs(panes.target(panel), source)
        self.assertIs(wall._preset_widgets()[3], slot)
        panel.source_picker.choose(other)
        self.assertIs(panes.target(panel), other)
        panes.floating[panel].window.close()
        self.assertIs(panes.panels[3], panel)
        self.assertIs(panes.target(panel), other)

        panel.float_button.click()
        room = dict(room_id='7001', uname='新直播', live=True)
        with patch.object(window, '_room_dict', return_value=room), patch.object(window, 'start_tile'):
            slot.roomDropped.emit('7001')
        with patch.object(window, '_sync_tile_playback') as playback:
            panes.floating[panel].window.close()
            playback.assert_not_called()
        self.assertFalse(panes.bindings())
        self.assertTrue(slot.isVisible())
        self.assertEqual(slot.room['room_id'], '7001')
        self.assertFalse(panel.isVisible())

    def test_fullscreen_float_can_change_room_without_syncing_wall_playback(self):
        window = self.wall_window()
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        wall, panes = window.wall, window.wall.pane_danmaku
        source, other = wall.tiles[:2]
        window.configure_wall_panes({3: source})
        panel = panes.panels[3]
        with patch.object(DanmakuFloatWindow, 'show', show_float_offscreen):
            panel.float_button.click()
        floated = panes.floating[panel]
        enter = window._fullscreen_presentation.enter
        with patch.object(window._fullscreen_presentation, 'enter',
                          side_effect=lambda tile: enter(tile, FULLSCREEN_RECT)):
            window._on_fullscreen(source)
        self.app.processEvents()
        try:
            self.assertTrue(floated.slot.isHidden())
            self.assertTrue(other.isHidden())
            picker = panel.source_picker
            with patch('ddm.motion.enabled', return_value=False), \
                    patch.object(window, '_sync_tile_playback') as playback:
                QTest.mouseClick(picker.anchor, Qt.LeftButton)
                self.assertTrue(picker.expanded)
                QTest.mouseClick(picker.buttons[other], Qt.LeftButton)
                playback.assert_not_called()
            self.assertFalse(picker.expanded)
            self.assertIs(panes.target(panel), other)
            self.assertEqual(panel._linked_room_id, '1002')
            window._danmaku_clients['1002'].message.emit(dict(kind='danmaku', text='换源成功'))
            self.assertEqual(panel._blocks[-1]['text'], '换源成功')
            self.assertTrue(floated.slot.isHidden())
            self.assertTrue(other.isHidden())
            self.assertIs(wall.fullscreen_tile, source)
        finally:
            window._exit_fullscreen()
        self.assertIs(panes.target(panel), other)
        floated.window.close()
        self.app.processEvents()
        self.assertIs(panes.target(panes.panels[3]), other)

    def test_close_can_keep_the_empty_video_cells_created_by_a_merged_float(self):
        window = self.wall_window()
        window.settings.update(danmaku_float_reuse_cell=True, danmaku_float_keep_video_slots=True)
        wall, panes = window.wall, window.wall.pane_danmaku
        source, _other, *slots = wall.tiles[:4]
        for tile in slots:
            tile.set_room(None)
        window.configure_wall_panes({2: source, 3: source})
        panel, = panes.rendered()
        panel.float_button.click()
        self.assertTrue(all(tile.isVisible() for tile in slots))
        panel.float_button.click()
        self.assertFalse(panes.floating)
        self.assertFalse(panes.bindings())
        self.assertFalse(panel.isVisible())
        self.assertEqual([wall._preset_widgets()[index] for index in (2, 3)], slots)
        self.assertTrue(all(tile.isVisible() and not tile.room.get('room_id') for tile in slots))

    def test_video_menu_reuses_the_linked_panel_and_raises_an_open_float(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        source = wall.tiles[0]
        window.configure_wall_panes({3: source})
        panel = panes.panels[3]
        menu = source.build_menu()
        self.addCleanup(menu.deleteLater)
        action = next(action for action in menu.actions() if action.data() == 'danmaku_float')
        action.trigger()
        floated = panes.floating[panel]
        action.trigger()
        self.assertEqual(list(panes.floating), [panel])
        self.assertIs(panes.floating[panel], floated)
        self.assertTrue(floated.window.isVisible())
        floated.window.close()
        self.assertIs(panes.panels[3], panel)
        self.assertTrue(panel.isVisible())

    def test_video_menu_opens_and_closes_without_creating_a_wall_slot(self):
        window = self.wall_window()
        window.settings['danmaku_float_reuse_cell'] = True
        wall, panes = window.wall, window.wall.pane_danmaku
        other, source = wall.tiles[:2]
        window.configure_wall_panes({3: other})
        docked = panes.panels[3]
        before = panes.state()
        menu = source.build_menu()
        self.addCleanup(menu.deleteLater)
        action = next(action for action in menu.actions() if action.text() == '打开弹幕浮窗')
        with patch.object(window, '_sync_tile_playback') as playback:
            action.trigger()
            playback.assert_not_called()
        panel, = panes.floating
        self.assertIs(panes.target(panel), source)
        self.assertTrue(docked.isVisible() and source.isVisible())
        self.assertIs(panes.panels[3], docked)
        self.assertIsNone(panes.floating[panel].slot)
        client = window._danmaku_clients[source.room['room_id']]
        client.message.emit(dict(kind='danmaku', text='来自右键选中的直播'))
        self.assertIn('来自右键选中的直播', panel.body.toPlainText())
        self.assertNotIn('来自右键选中的直播', docked.body.toPlainText())
        with patch.object(window, '_sync_tile_playback') as playback:
            panel.float_button.click()
            playback.assert_not_called()
        self.assertFalse(panes.floating)
        self.assertNotIn(panel, panes.all_panels())
        self.assertFalse(panel.isVisible())
        self.assertEqual(panes.state(), before)
        self.assertTrue(source.isVisible())

    def test_wall_quick_settings_apply_to_visible_rooms_and_use_existing_float_lifecycle(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second, locked, hidden = wall.tiles[:4]
        second.set_room(dict(room_id='douyin:3001', uname='竖屏', volume=30, muted=True, live=True))
        window.configure_wall_panes({3: first})
        first.set_quality_options([{'qn': 20000, 'desc': '4K'}, {'qn': 15000, 'desc': '2K'},
                                   {'qn': 400, 'desc': '蓝光 1080P'}, {'qn': 250, 'desc': '超清 720P'}])
        second.set_quality_options([{'qn': 23, 'desc': '720x1280 · 60fps'}, {'qn': 88, 'desc': '540x960'}])
        locked.quality_locked = True
        first.danmaku_button.setChecked(True)
        locked.room['supports_live_danmaku'] = False
        original_locked, original_hidden = locked.quality, (hidden.quality, hidden.volume)
        controls = window.wall_quick_settings
        self.assertIsNone(controls.menu)
        window.sidebar.wall_settings_button.click()
        menu = controls.menu
        self.assertTrue(menu.isVisible())
        self.assertNotIn('无边界布局', {label.text() for label in menu.findChildren(QLabel)})
        self.assertEqual(menu.volume_value.text(), '混合')
        self.assertEqual(menu.quality.currentText(), '选择画质')

        menu.volume.setValue(63)
        self.assertEqual([tile.volume for tile in (first, second, locked)], [63] * 3)
        self.assertFalse(second.muted)
        second.set_muted(True)
        menu.volume.sliderReleased.emit()
        self.assertFalse(second.muted)
        second.set_muted(True)
        menu.volume.setValue(0)
        self.assertTrue(second.muted)
        self.assertEqual([tile.volume for tile in (first, second, locked)], [0] * 3)
        self.assertEqual(hidden.volume, original_hidden[1])

        self.assertGreaterEqual(menu.quality.findData(2160), 0)
        index = menu.quality.findData(1440)
        self.assertGreaterEqual(index, 0)
        with patch.object(window, 'start_tile') as start:
            menu.quality.setCurrentIndex(index)
            menu.quality.activated.emit(index)
        self.assertEqual([call.args[0] for call in start.call_args_list], [first, second])
        self.assertEqual([call.kwargs['wall_quality'].tiers for call in start.call_args_list],
                         [(15000, 400, 250), (23, 88)])
        self.assertEqual((locked.quality, hidden.quality), (original_locked, original_hidden[0]))
        self.assertIn('保留当前画质', menu.status.text())

        self.assertIn('部分开启', menu.danmaku_label.text())
        with patch.object(window, '_on_video_danmaku_changed', wraps=window._on_video_danmaku_changed) as changed:
            menu.danmaku.click()
            changed.assert_called_once_with(True)
        self.assertTrue(first.danmaku_button.isChecked() and second.danmaku_button.isChecked())
        self.assertFalse(locked.danmaku_button.isChecked() or hidden.danmaku_button.isChecked())
        menu.danmaku.click()
        self.assertFalse(first.danmaku_button.isChecked() or second.danmaku_button.isChecked())

        panel = panes.panels[3]
        menu.floats.click()
        self.assertFalse(menu.isVisible())
        self.assertIn(panel, panes.floating)
        self.assertEqual(len(panes.floating), 2)
        self.assertIs(panes.target(panel), first)
        standalone, = (other for other in panes.floating if other is not panel)
        self.assertIs(panes.target(standalone), second)
        self.assertIsNone(panes.floating[standalone].cell)
        window.sidebar.wall_settings_button.click()
        self.assertTrue(menu.floats.isChecked())
        menu.floats.click()
        self.assertFalse(panes.floating)
        self.assertIs(panes.panels[3], panel)
        window.sidebar.wall_settings_button.click()
        self.assertTrue(menu.isVisible())
        QTest.keyClick(menu, Qt.Key_Escape)
        self.assertFalse(menu.isVisible())

    def test_wall_seamless_switch_keeps_slots_and_round_trips(self):
        window = self.window([], offscreen=True)
        wall = window.wall
        first, second, lower, _last = wall.visible_tiles()
        margins = wall.grid.contentsMargins()
        original = (first.geometry(), second.geometry())
        cover = QPixmap(64, 64)
        cover.fill(QColor('#20a0d0'))
        first.set_room(dict(room_id='1001', uname='测试', live=False), cover)
        self.assertFalse(first.video.mask().contains(QPoint(0, 0)))
        self.assertEqual(first.cover.pixmap().toImage().pixelColor(0, 0).alpha(), 0)

        dialog = window._create_settings_dialog()
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.auto_save.stop)
        dialog.auto_save.start()
        switch = dialog.general_page._checks['wall_seamless']
        self.assertFalse(switch.isChecked())
        self.assertTrue(switch.isEnabled())
        with patch.object(config, 'save') as save:
            switch.click()
            self.assertTrue(dialog.auto_save.flush())
            self.assertTrue(save.call_args.args[0]['settings']['wall_seamless'])
        self.app.processEvents()
        self.assertEqual(wall.grid.contentsMargins(), margins)
        self.assertEqual(first.geometry().right() + 1, second.x())
        self.assertEqual(first.geometry().bottom() + 1, lower.y())
        self.assertEqual(first.video.geometry().topLeft(), QPoint())
        self.assertEqual(first.video.width(), first.width())
        self.assertTrue(first.video.mask().contains(QPoint(0, 0)))
        self.assertEqual(first.cover.pixmap().toImage().pixelColor(0, 0).alpha(), 255)
        self.assertEqual(first.bottom.geometry().bottom(), first.rect().bottom())
        window.settings['windowed_transparent_controls'] = True
        first._layout_areas()
        self.assertEqual(first.bottom.mask().boundingRect(), first.bottom.rect())

        saved = window.current_state()['settings']
        self.assertTrue(saved['wall_seamless'])
        reopened = MainWindow([], [], layout_id='2x2', state={'plugins_enabled': [], 'settings': saved})
        self.addCleanup(self.close_window, reopened)
        self.assertTrue(reopened.wall.seamless)
        self.assertEqual(reopened.wall.grid.spacing(), 0)

        wall.set_layout('custom_grid9')
        first, second, third = wall.tiles[:3]
        second.set_room(dict(room_id='1002', live=False))
        third.set_room(dict(room_id='1003', live=False))
        wall.relayout(force=True)
        self.app.processEvents()
        self.assertEqual(wall.visible_tiles(), [first, second, third])
        self.assertEqual(first.geometry().right() + 1, second.x())
        self.assertEqual(second.geometry().right() + 1, third.x())
        window.configure_wall_panes({1: first})
        panel = wall.pane_danmaku.panels[1]
        self.assertTrue(panel.isVisible())
        self.assertEqual(first.geometry().right() + 1, panel.x())
        self.assertEqual(panel.geometry().right() + 1, third.x())
        self.assertEqual(wall.pane_danmaku.target(panel), first)

        second.set_room(None)
        third.set_room(None)
        wall.set_layout('2x2')
        self.assertTrue(switch.isChecked())
        switch.click()
        self.assertTrue(dialog.auto_save.flush())
        self.app.processEvents()
        self.assertFalse(window.settings['wall_seamless'])
        self.assertEqual(wall.grid.spacing(), 8)
        self.assertEqual((first.geometry(), second.geometry()), original)
        self.assertFalse(first.video.mask().contains(QPoint(0, 0)))

    def test_seamless_shared_edge_still_previews_and_resizes(self):
        from selfcheck_corner_drag_updates import move_to, release_at
        from selfcheck_pane_borders import press

        window = self.wall_window()
        wall = window.wall
        wall.set_seamless(True)
        self.app.processEvents()
        first, second = wall.visible_tiles()[:2]
        border = wall._pane_borders[first]
        self.assertEqual(first.geometry().right() + 1, second.x())
        self.assertEqual(border.targets['right'], wall._pane_borders[second].targets['left'])
        before = first.width()
        origin = press(border, ['right'])
        moved = origin + QPoint(30, 0)
        move_to(border, moved)
        QTest.qWait(80)
        self.assertTrue(wall._border_preview.isVisible())
        self.assertEqual(first.width(), before)
        release_at(border, moved)
        self.assertEqual(first.width(), before + 30)
        self.assertEqual(first.geometry().right() + 1, second.x())
        wall.set_seamless(False)
        self.assertEqual(first.geometry().right() + 9, second.x())

    def test_wall_quick_floats_fill_a_plain_wall_once_per_room(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        source, duplicate, *others = wall.tiles[:4]
        duplicate.set_room(dict(source.room))
        self.assertFalse(panes.bindings())
        panes.open_for_tile(source)
        existing, = panes.floating
        window.sidebar.wall_settings_button.click()
        menu = window.wall_quick_settings.menu
        self.assertTrue(menu.floats.isEnabled())
        self.assertFalse(menu.floats.isChecked())
        self.assertIn('部分开启', menu.floats_label.text())
        menu.floats.click()
        self.assertIn(existing, panes.floating)
        self.assertCountEqual([panes.target(panel) for panel in panes.floating], [source, *others])
        self.assertTrue(all(floating.cell is None for floating in panes.floating.values()))
        window.sidebar.wall_settings_button.click()
        self.assertTrue(menu.floats.isChecked())
        menu.floats.click()
        self.assertFalse(panes.floating)
        self.assertFalse(panes.bindings())

    def test_float_cell_setting_round_trips_and_resets(self):
        from ddm.settings_danmaku import DanmakuSettingsPage
        page = DanmakuSettingsPage({'danmaku_float_reuse_cell': True, 'danmaku_float_keep_video_slots': True})
        self.addCleanup(page.deleteLater)
        self.assertTrue(page.values()['danmaku_float_reuse_cell'])
        self.assertTrue(page.values()['danmaku_float_keep_video_slots'])
        self.assertTrue(page.float_keep_video_slots.isEnabled())
        page.float_cell_mode.buttons['reserve'].click()
        self.assertFalse(page.float_keep_video_slots.isEnabled())
        page.float_cell_mode.buttons['reuse'].click()
        self.assertTrue(page.float_keep_video_slots.isEnabled())
        self.assertTrue(page.float_keep_video_slots.isChecked())
        page.reset()
        self.assertFalse(page.values()['danmaku_float_reuse_cell'])
        self.assertFalse(page.values()['danmaku_float_keep_video_slots'])
        self.assertFalse(page.float_keep_video_slots.isEnabled())

    def test_reuse_legacy_chat_reserves_its_video_backing_slot(self):
        window = self.wall_window()
        window.settings['danmaku_float_reuse_cell'] = True
        wall, panes = window.wall, window.wall.pane_danmaku
        wall.set_layout('dm_main2')
        window.sync_danmaku()
        panel = wall.danmaku
        cell = panes.panel_cell(panel)
        source = panes.target(panel)
        panel.float_button.click()
        self.assertTrue(panes.cell_tiles()[cell].isVisible())
        self.assertIs(panes.target(panel), source)
        panes.floating[panel].window.close()
        self.assertIs(panes.panels[cell], panel)
        panel.float_button.click()
        panes.reset_preset(wall.layout_id)
        self.assertFalse(panes.floating)
        self.assertIs(panes.panels[cell], panel)

    def test_added_rooms_skip_chat_backing_slots_in_corner_layout(self):
        window = self.wall_window()
        wall = window.wall
        wall.set_layout('corner')
        wall.tiles[1].set_room(None)
        wall.tiles[2].set_room(None)
        window.configure_wall_panes({1: None, 2: None})
        tiles = list(wall.tiles)
        self.assertTrue(tiles[1].isHidden() and tiles[2].isHidden())
        with patch.object(window, 'start_tile') as start:
            for index in (4, 5):
                room = dict(room_id=str(1001 + index), uname=f'New {index}', live=False)
                if index == 4:
                    window._on_room_added(room)
                else:
                    window.add_to_wall(room)
                self.assertIs(window._tile_of(room['room_id']), tiles[index])
                self.assertTrue(tiles[index].isVisible())
                start.assert_called_with(tiles[index])
        self.assertEqual(wall.tiles, tiles)
        self.assertEqual(set(wall.pane_danmaku.bindings()), {1, 2})
        self.assertFalse(tiles[1].room.get('room_id'))
        self.assertFalse(tiles[2].room.get('room_id'))
        # Dropping on a chat pane still links its source rather than playing there.
        panel = wall.pane_danmaku.panels[1]
        wall.pane_danmaku.room_dropped(panel, '1005')
        self.assertIs(wall.pane_danmaku.target(panel), tiles[4])
        self.assertFalse(tiles[1].room.get('room_id'))

    def test_hidden_video_overflow_remains_eligible_for_automatic_placement(self):
        window = self.wall_window()
        window.wall.set_layout('corner')
        overflow = window.wall.tiles[4]
        overflow.set_room(dict(room_id='9000', uname='Retained overflow', live=False))
        window.wall.set_layout('2x2')
        self.assertTrue(overflow.isHidden())
        overflow.set_room(None)
        room = dict(room_id='1005', uname='Overflow', live=False)
        with patch.object(window, 'start_tile') as start:
            window.add_to_wall(room)
        self.assertIs(window._tile_of('1005'), overflow)
        start.assert_called_once_with(overflow)

    def test_default_pane_starts_with_empty_main_and_occupied_secondary(self):
        room = dict(room_id='1002', uname='Secondary fixture', live=False)
        state = {'plugins_enabled': [], 'settings': {'close_behavior': 'exit'},
                 'ui': {'layout_landscape': 'dm_main2'}}
        window = MainWindow([dict(room)], [{}, dict(room)], layout_id='dm_main2', state=state)
        self.addCleanup(self.close_window, window)
        panes = window.wall.pane_danmaku
        self.assertTrue(window.wall.has_danmaku)
        self.assertIsNone(panes.target(window.wall.danmaku))
        picker = window.wall.danmaku.source_picker
        self.assertEqual(picker.anchor.identity[0], '')
        self.assertIn(window.wall.tiles[1], picker.buttons)
        self.assertFalse(picker.anchor.isChecked())
        picker.choose(window.wall.tiles[1])
        self.assertIs(panes.target(window.wall.danmaku), window.wall.tiles[1])
        self.assertEqual(picker.anchor.identity[0], '1002')

    def test_default_pane_clears_source_when_main_video_is_closed(self):
        window = self.wall_window()
        window.wall.set_layout('dm_main2')
        window._refresh_meta()
        panel = window.wall.danmaku
        main = window.wall.tiles[window.wall.main_index()]
        self.assertIs(window.wall.pane_danmaku.target(panel), main)
        self.assertFalse(panel.float_button.isHidden())
        window._on_close_tile(dict(main.room))
        self.assertIsNone(window.wall.pane_danmaku.target(panel))
        self.assertEqual(panel._linked_room_id, '')
        self.assertEqual(panel.source_picker.anchor.identity[0], '')
        self.assertFalse(panel.source_picker.anchor.isChecked())
        self.assertTrue(panel.source_picker.buttons)
        self.assertTrue(panel.float_button.isHidden())

        source = next(iter(panel.source_picker.buttons))
        panel.source_picker.choose(source)
        panel.float_button.click()
        window._on_close_tile(dict(source.room))
        self.assertFalse(panel.source_picker.anchor.isChecked())
        self.assertTrue(panel.float_button.isVisible())
        self.assertEqual(panel.float_button.kind, 'close')
        panel.float_button.click()
        self.assertTrue(panel.float_button.isHidden())

    def test_wall_menu_converts_restores_and_preserves_room_and_sound(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        backing, source = wall.tiles[1], wall.tiles[0]
        original = deepcopy(backing.room), backing.volume, backing.muted
        menu = backing.build_menu()
        self.addCleanup(menu.deleteLater)
        self.assertNotIn('格子内容…', [action.text() for action in menu.actions()])
        next(action for action in menu.actions() if action.text() == '切换为弹幕').trigger()
        panel = panes.panels[1]
        self.assertTrue(panel.isVisible())
        self.assertTrue(backing.isHidden())
        self.app.processEvents()
        picker = panel.source_picker
        self.assertTrue(picker.expanded)
        self.assertEqual(set(picker.buttons), {wall.tiles[0], wall.tiles[2], wall.tiles[3]})
        self.assertIsNone(panes.target(panel))
        self.assertTrue(panel.float_button.isHidden())
        QTest.mouseClick(picker.buttons[source], Qt.LeftButton)
        self.assertFalse(picker.expanded)
        self.assertTrue(picker.tray.isHidden())
        self.assertTrue(picker.anchor.isVisible())
        self.assertFalse(panel.font_controls.isHidden())
        self.assertIs(panes.target(panel), source)
        self.assertEqual(panel._linked_room_id, '1001')
        self.assertTrue(panel.float_button.isVisible())
        self.assertLess(panel.float_button.geometry().right(), picker.x())
        self.assertLess(picker.x() - panel.float_button.geometry().right(), 10)
        self.assertLessEqual(picker.geometry().right(), panel.count.x())
        self.assertLess(panel.count.x() - picker.geometry().right(), 10)
        self.assertEqual((backing.room, backing.volume, backing.muted), original)
        menu = panes.create_menu(1)
        self.addCleanup(menu.deleteLater)
        self.assertEqual([action.text() for action in menu.actions()], ['恢复直播画面'])
        next(action for action in menu.actions() if action.text() == '恢复直播画面').trigger()
        self.assertFalse(panes.panels)
        self.assertTrue(backing.isVisible())
        self.assertEqual((backing.room, backing.volume, backing.muted), original)
        source.setProperty('pictureInPicture', True)
        menu = source.build_menu()
        self.addCleanup(menu.deleteLater)
        self.assertNotIn('切换为弹幕', [action.text() for action in menu.actions()])
        source.setProperty('pictureInPicture', False)

    def test_avatar_strip_reopens_scrolls_and_receives_late_cached_images(self):
        window = self.wall_window()
        wall = window.wall
        wall.set_layout('4x4')
        for index, tile in enumerate(wall.tiles[4:], 4):
            tile.set_room(dict(room_id=str(1001 + index), uname=f'主播 {index + 1}', live=False))
        window.configure_wall_panes({15: wall.tiles[0]})
        panel = wall.pane_danmaku.panels[15]
        picker = panel.source_picker
        QTest.mouseClick(picker.anchor, Qt.LeftButton)
        self.assertTrue(picker.expanded)
        self.assertEqual(len(picker.buttons), 15)
        positions = [button.x() for button in picker.buttons.values()]
        self.assertEqual(positions, sorted(positions, reverse=True))
        self.assertGreater(picker.scroll.horizontalScrollBar().maximum(), 0)
        # Every candidate remains reachable within the existing header height.
        bar = picker.scroll.horizontalScrollBar()
        bar.setValue(0)
        self.assertEqual(picker.buttons[wall.tiles[14]].x(), 0)
        height = panel.header.height()
        selected = wall.tiles[14]
        QTest.mouseClick(picker.buttons[selected], Qt.LeftButton)
        self.assertIs(wall.pane_danmaku.target(panel), selected)
        self.assertEqual(panel.header.height(), height)
        self.assertEqual(picker.anchor.identity[0], selected.room['room_id'])
        picker.set_expanded(True, animate=False)
        QTest.keyClick(picker.buttons[selected], Qt.Key_Escape)
        self.assertFalse(picker.expanded)
        self.assertTrue(picker.anchor.isVisible())
        # Avatar loading updates an already selected anchor without clearing its source.
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor('red'))
        target = wall.tiles[0]
        window.configure_wall_panes({15: target})
        window._on_room_avatar(target.room['room_id'], pixmap)
        self.assertEqual(picker.anchor.face_key, pixmap.cacheKey())
        self.assertEqual(picker.buttons[target].face_key, pixmap.cacheKey())
        self.assertIs(wall.pane_danmaku.target(panel), target)

    def test_avatar_header_only_compacts_when_candidates_do_not_fit(self):
        window = self.wall_window()
        window.configure_wall_panes({3: window.wall.tiles[0]})
        panel = window.wall.pane_danmaku.panels[3]
        picker = panel.source_picker
        panel.resize(700, 300)
        self.app.processEvents()
        picker.set_expanded(True, animate=False)
        self.assertTrue(panel.title.isVisible())
        self.assertTrue(panel.font_controls.isVisible())
        self.assertGreaterEqual(picker.tray.x(), panel.font_controls.geometry().right())
        self.assertLessEqual(picker.tray.geometry().right(), panel.count.x())
        panel.resize(210, 300)
        self.app.processEvents()
        self.assertTrue(picker.expanded)
        self.assertTrue(panel.title.isHidden())
        self.assertTrue(panel.font_controls.isHidden())
        self.assertEqual(panel.float_button.x(), panel.header.layout().contentsMargins().left())
        self.assertLess(panel.float_button.geometry().right(), picker.tray.x())
        panel.resize(700, 300)
        self.app.processEvents()
        self.assertTrue(panel.title.isVisible())
        self.assertTrue(panel.font_controls.isVisible())
        self.assertGreaterEqual(picker.tray.x(), panel.font_controls.geometry().right())
        picker.set_expanded(False, animate=False)
        self.assertTrue(panel.title.isVisible())
        self.assertTrue(panel.font_controls.isVisible())

    def test_lower_corners_are_continuous_with_and_without_send_bar(self):
        from ddm import continuous_corners
        host = QWidget()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        host.setObjectName('PanelCornersFixture')
        host.setStyleSheet('#PanelCornersFixture {background: #ff00ff;}')
        host.setGeometry(-10000, -10000, 384, 304)
        panel = DanmakuPanel(host)
        panel.setGeometry(12, 12, 360, 280)
        panel.body.setPlainText('\n'.join('滚动消息 ' + str(index) for index in range(100)))
        host.show()
        for mode in ('dark', 'light'):
            theme.apply(mode)
            self.app.setStyleSheet(theme.qss())
            for sending in (False, True):
                with self.subTest(theme=mode, send_bar=sending):
                    panel.composer_bar.setVisible(sending)
                    self.app.processEvents()
                    panel.body.verticalScrollBar().setValue(panel.body.verticalScrollBar().maximum())
                    surface = panel.composer_bar if sending else panel.body
                    values = continuous_corners._filter.values(surface)
                    self.assertEqual(values['border-bottom-left-radius'], '10px')
                    self.assertEqual(values['border-bottom-right-radius'], '10px')
                    image = host.grab().toImage()
                    scale = image.devicePixelRatio()
                    for x in (12, 13, 370, 371):
                        self.assertEqual(image.pixelColor(round(x * scale), round(291 * scale)).name(), '#ff00ff')
                    self.assertNotEqual(image.pixelColor(round(180 * scale), round(291 * scale)).name(), '#ff00ff')

    def test_avatar_motion_is_right_anchored_interruptible_and_stops_when_hidden(self):
        from ddm import motion
        window = self.wall_window()
        window.configure_wall_panes({3: window.wall.tiles[1]})
        panel = window.wall.pane_danmaku.panels[3]
        picker = panel.source_picker
        with patch.object(motion, 'enabled', return_value=True):
            picker.set_expanded(True)
            picker.animation.setCurrentTime(60)
            progress = picker.progress
            self.assertGreater(progress, 0)
            self.assertLess(progress, 1)
            picker.set_expanded(False)
            self.assertAlmostEqual(picker.animation.startValue(), progress)
            picker.animation.setCurrentTime(picker.animation.duration())
            self.assertTrue(picker.tray.isHidden())
            self.assertTrue(picker.anchor.isVisible())
            picker.set_expanded(True)
            panel.hide()
            self.assertEqual(picker.animation.state(), QAbstractAnimation.Stopped)
            self.assertFalse(picker.expanded)
            self.assertTrue(picker.tray.isHidden())
        panel.show()
        with patch.object(motion, 'enabled', return_value=False):
            picker.set_expanded(True)
            self.assertEqual(picker.progress, 1)
            self.assertEqual(picker.animation.state(), QAbstractAnimation.Stopped)

    def test_multiple_panes_share_clients_and_route_messages_status_and_sc(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({2: first, 3: first})
        panels = panes.rendered()
        self.assertEqual(len(panels), 1)
        self.assertEqual(set(window._danmaku_clients), {'1001', '1002'})  # visible SC sources too
        client = window._danmaku_clients['1001']
        client.message.emit(dict(kind='danmaku', text='共享消息', uname='测试'))
        for panel in panels:
            self.assertEqual(panel._blocks[-1]['text'], '共享消息')
        client.status.emit('已连接')
        self.assertTrue(all(panel._status == '已连接' for panel in panels))
        now = int(time.time())
        client.message.emit(dict(kind='super_chat', id='shared-sc', uid='1', uname='测试',
                                 price=30, message='共享 SC', start_time=now, end_time=now + 120))
        self.assertTrue(all(panel.super_chats._events for panel in panels))
        client.message.emit(dict(kind='super_chat_delete', ids=['shared-sc']))
        self.assertTrue(all(not panel.super_chats._events for panel in panels))
        window.configure_wall_panes({2: first, 3: second})
        panels = list(panes.panels.values())
        self.assertIs(window._danmaku_clients['1001'], client)
        client.message.emit(dict(kind='danmaku', text='只给第一栏'))
        self.assertEqual(panels[0]._blocks[-1]['text'], '只给第一栏')
        self.assertFalse(any(event.get('text') == '只给第一栏' for event in panels[1]._blocks))
        # Old clients queued after a source change must not route into the new pane.
        first.set_room(dict(room_id='2001', uname='新主播', live=True))
        window.sync_danmaku()
        client.message.emit(dict(kind='danmaku', text='旧房间排队消息'))
        self.assertFalse(any(event.get('text') == '旧房间排队消息' for event in panels[0]._blocks))
        self.assertEqual(panels[0]._linked_room_id, '2001')
        first.set_room(None)
        window.sync_danmaku()
        self.assertEqual(panels[0]._linked_room_id, '')
        self.assertEqual(panels[0].count.property("state"), "idle")
        self.assertIsNone(panes.target(panels[0]))

    def test_swap_and_move_keep_explicit_sources_and_recording_is_not_interrupted(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({3: first})
        wall.tiles[0], wall.tiles[1] = second, first
        wall.relayout(force=True)
        window.sync_danmaku()
        self.assertIs(panes.target(panes.panels[3]), first)
        with patch.object(window, '_hot_swap', return_value=False):
            window._on_tile_swapped('1001', second)
        self.assertIs(panes.target(panes.panels[3]), second)
        self.assertEqual(panes.target(panes.panels[3]).room['room_id'], '1001')
        destination = panes.cell_for_tile(first)
        panes.move(3, first)
        self.assertIn(destination, panes.bindings())
        self.assertIs(panes.target(panes.panels[destination]), second)
        window.recorder.sessions[second] = Mock(recording=True, stopping=False)
        self.addCleanup(window.recorder.sessions.clear)
        with self.assertRaisesRegex(ValueError, '录制'):
            window.configure_wall_panes({panes.cell_for_tile(second): None})

    def test_video_drop_uses_independent_settings_for_linked_and_unlinked_panes(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        owner, video, _other, backing = wall.tiles[:4]
        for linked in (False, True):
            for swap in (False, True):
                with self.subTest(linked=linked, swap=swap):
                    window.settings['danmaku_drag_linked_swap'] = swap if linked else not swap
                    window.settings['danmaku_drag_unlinked_swap'] = swap if not linked else not swap
                    window.configure_wall_panes({3: owner if linked else -1})
                    original = panes.panels[3]
                    self.drop_video(original, video, 3)
                    self.assertEqual(panes.bindings(), {1: owner if linked else -1} if swap else {3: video})
                    if swap:
                        self.assertIs(panes.cell_tiles()[3], video)
                        self.assertIs(panes.cell_tiles()[1], backing)
                        self.assertIs(panes.panels[1], original)
                        panes.move(1, video)
                    else:
                        self.assertIs(panes.cell_tiles()[1], video)

    def test_video_drop_in_legacy_layout_can_relink_or_swap_without_relinking(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        window._on_layout_changed('dm_main2')
        cell = wall._danmaku_cell
        owner, video = wall.tiles[:2]
        destination = panes.cell_for_tile(video)
        self.assertFalse(panes.custom)
        self.drop_video(wall.danmaku, video, cell)
        self.assertEqual(panes.bindings(), {cell: video})
        self.assertIs(panes.cell_tiles()[destination], video)
        window._on_layout_changed('dm_main2')
        self.assertIs(panes.target(wall.danmaku), owner)

        window.settings['danmaku_drag_linked_swap'] = True
        self.drop_video(wall.danmaku, video, cell)
        self.assertEqual(panes.bindings(), {destination: owner})
        self.assertIs(panes.cell_tiles()[cell], video)
        self.assertIs(panes.panels[destination], wall.danmaku)

    def test_video_drop_swaps_only_the_hit_cell_of_a_merged_pane(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        owner, video = wall.tiles[:2]
        window.settings['danmaku_drag_linked_swap'] = True
        window.configure_wall_panes({2: owner, 3: owner})
        merged, = panes.rendered()
        self.drop_video(merged, video, 2)
        self.assertEqual(panes.bindings(), {1: owner, 3: owner})
        self.assertIs(panes.cell_tiles()[2], video)
        self.assertTrue(video.isVisible())

    def test_explicit_layout_selection_resets_manual_panes_including_current_layout(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        window.configure_wall_panes({3: wall.tiles[0]})
        window._on_layout_changed('1x2')
        window._on_layout_changed('2x2')
        self.assertFalse(panes.bindings())
        self.assertTrue(all(tile.isVisible() for tile in wall.tiles[:4]))
        window.configure_wall_panes({3: wall.tiles[0]})
        window._on_layout_changed('2x2')
        self.assertFalse(panes.bindings())
        window._on_layout_changed('dm_main2')
        default = layouts.danmaku_cell('dm_main2')
        window.configure_wall_panes({0: -1})
        window._on_layout_changed('dm_main2')
        self.assertFalse(panes.custom)
        self.assertEqual(set(panes.bindings()), {default})
        self.assertIs(panes.panels[default], wall.danmaku)

    def test_merged_pane_context_menu_restores_only_the_clicked_cell(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        source = wall.tiles[0]
        window.configure_wall_panes({2: source})
        original = panes.panels[2]
        client = window._danmaku_clients['1001']
        client.message.emit(dict(kind='danmaku', text='合并前消息'))
        window.configure_wall_panes({2: source, 3: source})
        merged, = panes.rendered()
        self.assertIs(merged, original)
        self.assertEqual(merged._blocks[-1]['text'], '合并前消息')
        self.assertEqual(merged.geometry(), panes.rectangles[2].united(panes.rectangles[3]))
        self.assertEqual(set(panes.cells_for(2)), {2, 3})
        wall.set_fullscreen_tile(source)
        window.sync_danmaku()
        self.assertTrue(all(panel.isHidden() for panel in panes.all_panels()))
        wall.set_fullscreen_tile(None)
        window.sync_danmaku()
        self.assertIs(panes.rendered()[0], merged)
        self.assertEqual(merged._blocks[-1]['text'], '合并前消息')
        panes.room_dropped(merged, '1002')
        self.assertTrue(all(tile is wall.tiles[1] for tile in panes.bindings().values()))
        self.assertEqual(len(panes.rendered()), 1)
        source = wall.tiles[1]
        for clicked, remaining in ((2, 3), (3, 2)):
            with self.subTest(clicked=clicked):
                window.configure_wall_panes({2: source, 3: source})
                merged, = panes.rendered()
                window._danmaku_clients['1002'].message.emit(dict(kind='danmaku', text='保留的消息'))
                viewport = merged.body.viewport()
                point = wall.mapToGlobal(panes.rectangles[clicked].center())
                event = QContextMenuEvent(QContextMenuEvent.Mouse, viewport.mapFromGlobal(point), point)

                def restore(cell, _point):
                    menu = panes.create_menu(cell)
                    self.addCleanup(menu.deleteLater)
                    self.assertEqual([action.text() for action in menu.actions()], ['恢复直播画面'])
                    menu.actions()[0].trigger()

                with patch.object(panes, 'open_menu', side_effect=restore):
                    self.app.sendEvent(viewport, event)
                self.assertEqual(panes.bindings(), {remaining: source})
                self.assertTrue(panes.cell_tiles()[clicked].isVisible())
                self.assertIs(panes.rendered()[0], merged)
                self.assertEqual(merged._blocks[-1]['text'], '保留的消息')
                self.assertEqual(merged.geometry(), panes.rectangles[remaining])

    def test_corner_right_column_merges_across_independently_allocated_rows(self):
        window = self.wall_window()
        window._on_layout_changed('corner')
        wall, panes = window.wall, window.wall.pane_danmaku
        source = wall.tiles[0]
        window.configure_wall_panes({1: source, 2: source, 5: source})
        for width in (1200, 1401):
            with self.subTest(width=width):
                wall.reset_corner_ratios()
                window.resize(width, 900)
                self.app.processEvents()
                wall.relayout(force=True)
                window.sync_danmaku()
                self.assertEqual(panes.rectangles[1].left(), panes.rectangles[5].left())
                # A small independent drag may offset the column without covering a video.
                area = wall._corner_area()
                gap = wall.grid.spacing()
                wall._corner_width_ratio = (panes.rectangles[1].left() - area.left() - gap + 2) / (area.width() - gap)
                wall.relayout(force=True)
                self.assertNotEqual(panes.rectangles[1].left(), panes.rectangles[5].left())
                merged, = panes.rendered()
                expected = panes.rectangles[1].united(panes.rectangles[2]).united(panes.rectangles[5])
                self.assertEqual(merged.geometry(), expected)
                self.assertEqual(set(panes.cells_for(5)), {1, 2, 5})
                for cell in (0, 3, 4):
                    self.assertFalse(merged.geometry().intersects(panes.rectangles[cell]))
        client = window._danmaku_clients['1001']
        client.message.emit(dict(kind='danmaku', text='环绕布局单份消息'))
        self.assertEqual(sum(event.get('text') == '环绕布局单份消息' for event in merged._blocks), 1)
        panes.request(5, video=True)
        self.assertEqual(set(panes.bindings()), {1, 2})
        self.assertTrue(wall.tiles[5].isVisible())
        self.assertTrue(all(not wall.tiles[cell].isVisible() for cell in (1, 2)))

    def test_corner_default_rows_align_without_overriding_independent_ratios(self):
        wall = WallGrid([], layout_id='corner')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        wall.show()
        for width in (1200, 1401, 3840):
            with self.subTest(width=width):
                wall.resize(width, 900)
                self.app.processEvents()
                wall.relayout(force=True)
                self.assertEqual(wall.tiles[1].x(), wall.tiles[5].x())
                self.assertEqual(wall.tiles[0].geometry().right(), wall.tiles[4].geometry().right())
        wall.restore_corner_ratios(dict(width=.6, bottom=[.3, .7]))
        self.assertEqual(wall.corner_ratios()['width'], .6)
        self.assertEqual(wall.corner_ratios()['bottom'], [.3, .7])
        self.assertNotEqual(wall.tiles[1].x(), wall.tiles[5].x())
        wall.reset_corner_ratios()
        self.assertEqual(wall.tiles[1].x(), wall.tiles[5].x())
        main = wall.tiles[0].geometry()
        wall.restore_corner_ratios(dict(width=2 / 3, bottom=[.3, .7]))
        self.assertEqual(wall.tiles[0].geometry(), main)

    def test_rectangular_merges_never_cover_unrelated_cells_and_follow_source_changes(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        window._on_layout_changed('3x3')
        first, second = wall.tiles[:2]
        cases = [({3: first, 4: first}, 1), ({3: first, 6: first}, 1),
                 ({3: first, 4: first, 6: first, 7: first}, 1),
                 ({3: first, 7: first}, 2), ({3: first, 4: second}, 2),
                 ({3: -1, 4: -1}, 2), ({3: first, 4: first, 6: first}, 2)]
        for bindings, count in cases:
            with self.subTest(cells=tuple(bindings), count=count):
                window.configure_wall_panes(bindings)
                self.assertEqual(len(panes.rendered()), count)
                for panel in panes.rendered():
                    for cell, rect in panes.rectangles.items():
                        if cell not in bindings:
                            self.assertFalse(panel.geometry().intersects(rect))
        window.configure_wall_panes({3: first, 4: second})
        second.set_room(dict(first.room))
        window.sync_danmaku()
        self.assertEqual(len(panes.rendered()), 1)
        second.set_room(dict(room_id='2002', uname='换台', live=True))
        window.sync_danmaku()
        self.assertEqual(len(panes.rendered()), 2)
        self.assertEqual({panel._linked_room_id for panel in panes.rendered()}, {'1001', '2002'})
        second.set_room(None)
        window.sync_danmaku()
        self.assertEqual(len(panes.rendered()), 2)
        self.assertEqual(panes.panels[4]._linked_room_id, '')

    def test_custom_grids_merge_adjacent_chat_and_leave_vacant_cells_clear(self):
        for layout, size in (('custom_grid9', 3), ('custom_grid16', 4)):
            with self.subTest(layout=layout):
                window = self.window([dict(room_id='1001', uname='主播', live=True)], offscreen=True)
                window.layout_presets.select_builtin(layout)
                wall, panes = window.wall, window.wall.pane_danmaku
                source = wall.tiles[0]
                top, bottom = 2, size + 2
                window.configure_wall_panes({top: source})
                original, = panes.rendered()
                client = window._danmaku_clients['1001']
                client.message.emit(dict(text='合并前消息'))

                window.configure_wall_panes({top: source, bottom: source})
                merged, = panes.rendered()
                self.assertIs(merged, original)
                self.assertTrue(merged.isVisible())
                self.assertTrue(panes.panels[bottom].isHidden())
                self.assertEqual(merged.geometry(), panes.rectangles[top].united(panes.rectangles[bottom]))
                self.assertIs(window._danmaku_clients['1001'], client)
                client.message.emit(dict(text='合并后消息'))
                self.assertEqual([event['text'] for event in merged._blocks], ['合并前消息', '合并后消息'])

                window.configure_wall_panes({1: source, top: source, bottom: source})
                self.assertEqual(len(panes.rendered()), 2)
                vacant = panes.rectangles[size + 1]
                self.assertFalse(any(panel.geometry().intersects(vacant) for panel in panes.rendered()))

    def test_delete_removes_only_the_hovered_custom_chat_cell(self):
        window = self.window([dict(room_id='1001', uname='主播', live=True)], offscreen=True)
        window.layout_presets.select_builtin('custom_grid9')
        wall, panes = window.wall, window.wall.pane_danmaku
        source = wall.tiles[0]
        window.configure_wall_panes({2: source, 5: source})
        merged = panes.panels[5]
        client = window._danmaku_clients['1001']
        client.message.emit(dict(text='保留的弹幕'))
        self.app.setActiveWindow(window)
        merged.body.setFocus()
        self.app.processEvents()

        for clicked, remaining in ((5, {2: source}), (2, {})):
            point = panes.rectangles[clicked].center()
            with patch('ddm.app_shortcuts.QCursor.pos', return_value=wall.mapToGlobal(point)):
                QTest.keyClick(merged.body, Qt.Key_Delete)
            self.assertEqual(panes.bindings(), remaining)
            self.assertIsNotNone(wall.snap_grid.vacant_unit_at(point))
            self.assertTrue(source.isVisible())
            self.assertEqual(source.room['room_id'], '1001')
            if remaining:
                self.assertEqual(panes.rendered(), [merged])
                self.assertEqual(merged._blocks[-1]['text'], '保留的弹幕')
        self.assertFalse(panes.rendered())

    def test_state_and_named_presets_restore_type_links_and_backing_slots(self):
        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        first, second = wall.tiles[:2]
        window.configure_wall_panes({2: first, 3: second})
        snapshot = window.room_preset_snapshot()
        self.assertEqual(snapshot['layout']['panels'], [dict(cell=2, source=0), dict(cell=3, source=1)])
        self.assertEqual(len(snapshot['slots']), 4)
        key = window.save_room_preset('双路弹幕')
        window.configure_wall_panes({})
        self.assertTrue(window.apply_room_preset(key))
        self.assertEqual(window.room_preset_snapshot(), snapshot)
        state = window.current_state()
        state["settings"]["danmaku_font_size"] = 18
        # A software restart creates a fresh QApplication in a new process.
        with tempfile.TemporaryDirectory(prefix='ddm-pane-state-') as directory:
            state_file = Path(directory) / 'state.json'
            state_file.write_text(json.dumps(state), encoding='utf-8')
            result = subprocess.run([sys.executable, str(Path(__file__).parent / 'checks/bootstrap.py'),
                str(Path(__file__).resolve()), '--restore-state', str(state_file)],
                capture_output=True, text=True, encoding='utf-8', timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS: fresh-process pane restoration', result.stdout)
        invalid = deepcopy(snapshot)
        invalid['layout']['panels'][0]['source'] = 3
        with self.assertRaises(ValueError):
            room_presets.validate(invalid)

    @unittest.skipUnless(NATIVE, 'Windows native floating window ownership check')
    def test_native_detached_fullscreen_keeps_existing_and_new_floats_above_video(self):
        import ctypes
        from ctypes import wintypes

        window = self.wall_window()
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        wall, panes = window.wall, window.wall.pane_danmaku
        source, other = wall.tiles[:2]

        user32 = ctypes.windll.user32
        user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.GetWindowLongW.restype = ctypes.c_long
        with patch.object(DanmakuFloatWindow, 'show', show_float_offscreen):
            panes.open_for_tile(source)
            panel, = panes.floating
            floating = panes.floating[panel].window
            handle = int(floating.winId())
            self.assertFalse(user32.GetWindowLongW(handle, -20) & 0x8)  # GWL_EXSTYLE / WS_EX_TOPMOST
            QTest.mouseClick(floating.pin, Qt.LeftButton)
            self.assertTrue(user32.GetWindowLongW(handle, -20) & 0x8)
            self.assertEqual(int(floating.winId()), handle)
            enter = window._fullscreen_presentation.enter
            with patch.object(window._fullscreen_presentation, 'enter',
                              side_effect=lambda tile: enter(tile, FULLSCREEN_RECT)):
                window._on_fullscreen(source)
            try:
                video = int(source.winId())
                self.assertTrue(user32.GetWindowLongW(handle, -20) & 0x8)
                QTest.mouseClick(floating.pin, Qt.LeftButton)
                self.assertFalse(user32.GetWindowLongW(handle, -20) & 0x8)
                source.raise_()
                self.assertEqual(user32.GetWindow(handle, 4), video)  # GW_OWNER
                above = user32.GetWindow(video, 3)  # GW_HWNDPREV
                while above and above != handle:
                    above = user32.GetWindow(above, 3)
                self.assertEqual(above, handle)
                self.assertTrue(floating.isVisible() and source.frameGeometry().intersects(floating.frameGeometry()))
                picker = panel.source_picker
                with patch('ddm.motion.enabled', return_value=False):
                    QTest.mouseClick(picker.anchor, Qt.LeftButton)
                    QTest.mouseClick(picker.buttons[other], Qt.LeftButton)
                self.assertIs(panes.target(panel), other)
                panes.open_for_tile(source)
                extra, = (entry.window for item, entry in panes.floating.items() if item is not panel)
                self.assertEqual(user32.GetWindow(int(extra.winId()), 4), video)
            finally:
                window._exit_fullscreen()
            self.assertEqual(int(floating.winId()), handle)
            for entry in panes.floating.values():
                self.assertEqual(user32.GetWindow(int(entry.window.winId()), 4), int(window.winId()))

    @unittest.skipUnless(NATIVE, 'Windows native window stacking check')
    def test_native_quick_layer_stays_below_moving_chat_without_mask_holes(self):
        import ctypes
        from ctypes import wintypes
        from ddm.danmaku_float_window import DanmakuFloatWindow
        from selfcheck_mpv import pump

        window = self.wall_window()
        wall, panes = window.wall, window.wall.pane_danmaku
        origin = wall.mapToGlobal(QPoint())
        layer = wall.ensure_quick_danmaku_layer()
        group = layer.create_group(0, 0, wall.width(), wall.height())
        image = QImage(100, 20, QImage.Format_ARGB32)
        image.fill(QColor('white'))
        layer.add(group, image, 45, 65, image.width(), image.height(), speed=30)
        show = DanmakuFloatWindow.show

        def show_offscreen(floating):
            floating.setAttribute(Qt.WA_ShowWithoutActivating)
            floating.move(origin + QPoint(32 + 20 * len(panes.floating), 40))
            show(floating)

        with patch.object(DanmakuFloatWindow, 'show', show_offscreen):
            for source in wall.tiles[:2]:
                panes.open_for_tile(source)
        pump(self.app, .2)
        floats = [floating.window for floating in panes.floating.values()]
        self.assertEqual(len(floats), 2)
        self.assertTrue(layer.window.isVisible())
        overlay = int(layer.window.winId())
        user32 = ctypes.windll.user32
        user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetWindow.restype = wintypes.HWND

        def assert_above_overlay(floating):
            above = user32.GetWindow(overlay, 3)  # GW_HWNDPREV
            handle = int(floating.winId())
            while above and above != handle:
                above = user32.GetWindow(above, 3)
            self.assertEqual(above, handle)

        for step in range(3):
            floats[0].move(origin + QPoint(75 + step * 35, 55 + step * 12))
            layer.raise_()
            pump(self.app, .05)
            for floating in floats:
                assert_above_overlay(floating)
                point = floating.mapToGlobal(floating.rect().center()) - origin
                self.assertTrue(wall.rect().contains(point))
                self.assertTrue(layer.window.mask().contains(point))
        point = floats[0].mapToGlobal(floats[0].rect().center()) - origin
        with patch('ddm.video_danmaku_quick._stack_below', return_value=False):
            self.assertTrue(layer._update_occlusion())
            self.assertFalse(layer.window.mask().contains(point))
        self.assertTrue(layer._update_occlusion())
        self.assertTrue(layer.window.mask().contains(point))
        for floating in floats:
            floating.close()
        pump(self.app, .08)
        self.assertTrue(layer.window.mask().contains(wall.rect().center()))

    @unittest.skipUnless(NATIVE, 'Windows native local MP4 check')
    def test_native_playback_core_and_hwnd_survive_type_changes_and_hot_swap(self):
        from ddm.player import TilePlayer
        from selfcheck_mpv import ready, pump
        window = self.wall_window()
        source, empty = window.wall.tiles[:2]
        empty.set_room(None)
        with tempfile.TemporaryDirectory(prefix='ddm-chat-panes-') as directory:
            media = Path(directory) / 'silent.mp4'
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '10', '-c:v', 'libx264',
                '-preset', 'ultrafast', str(media)], check=True, timeout=30)
            player = TilePlayer(source.video, window, silent=True)
            window.players[source] = player
            try:
                player.play(str(media))
                ready(self.app, player)
                core, handle, generation = player.player, int(source.video.winId()), player.state_generation
                position = player._prop('time-pos') or 0
                window.configure_wall_panes({2: source, 3: source})
                self.assertTrue(window._hot_swap(source, empty))
                pump(self.app, .3)
                self.assertIs(player.player, core)
                self.assertEqual(int(source.video.winId()), handle)
                self.assertGreater(player._prop('time-pos') or 0, position)
                self.assertTrue(all(window.wall.pane_danmaku.target(panel) is source
                                    for panel in window.wall.pane_danmaku.panels.values()))
                panes = window.wall.pane_danmaku
                panel, = panes.rendered()
                panel.float_button.click()
                self.assertTrue(panes.floating[panel].window.isVisible())
                self.assertIs(player.player, core)
                self.assertEqual(int(source.video.winId()), handle)
                panes.floating[panel].window.close()
                window.picture_in_picture.start([window.wall.tiles.index(source)])
                pump(self.app, .3)
                self.assertTrue(all(panel.isHidden() for panel in window.wall.pane_danmaku.all_panels()))
                window.picture_in_picture.restore(activate=True)
                self.assertEqual(len(window.wall.pane_danmaku.rendered()), 1)
                self.assertTrue(window.wall.pane_danmaku.rendered()[0].isVisible())
                window.settings['danmaku_drag_linked_swap'] = True
                panel, = panes.rendered()
                cell, destination = panes.panel_cell(panel), panes.cell_for_tile(source)
                self.drop_video(panel, source, cell)
                self.assertIs(panes.cell_tiles()[cell], source)
                self.assertIs(panes.bindings()[destination], source)
                pump(self.app, .15)
                self.assertIs(player.player, core)
                self.assertEqual(int(source.video.winId()), handle)
                window.configure_wall_panes({})
                self.assertIs(player.player, core)
                self.assertEqual(int(source.video.winId()), handle)
                self.assertEqual(player.state_generation, generation)
            finally:
                window.players.pop(source, None)
                player.release()

    def test_every_preset_accepts_arbitrary_cells_including_portrait_and_corner(self):
        wall = WallGrid([], layout_id='2x2')
        self.addCleanup(wall.deleteLater)
        self.addCleanup(wall.close)
        wall.resize(1200, 900)
        wall.show()
        self.app.processEvents()
        for identifier in layouts.BY_ID:
            with self.subTest(layout=identifier):
                wall.set_layout(identifier)
                count = layouts.capacity(identifier)
                wall.pane_danmaku.apply({0: None, count - 1: None})
                self.app.processEvents()
                widgets = wall._preset_widgets()
                expected = {0, count - 1} if layouts.snap_grid_size(identifier) else set(range(count))
                self.assertEqual(set(widgets), expected)
                self.assertEqual(set(wall.pane_danmaku.panels), {0, count - 1})
                self.assertTrue(all(panel.isVisible() for panel in wall.pane_danmaku.panels.values()))
                self.assertTrue(all(rect.width() > 0 and rect.height() > 0 for rect in
                                    (widget.geometry() for widget in widgets.values())))


def restore_state(path):
    state = json.loads(Path(path).read_text(encoding='utf-8'))
    case = PaneDanmakuTests('test_state_and_named_presets_restore_type_links_and_backing_slots')
    case.setUpClass()
    case.setUp()
    try:
        follows, rooms = config.build_rooms(state)
        window = MainWindow(follows, rooms, layout_id='2x2', state=state)
        window.settings['close_behavior'] = 'exit'
        case.addCleanup(case.close_window, window)
        window.move(-10000, -10000)
        window.show()
        case.app.processEvents()
        panes = window.wall.pane_danmaku
        case.assertEqual(set(panes.panels), {2, 3})
        case.assertTrue(all(panel.font_slider.value() == 18 for panel in panes.panels.values()))
        case.assertEqual([panes.target(panel).room['room_id'] for panel in panes.panels.values()], ['1001', '1002'])
        case.assertEqual(window.current_state()['ui']['pane_layouts'], state['ui']['pane_layouts'])
        print('PASS: fresh-process pane restoration', flush=True)
    finally:
        case.doCleanups()


if __name__ == '__main__':
    if '--restore-state' in sys.argv:
        restore_state(sys.argv[sys.argv.index('--restore-state') + 1])
    elif len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(PaneDanmakuTests, __file__, ('--native',) if NATIVE else ()))
    else:
        unittest.main(verbosity=2)
