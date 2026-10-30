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
            def repeat_message(self, event):
                sent.append((self.context.room.get('room_id'), event['emoticon_unique'], event['dm_type']))
                return True
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

    def test_emoticon_repeat_keeps_identifier_in_panel_and_video(self):
        tile = self.wall.tiles[0]
        event = {'text': '[表情]', 'dm_type': 1, 'emoticon_unique': 'official_13'}
        controls = tile._plugin_controls
        edit = controls.entries[0].control.widget
        edit.setText('keep draft')
        panel = self.wall.danmaku
        panel.add_event(event)
        with self.choose(0):
            panel._message_clicked(0, QPoint())
        self.assertEqual(APP.clipboard().text(), '[表情]')
        self.assertEqual(self.sent, [])
        with self.choose(1):
            panel._message_clicked(0, QPoint())
        video = tile.video_danmaku
        video.set_native_video(False)
        video.set_enabled(True)
        video.set_active(True)
        with patch.object(video, '_poll_hover'):
            self.assertTrue(video.add_event(event))
            comment = video.comments[0]
            comment.x = 20
            point = QPoint(25, comment.lane * video.lane_height() + 8)
            with self.choose(1):
                self.assertTrue(video.open_actions_at(video.mapToGlobal(point)))
        self.assertEqual(self.sent, [('12', 'official_13', 1)] * 2)
        self.assertEqual(edit.text(), 'keep draft')
        with self.choose(1, lambda _menu: tile.set_room({'room_id': '99'})):
            tile._show_danmaku_actions(event, QPoint())
        self.assertEqual(len(self.sent), 2, 'Room changes must invalidate structured repeats')

    def test_emoticon_never_falls_back_to_text_with_missing_id_or_old_plugin(self):
        controls = self.wall.tiles[0]._plugin_controls
        event = {'text': '[表情]', 'dm_type': 1, 'emoticon_unique': 'official_13'}
        missing = dict(event, emoticon_unique='')
        self.assertFalse(controls.can_repeat(missing))
        self.assertFalse(controls.repeat_message(missing, '12'))
        control = controls.entries[0].control
        with patch.object(type(control), 'repeat_message', plugins.TileControl.repeat_message):
            self.assertFalse(controls.can_repeat(event))
            self.assertFalse(controls.repeat_message(event, '12'))
            with self.choose(0, lambda menu: self.assertFalse(menu.repeat_button.isEnabled())):
                self.wall.tiles[0]._show_danmaku_actions(event, QPoint())
        self.assertEqual(self.sent, [])

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

    def test_outside_click_only_dismisses_toolbar_without_replaying_on_comments(self):
        panel = self.wall.danmaku
        panel.add_message('Viewer', 'first comment')
        panel.add_message('Viewer', 'second comment')
        APP.processEvents()
        body = panel.body
        cursor = body.textCursor()
        cursor.setPosition(0)
        first = body.cursorRect(cursor).center()
        cursor.setPosition(body.document().lastBlock().position())
        second = body.cursorRect(cursor).center()
        targets = (second, QPoint(20, body.viewport().height() - 10))
        for target in targets:
            with self.subTest(target=target):
                opened = []
                replay_blocked = []
                class TrackingToolbar(danmaku_actions.CommentToolbar):
                    def exec(menu, position):
                        opened.append(menu)
                        return super().exec(position + QPoint(150, 100))
                    def closeEvent(menu, event):
                        replay_blocked.append(menu.testAttribute(Qt.WA_NoMouseReplay))
                        super().closeEvent(event)
                APP.clipboard().setText('unchanged')
                fallback = QTimer()
                fallback.setSingleShot(True)
                fallback.timeout.connect(lambda: QApplication.activePopupWidget().reject()
                    if QApplication.activePopupWidget() else None)
                fallback.start(250)
                def click_outside():
                    menu = QApplication.activePopupWidget()
                    point = menu.mapFromGlobal(body.viewport().mapToGlobal(target))
                    QTest.mouseClick(menu.windowHandle(), Qt.LeftButton, pos=point)
                QTimer.singleShot(30, click_outside)
                with patch.object(danmaku_actions, 'CommentToolbar', TrackingToolbar):
                    QTest.mouseClick(body.viewport(), Qt.LeftButton, pos=first)
                closed_by_click = fallback.isActive()
                fallback.stop()
                self.assertTrue(closed_by_click)
                self.assertEqual(replay_blocked, [True])
                self.assertEqual(len(opened), 1)
                self.assertIsNone(opened[0].chosen)
                self.assertIsNone(QApplication.activePopupWidget())
                self.assertEqual(APP.clipboard().text(), 'unchanged')
                self.assertEqual(self.sent, [])
                self.assertFalse(panel._follow_tail)
        with self.choose(0):
            QTest.mouseClick(body.viewport(), Qt.LeftButton, pos=second)
        self.assertEqual(APP.clipboard().text(), 'second comment')

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
        panel.jump_to_bottom()
        with patch.object(danmaku_actions, 'show_comment_menu') as show:
            QTest.mouseClick(body.viewport(), Qt.LeftButton,
                             pos=QPoint(20, body.viewport().height() - 10))
            show.assert_not_called()
        self.assertTrue(panel._follow_tail)

    def test_chat_click_holds_reading_position_until_return_to_bottom(self):
        panel = self.wall.danmaku
        panel.set_max_blocks(80)
        for index in range(80):
            panel.add_message('Viewer', f'comment {index} ' + 'wrapped text ' * (index % 3))
        APP.processEvents()
        body = panel.body
        bar = body.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.assertEqual(bar.value(), bar.maximum())
        # Leave a queued tail correction pending when the user clicks.
        panel.add_message('Viewer', 'pending before click')
        cursor = body.textCursor()
        cursor.setPosition(body.document().lastBlock().position())
        point = body.cursorRect(cursor).center()
        anchor = body.cursorForPosition(QPoint(12, 12))
        anchor_text = anchor.block().text()
        anchor_y = body.cursorRect(anchor).y()

        def incoming(_menu=None):
            for index in range(5):
                panel.add_message('New viewer', f'new comment {index}')
            APP.processEvents()
            current = body.cursorForPosition(QPoint(12, 12))
            self.assertFalse(panel._follow_tail)
            self.assertEqual(current.block().text(), anchor_text)
            self.assertLessEqual(abs(body.cursorRect(current).y() - anchor_y), 1)
            self.assertTrue(body.toPlainText().endswith('new comment 4'))
            self.assertTrue(panel.bottom_button.isVisible())

        with self.choose(0, incoming):
            QTest.mouseClick(body.viewport(), Qt.LeftButton, pos=point)
        incoming()  # Closing the action toolbar must not resume following.
        self.assertEqual(len(panel._blocks), body.document().blockCount())
        panel.bottom_button.click()
        panel.add_message('Viewer', 'follow again')
        APP.processEvents()
        self.assertTrue(panel._follow_tail)
        self.assertEqual(bar.value(), bar.maximum())
        self.assertTrue(panel.bottom_button.isHidden())

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
            self.assertEqual(received, [{'text': '  original   text  '}])
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
