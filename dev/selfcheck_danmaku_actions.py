"""Offline comment actions: hover, row clicks, copy and room-bound Enter dispatch."""
import os
from pathlib import Path
import sys
import unittest
from time import perf_counter
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit
from ddm import danmaku_actions, plugins, theme
from ddm.widgets import WallGrid

APP = QApplication.instance() or QApplication([])


class ActionsTests(unittest.TestCase):
    def setUp(self):
        APP.setStyleSheet(theme.qss())
        self.sent = []
        self.manager = plugins.PluginManager()
        sent = self.sent
        class Input(plugins.TileControl):
            def __init__(self, context):
                super().__init__(QLineEdit(context.parent), minimum_width=90)
                self.context = context
                self.widget.returnPressed.connect(self.send)
            def send(self):
                sent.append((self.context.room.get('room_id'), self.widget.text()))
            def focus_input(self):
                if not self.widget.isEnabled():
                    return False
                self.widget.setFocus(Qt.ShortcutFocusReason)
                return True
        self.manager.register_tile_control('synthetic', 'input', Input)
        self.wall = WallGrid([{'room_id': '12'}, {'room_id': '13'}], layout_id='dm_main2')
        self.wall.resize(1600, 800)
        self.wall.show()
        self.wall.activateWindow()
        for tile in self.wall.tiles:
            self.manager.attach_tile(tile)
        APP.processEvents()

    def tearDown(self):
        self.manager.unload()
        self.wall.close()
        self.wall.deleteLater()
        APP.processEvents()

    def choose(self, index, before=None):
        class TestMenu(danmaku_actions.CommentToolbar):
            def exec(menu, _position):
                self.assertEqual([a.text() for a in menu.command_actions], ['复制', '+1'])
                if before:
                    before(menu)
                return menu.command_actions[index]
        return patch.object(danmaku_actions, 'CommentToolbar', TestMenu)

    def test_copy_and_repeat_use_original_text_and_only_the_target_room(self):
        tile = self.wall.tiles[0]
        controls = tile._plugin_controls
        message = '  中文 [表情]   <原文>  '
        with self.choose(0):
            tile._show_danmaku_actions(message, QPoint())
        self.assertEqual(APP.clipboard().text(), message)
        self.assertEqual(self.sent, [])
        with self.choose(1):
            tile._show_danmaku_actions(message, QPoint())
        self.assertEqual(self.sent, [('12', message)])
        self.assertEqual(controls.entries[0].control.widget.text(), message)
        with self.choose(1, lambda _menu: tile.set_room({'room_id': '99'})):
            tile._show_danmaku_actions('stale', QPoint())
        self.assertEqual(self.sent, [('12', message)])

    def test_unavailable_or_readonly_input_cannot_send(self):
        controls = self.wall.tiles[0]._plugin_controls
        edit = controls.entries[0].control.widget
        edit.setReadOnly(True)
        self.assertFalse(controls.repeat_text('blocked', '12'))
        edit.setReadOnly(False)
        edit.setEnabled(False)
        self.assertFalse(controls.repeat_text('blocked', '12'))
        edit.setEnabled(True)
        edit.setMaxLength(3)
        self.assertFalse(controls.repeat_text('too long', '12'))
        self.assertFalse(controls.repeat_text('x', '13'))
        with self.choose(0, lambda menu: self.assertFalse(menu.repeat_button.isEnabled())):
            danmaku_actions.show_comment_menu(self.wall, 'copy only', None, QPoint())
        self.assertEqual(APP.clipboard().text(), 'copy only')
        self.assertEqual(self.sent, [])

    def test_real_popup_dispatches_one_send(self):
        def select_repeat():
            menu = QApplication.activePopupWidget()
            self.assertIsInstance(menu, danmaku_actions.CommentToolbar)
            QTest.mouseClick(menu.repeat_button, Qt.LeftButton)
        QTimer.singleShot(30, select_repeat)
        self.wall.tiles[0]._show_danmaku_actions('one actual menu selection', QPoint(80, 80))
        self.assertEqual(self.sent, [('12', 'one actual menu selection')])

    def test_escape_closes_toolbar_without_copy_or_send(self):
        APP.clipboard().setText('keep clipboard')
        def cancel():
            QTest.keyClick(QApplication.activePopupWidget(), Qt.Key_Escape)
        QTimer.singleShot(30, cancel)
        self.wall.tiles[0]._show_danmaku_actions('cancelled comment', QPoint(80, 80))
        self.assertEqual(APP.clipboard().text(), 'keep clipboard')
        self.assertEqual(self.sent, [])

    def test_small_tile_can_repeat_when_the_bar_has_no_room_for_input(self):
        tile = self.wall.tiles[1]
        tile.resize(200, 240)
        APP.processEvents()
        controls = tile._plugin_controls
        self.assertTrue(controls.widget.isHidden())
        self.assertTrue(controls.can_repeat())
        with self.choose(1):
            tile._show_danmaku_actions('small tile', QPoint())
        self.assertEqual(self.sent, [('13', 'small tile')])

    def test_chat_left_click_targets_body_and_ignores_blank_space(self):
        panel = self.wall.danmaku
        panel.add_message('Name', 'first <message>')
        panel.add_message('Other', 'second')
        APP.processEvents()
        body = panel.body
        cursor = body.textCursor()
        cursor.setPosition(0)
        position = body.cursorRect(cursor).center()
        with self.choose(0):
            QTest.mouseClick(body.viewport(), Qt.LeftButton, pos=position)
        self.assertEqual(APP.clipboard().text(), 'first <message>')
        with self.choose(1):
            QTest.mouseClick(body.viewport(), Qt.LeftButton, pos=position)
        self.assertEqual(self.sent, [('12', 'first <message>')])
        with patch.object(danmaku_actions, 'show_comment_menu') as show:
            QTest.mouseClick(body.viewport(), Qt.LeftButton,
                             pos=QPoint(20, body.viewport().height() - 10))
            show.assert_not_called()

    def test_hover_pauses_one_comment_and_resumes_without_jumping(self):
        video = self.wall.tiles[0].video_danmaku
        video.set_native_video(False)
        video.set_enabled(True)
        video.set_active(True)
        with patch.object(video, '_poll_hover'):
            self.assertTrue(video.add_event({'text': '  original   text  '}))
            self.assertTrue(video.add_event({'text': 'another comment'}))
            first, second = video.comments
            first.x, second.x = 160, 300
            point = QPoint(170, first.lane * video.lane_height() + 8)
            self.assertIs(video.comment_at(point), first)
            video._set_hover(first)
            video._last_tick = 100
            with patch('ddm.video_danmaku.perf_counter', return_value=100.1):
                video._tick()
            self.assertEqual(first.x, 160)
            self.assertLess(second.x, 300)
            received = []
            video.actionsRequested.disconnect()
            video.actionsRequested.connect(lambda text, _point: received.append(text))
            video._last_tick = perf_counter()
            QTest.qWait(650)
            self.assertEqual(received, [])
            QTest.qWait(450)
            self.assertEqual(received, [], 'Hover must never open the toolbar automatically')
            self.assertTrue(video.open_actions_at(video.mapToGlobal(point)))
            self.assertEqual(received, ['  original   text  '])
            video._set_hover(None)
            self.assertFalse(first.held)
            video._last_tick = 101
            with patch('ddm.video_danmaku.perf_counter', return_value=101.1):
                video._tick()
            self.assertLess(first.x, 160)
            video._set_hover(first)
            video.clear()
            self.assertIsNone(video._hovered)

    def test_cursor_hit_and_leave_release_comment(self):
        video = self.wall.tiles[0].video_danmaku
        video.set_native_video(False)
        video.set_enabled(True)
        video.set_active(True)
        self.assertTrue(video.add_event({'text': 'hover target'}))
        comment = video.comments[0]
        comment.x, comment.lane = 100, 2
        point = video.mapToGlobal(QPoint(110, 2 * video.lane_height() + 8))
        with patch('ddm.video_danmaku.QCursor.pos', return_value=point) as cursor, \
                patch.object(self.wall, 'isActiveWindow', return_value=True):
            video._poll_hover()
            self.assertIs(video._hovered, comment)
            self.assertTrue(comment.held)
            cursor.return_value = video.mapToGlobal(QPoint(-50, -50))
            video._poll_hover()
            self.assertIsNone(video._hovered)
            self.assertFalse(comment.held)

    def test_video_left_click_opens_toolbar_without_selecting_tile(self):
        tile = self.wall.tiles[0]
        video = tile.video_danmaku
        video.set_native_video(False)
        video.set_enabled(True)
        video.set_active(True)
        self.assertTrue(video.add_event({'text': 'clicked comment'}))
        video.comments[0].x = 160
        point = tile.video.mapFromGlobal(video.mapToGlobal(QPoint(170, 8)))
        selected = []
        tile.clicked.connect(selected.append)
        with self.choose(0):
            QTest.mouseClick(tile.video, Qt.LeftButton, pos=point)
        self.assertEqual(APP.clipboard().text(), 'clicked comment')
        self.assertEqual(selected, [])

    def test_chat_hover_feedback_and_transparent_horizontal_toolbar(self):
        panel = self.wall.danmaku
        panel.add_message('Viewer', 'hover feedback')
        APP.processEvents()
        body = panel.body
        cursor = body.textCursor()
        cursor.setPosition(0)
        point = body.cursorRect(cursor).center()
        plain = body.viewport().grab().toImage()
        body._hover_at(QPointF(point))
        self.assertIsNotNone(body._hover_block)
        self.assertNotEqual(body.viewport().grab().toImage(), plain)
        QApplication.sendEvent(body.viewport(), QEvent(QEvent.Leave))
        self.assertIsNone(body._hover_block)
        previous = theme.mode()
        self.addCleanup(theme.apply, previous)
        for mode in ('light', 'dark'):
            theme.apply(mode)
            toolbar = danmaku_actions.CommentToolbar(panel)
            toolbar.popup(QPoint(80, 80))
            APP.processEvents()
            first = toolbar.copy_button.mapTo(toolbar, QPoint())
            second = toolbar.repeat_button.mapTo(toolbar, QPoint())
            self.assertEqual(first.y(), second.y())
            self.assertLess(first.x(), second.x())
            self.assertEqual(toolbar.grab().toImage().pixelColor(0, 0).alpha(), 0)
            self.assertTrue(toolbar.testAttribute(Qt.WA_TranslucentBackground))
            toolbar.close()
            toolbar.deleteLater()


if __name__ == '__main__':
    unittest.main()
