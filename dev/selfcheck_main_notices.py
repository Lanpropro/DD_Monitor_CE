"""Offline checks for per-tile D shortcut, compact notices and startup live baseline."""
from contextlib import ExitStack
import os
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import Mock, patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
runpy.run_path(str(ROOT / 'main.py'), run_name='bootstrap')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QKeySequence, QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QWidget
from ddm import motion, theme
from ddm.app import MainWindow
from ddm.dialogs import ShortcutSettingsPage
from ddm.online_ui import show_result, UpdateNotice


class MainNoticesTests(unittest.TestCase):
    def test_toasts_anchor_on_the_left_and_stack_down(self):
        window = self.window([])
        window.resize(1200, 800)
        update = UpdateNotice(window)
        update.show_offer({'version': 'test'}, persistent=True)
        show_result(window, '左侧通知', persistent=True)
        result = window._result_notice
        for side in ('left', 'top', 'left'):
            window.sidebar.set_side(side)
            for collapsed in (False, True):
                window.sidebar.set_collapsed(collapsed, animate=False)
                self.app.processEvents()
                for card in (update, result):
                    expected = 16
                    expected = max(0, min(expected, window.width() - card.width() - 16))
                    self.assertEqual(card.x(), window.mapToGlobal(QPoint(expected, 0)).x())
                self.assertGreater(result.y(), update.geometry().bottom())

    def test_notice_history_collects_results_and_update_once(self):
        window = self.window([{'room_id': '1001', 'uname': '主播甲'}])
        center = window.sidebar.notification_button.center
        window._show_notice('主播甲开播了', rooms=[{'room_id': '1001'}], kind='live')
        window._record_notice('录制已完成')
        self.assertEqual([entry.message for entry in center.entries], ['主播甲开播了', '录制已完成'])
        with patch.object(window, '_unread_app_update', return_value={'version': '0.5'}), \
                patch.object(window, '_unread_plugin_updates', return_value=[]), \
                patch.object(window, 'open_settings') as settings:
            window._show_update_notice()
            window._show_update_notice()
            self.assertEqual(len(center.entries), 3)
            self.assertEqual(center.entries[-1].message, '软件有新版 v0.5')
            center.entries[-1].callback()
            settings.assert_called_once_with('updates')

    def test_single_line_notice_keeps_heading_message_and_action_visible(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        from ddm.online_ui import ResultNotice
        notice = ResultNotice(owner)
        notice.title.setWordWrap(False)
        notice.show_message('已保存录制：example.mp4', on_click=Mock())
        self.assertEqual(notice.text_column.layout().geometry().width(), notice.text_column.width())
        self.app.processEvents()
        self.assertGreaterEqual(notice.category.height(), notice.category.fontMetrics().height())
        self.assertGreaterEqual(notice.title.height(), notice.title.fontMetrics().height())
        self.assertGreater(notice.action.y(), notice.text_column.geometry().bottom())
        self.assertGreaterEqual(notice.height(), notice.layout().totalSizeHint().height())
    def test_recording_file_notices_shorten_paths_and_reflow_on_resize(self):
        room = {'room_id': '1001', 'uname': '主播甲'}
        window = self.window([room])
        filename = '主播甲_' + '很长的录像文件名_' * 18 + '20261020_120000_part002.mp4'
        path = str(Path(tempfile.gettempdir()) / ('深层目录' * 25) / filename)
        for prefix in ('已保存录制', '已保存即时回放', '正在导出录制', '正在导出即时回放'):
            window.recorder._say(prefix + '：' + path, room)
            notice = window._result_notice
            self.assertEqual(notice._file_path, path)
            entry = window.sidebar.notification_button.center.entries[-1]
            self.assertIn(path, entry.message)
            with patch('ddm.notification_center.reveal_file') as reveal:
                entry.callback()
                reveal.assert_called_once_with(path)
            self.assertIn('1001', notice._avatars)
            self.assertNotIn(str(Path(path).parent), notice.title.text())
            self.assertIn('…', notice.title.text())
            self.assertTrue(notice.title.text().endswith('.mp4'))
            self.assertIn(path, notice.toolTip())
            self.assertFalse(notice.title.wordWrap())
            self.assertGreaterEqual(notice.category.height(), notice.category.fontMetrics().height())
            self.assertGreaterEqual(notice.title.height(), notice.title.fontMetrics().height())
            self.assertEqual(notice.action.text(), '打开文件位置')
            self.assertGreaterEqual(notice.height(), 76)
            for width in (320, 1000):
                window.resize(width, 700)
                self.app.processEvents()
                self.assertLessEqual(notice.width(), min(480, window.width() - 32))
                self.assertGreaterEqual(notice.height(), 76)
                self.assertLessEqual(notice.title.fontMetrics().horizontalAdvance(notice.title.text()),
                                     notice.title.width())
            notice.dismiss(animate=False)
        window.recorder._say('已保存录制：' + str(Path(tempfile.gettempdir()) / 'short.mp4'), room)
        self.assertEqual(window._result_notice.title.text(), '已保存录制：short.mp4')
        window.recorder._say('导出失败；原始分段仍保留在 .ddm-parts：错误目录', room)
        self.assertEqual(window._result_notice._file_path, '')
        self.assertIn('错误目录', window._result_notice.title.text())

    def test_recording_file_click_and_context_copy_use_full_path(self):
        window = self.window([{'room_id': '1001', 'uname': '主播甲'}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '中文 name, & test.mp4'
            path.touch()
            window.recorder._say('已保存录制：' + str(path), {'room_id': '1001'})
            notice = window._result_notice
            with patch('ddm.online_ui.subprocess.Popen') as reveal, \
                    patch('ddm.online_ui.sys.platform', 'win32'), \
                    patch.object(window, '_open_room_browser') as browser:
                QTest.mouseClick(notice.title, Qt.LeftButton)
                reveal.assert_called_once_with(['explorer.exe', '/select,', str(path)])
                browser.assert_not_called()
                self.assertFalse(notice.isVisible())
            window.recorder._say('已保存录制：' + str(path), {'room_id': '1001'})
            notice = window._result_notice
            original_clipboard = self.app.clipboard().text()
            self.addCleanup(self.app.clipboard().setText, original_clipboard)
            def select_copy(menu, point):
                actions = menu.actions()
                self.assertEqual([action.text() for action in actions], ['打开文件位置', '复制完整路径'])
                actions[1].trigger()
            menu = QMenu(notice)
            with patch('ddm.online_ui.QMenu', return_value=menu), \
                    patch.object(menu, 'exec', side_effect=lambda point: select_copy(menu, point)) as context:
                point = notice.rect().center()
                event = QContextMenuEvent(QContextMenuEvent.Mouse, point, notice.mapToGlobal(point))
                self.assertTrue(notice.isEnabled())
                self.assertEqual(notice.contextMenuPolicy(), Qt.DefaultContextMenu)
                self.assertEqual(notice._file_path, str(path))
                self.app.sendEvent(notice, event)
                context.assert_called_once()
            self.assertEqual(self.app.clipboard().text(), str(path))
            self.assertTrue(notice.isVisible())
            self.assertTrue(notice.timer.isActive())
            path.unlink()
            with patch('ddm.online_ui.QDesktopServices.openUrl', return_value=True) as folder:
                notice._open_file_location()
                self.assertEqual(Path(folder.call_args.args[0].toLocalFile()), path.parent)

    def test_recording_and_send_notices_include_room_and_update_all_avatars(self):
        room = {'room_id': '1001', 'uname': '主播甲'}
        window = self.window([room])
        window.recorder._say('主播甲 开始录制', room)
        recording = window._result_notice
        self.assertIn('1001', recording._avatars)
        window.wall.tiles[0].composer.noticeRequested.emit('发送失败', False)
        sending = window._result_notice
        self.assertIn('1001', sending._avatars)
        with patch.object(recording, 'set_room_avatar') as first, \
                patch.object(sending, 'set_room_avatar') as second:
            pixmap = QPixmap(32, 32)
            pixmap.fill(QColor('#00a1d6'))
            window._on_room_avatar('1001', pixmap)
            first.assert_called_once_with('1001', pixmap)
            second.assert_called_once_with('1001', pixmap)

    def test_notification_settings_defaults_save_and_reset(self):
        from ddm.dialogs import SettingsDialog
        from ddm.config import DEFAULT_SETTINGS
        dialog = SettingsDialog(DEFAULT_SETTINGS, {}, preview=True)
        self.addCleanup(dialog.close)
        page = dialog.notification_page
        self.assertTrue(page.values()['notice_persist_updates'])
        self.assertTrue(page.values()['notice_persist_pinned_live'])
        self.assertFalse(page.values()['notice_persist_live'])
        page._checks['notice_persist_warning'].setChecked(True)
        page._checks['live_alert'].setChecked(False)
        self.assertTrue(dialog.settings()['notice_persist_warning'])
        self.assertFalse(dialog.settings()['live_alert'])
        page.reset()
        self.assertFalse(page.values()['notice_persist_warning'])
        self.assertTrue(page.values()['live_alert'])

    def test_notifications_stack_reflow_close_and_jump_independently(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        activated = Mock()
        update = UpdateNotice(owner)
        update.activated.connect(activated)
        update.show_offer({'version': 'test'}, persistent=True)
        show_result(owner, '持续提示', persistent=True, on_click=activated)
        first = owner._result_notice
        show_result(owner, '普通提示')
        second = owner._result_notice
        self.app.processEvents()
        self.assertEqual(len(owner._notices), 3)
        self.assertFalse(update.timer.isActive())
        self.assertFalse(first.timer.isActive())
        self.assertTrue(second.timer.isActive())
        self.assertGreater(first.y(), update.y() + update.height())
        self.assertGreater(second.y(), first.y() + first.height())
        before = second.y()
        first.findChild(QPushButton, 'NoticeClose').click()
        self.assertLess(second.y(), before)
        activated.assert_not_called()
        self.assertTrue(second.isVisible())
        QTest.mouseClick(update.title, Qt.LeftButton)
        activated.assert_called_once()
        self.assertEqual(len(owner._notices), 1)

    def test_pinned_live_policy_and_room_navigation(self):
        window = self.window([{'room_id': '1001', 'uname': '主播甲', 'live': False},
                              {'room_id': '1002', 'uname': '主播乙', 'live': False}])
        window.sidebar.apply_pins(['1001'])
        for tile in window.wall.tiles:
            tile.set_room(None)
        window.start_tile.reset_mock()
        with patch.object(window, '_open_room_browser') as browser:
            window._show_notice('甲开播了', rooms=[{'room_id': '1001'}], kind='live')
            notice = window._result_notice
            self.assertFalse(notice.timer.isActive())
            QTest.mouseClick(notice.title, Qt.LeftButton)
            browser.assert_not_called()
            self.assertIsNotNone(window._tile_of('1001'))
            window.start_tile.assert_called_once()
        window._show_notice('乙开播了', rooms=[{'room_id': '1002'}], kind='live')
        self.assertTrue(window._result_notice.timer.isActive())
        window.settings['notice_persist_warning'] = True
        window._show_notice('警告', kind='warning')
        self.assertFalse(window._result_notice.timer.isActive())

    def test_live_notice_dismisses_without_expanding_or_replacing_full_wall(self):
        window = self.window([{'room_id': str(index), 'live': False} for index in range(1, 5)])
        original = [dict(tile.room) for tile in window.wall.tiles]
        with patch.object(window.wall, 'add_room') as add, \
                patch.object(window, '_open_room_browser') as browser:
            window._show_notice('新主播开播了', rooms=[{'room_id': '999'}], kind='live')
            notice = window._result_notice
            QTest.mouseClick(notice.title, Qt.LeftButton)
            self.assertFalse(notice.isVisible())
            self.assertEqual([tile.room for tile in window.wall.tiles], original)
            add.assert_not_called()
            browser.assert_not_called()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', '_start_avatar_loader'):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.stack.enter_context(patch('ddm.images.load_room_avatar', return_value=None))
        self.stack.enter_context(patch('ddm.images.load_cached_avatar', return_value=None))

    def window(self, rooms):
        window = MainWindow([dict(room) for room in rooms], [dict(room) for room in rooms],
                            layout_id='2x2', state={'plugins_enabled': []})
        window.resize(1000, 700)
        window.show()
        self.app.processEvents()
        self.addCleanup(window.close)
        return window

    def status(self, live, **values):
        return dict(live=live, viewers='', title='', uname='', face='', **values)

    def complete_startup(self, window):
        poller = Mock()
        window._poller = poller
        window._on_poller_finished(poller)
        self.assertTrue(window._startup_status_complete)

    def test_b_targets_one_tile_remaps_and_preserves_typing(self):
        window = self.window([{'room_id': '1001'}, {'room_id': '1001'}])
        first, second = window.wall.tiles[:2]
        cursor = self.stack.enter_context(patch.object(window, '_tile_under_cursor', return_value=second))
        self.assertEqual(window.shortcuts['video_danmaku'], 'B')
        QTest.keyClick(window, Qt.Key_B)
        self.assertTrue(second.danmaku_button.isChecked())
        self.assertFalse(first.danmaku_button.isChecked())
        self.assertTrue(window.current_state()['wall'][1]['video_danmaku_enabled'])
        QTest.keyClick(window, Qt.Key_B)
        self.assertFalse(second.danmaku_button.isChecked())
        page = ShortcutSettingsPage(window.shortcuts)
        page._edits['video_danmaku'].setKeySequence(QKeySequence('R'))
        window.shortcuts = page.values()
        QTest.keyClick(window, Qt.Key_B)
        self.assertFalse(second.danmaku_button.isChecked())
        QTest.keyClick(window, Qt.Key_R)
        self.assertTrue(second.danmaku_button.isChecked())
        page.reset()
        window.shortcuts = page.values()
        self.assertEqual(window.shortcuts['video_danmaku'], 'B')
        window.sidebar.search.clear()
        QTest.keyClick(window.sidebar.search, Qt.Key_B)
        self.assertEqual(window.sidebar.search.text(), 'b')
        self.assertTrue(second.danmaku_button.isChecked())
        for target in (None, window.wall.tiles[2]):
            cursor.return_value = target
            QTest.keyClick(window, Qt.Key_B)
        self.assertFalse(first.danmaku_button.isChecked())
        window.sync_danmaku.assert_called()

    def test_delete_closes_only_hovered_tile_and_keeps_empty_slot(self):
        window = self.window([{'room_id': '1001'}, {'room_id': '1001'}])
        first, second = window.wall.tiles[:2]
        original_tiles = list(window.wall.tiles)
        with patch.object(window, '_tile_under_cursor', return_value=second), \
                patch.object(window.recorder, 'stop', wraps=window.recorder.stop) as stop:
            self.assertEqual(window.shortcuts['close_tile'], 'Del')
            QTest.keyClick(window, Qt.Key_Delete)
            self.assertEqual(first.room['room_id'], '1001')
            self.assertFalse(second.room.get('room_id'))
            self.assertEqual(window.wall.tiles, original_tiles)
            stop.assert_called_once_with(second)
            self.assertFalse(window.current_state()['wall'][1].get('room_id'))
            QTest.keyClick(window, Qt.Key_Delete)
            self.assertEqual(stop.call_count, 1)
        with patch.object(window, '_tile_under_cursor', return_value=None), \
                patch.object(window, '_clear_tile_room') as clear:
            QTest.keyClick(window, Qt.Key_Delete)
            clear.assert_not_called()

    def test_delete_preserves_search_and_composer_editing(self):
        window = self.window([{'room_id': '1001'}])
        tile = window.wall.tiles[0]
        with patch.object(window, '_tile_under_cursor', return_value=tile), \
                patch.object(window, '_clear_tile_room') as clear:
            for edit in (window.sidebar.search, tile.composer.edit):
                edit.setText('abc')
                edit.setCursorPosition(0)
                edit.setFocus()
                self.app.processEvents()
                QTest.keyClick(edit, Qt.Key_Delete)
                self.assertEqual(edit.text(), 'bc')
                clear.assert_not_called()
                edit.clear()

    def test_close_shortcut_can_be_remapped_saved_and_reset(self):
        window = self.window([{'room_id': '1001'}])
        page = ShortcutSettingsPage(window.shortcuts)
        self.addCleanup(page.close)
        page._edits['close_tile'].setKeySequence(QKeySequence('Ctrl+K'))
        window.shortcuts = page.values()
        window._refresh_shortcuts()
        tile = window.wall.tiles[0]
        with patch.object(window, '_tile_under_cursor', return_value=tile):
            QTest.keyClick(window, Qt.Key_Delete)
            self.assertEqual(tile.room['room_id'], '1001')
            QTest.keyClick(window, Qt.Key_K, Qt.ControlModifier)
            self.assertFalse(tile.room.get('room_id'))
        self.assertEqual(window.current_state()['ui']['shortcuts']['close_tile'], 'Ctrl+K')
        page.reset()
        self.assertEqual(page.values()['close_tile'], 'Del')

    def test_send_auth_notice_opens_login_and_normal_notice_clears_action(self):
        from ddm import bili
        window = self.window([{'room_id': '1001'}])
        composer = window.wall.tiles[0].composer
        for session in ('', 'existing-session'):
            with patch.object(bili, 'SESSION_DATA', session), patch.object(bili, 'BILI_JCT', ''), \
                    patch.object(window, 'open_login') as login, patch.object(bili, 'send_danmaku') as send:
                composer.edit.setText('test')
                composer.send_text()
                self.app.processEvents()
                notice = window._result_notice
                self.assertIn('登录', notice.title.text())
                self.assertTrue(composer.feedback.isHidden())
                self.assertFalse(composer.feedback.isWindow())
                self.assertEqual(composer.edit.toolTip(), '')
                QTest.mouseClick(notice.title, Qt.LeftButton)
                login.assert_called_once_with('bilibili', reauthenticate=True)
                send.assert_not_called()
                window._show_notice('普通提示')
                notice = window._result_notice
                QTest.mouseClick(notice.title, Qt.LeftButton)
                self.assertEqual(login.call_count, 1)

    def test_reauthentication_opens_login_without_discarding_existing_cookies(self):
        from ddm import bili
        from ddm.account_dialog import AccountPlatformDialog
        from ddm.login import LoginWindow
        window = self.window([])
        with patch.object(bili, 'SESSION_DATA', 'existing-session'), \
                patch.object(LoginWindow, 'start_login'):
            dialog = AccountPlatformDialog(window, {}, reauthenticate=True)
            try:
                self.assertIsInstance(dialog.page, LoginWindow)
                self.assertEqual(bili.SESSION_DATA, 'existing-session')
            finally:
                dialog.reject()

    def test_notice_width_wrap_and_warning_feedback(self):
        owner = QWidget()
        owner.resize(1000, 600)
        owner.show()
        self.addCleanup(owner.close)
        show_result(owner, '完成')
        notice = owner._result_notice
        self.app.processEvents()
        short_width = notice.width()
        self.assertEqual(short_width, 420)
        self.assertGreaterEqual(notice.height(), 76)
        show_result(owner, '主播甲 开播了', rooms=[{'room_id': 'test', 'uname': '主播甲'}], kind='live')
        notice = owner._result_notice
        self.assertEqual(notice.width(), short_width)
        self.assertEqual(notice.timer.interval(), 5000)
        self.assertEqual(len(notice._avatars), 1)
        self.app.processEvents()
        self.assertGreaterEqual(notice.title.width(), notice.title.fontMetrics().horizontalAdvance(notice.title.text()))
        self.assertGreaterEqual(notice.height(), 76)
        show_result(owner, '主播甲、主播乙 等 4 位主播开播了',
                    rooms=[{'room_id': str(index), 'uname': '主播'} for index in range(3)], kind='live')
        notice = owner._result_notice
        self.app.processEvents()
        self.assertGreaterEqual(notice.title.height(),
                                notice.title.heightForWidth(notice.title.width()))
        show_result(owner, '请先选择录制保存目录，再开始录制。' * 8, kind='warning')
        notice = owner._result_notice
        self.app.processEvents()
        self.assertLessEqual(notice.width(), 480)
        self.assertGreater(notice.height(), 48)
        self.assertEqual(notice.timer.interval(), 6000)
        self.assertFalse(notice._avatars)
        owner.resize(240, 600)
        self.app.processEvents()
        self.assertLessEqual(notice.width(), 208)
        owner.hide()
        self.assertFalse(notice.isVisible())
        self.assertFalse(notice.timer.isActive())

    def test_card_actions_and_close_do_not_duplicate_navigation(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        for kind, text, label in (('live', '主播开播了', '放入画面墙'),
                                  ('warning', '请重新登录', '前往登录'),
                                  ('info', '操作完成', '查看详情')):
            callback = Mock()
            show_result(owner, text, kind=kind, on_click=callback, persistent=True)
            notice = owner._result_notice
            self.app.processEvents()
            self.assertTrue(notice.action.isVisible())
            self.assertEqual(notice.action.text(), label)
            self.assertGreater(notice.action.y(), notice.text_column.geometry().bottom())
            self.assertGreater(notice.action.x(), notice.width() // 2)
            self.assertEqual(notice.findChild(QPushButton, 'NoticeClose').y(), 14)
            QTest.mouseClick(notice.action, Qt.LeftButton)
            callback.assert_called_once_with()
            self.assertFalse(notice.isVisible())
        show_result(owner, '普通提示')
        self.assertTrue(owner._result_notice.action.isHidden())
        self.assertEqual(owner._result_notice.category.text(), '操作提示')

    def test_cards_follow_theme_and_resize_without_clipping(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        self.addCleanup(theme.apply, theme._mode)
        update = UpdateNotice(owner)
        update.show_offer({'version': '0.5'}, persistent=True)
        show_result(owner, '需要检查的说明。' * 12, kind='warning', on_click=Mock())
        notice = owner._result_notice
        for mode in ('light', 'dark'):
            theme.apply(mode)
            self.app.processEvents()
            for card in (update, notice):
                rendered = card.grab().toImage()
                self.assertEqual(rendered.pixelColor(4, card.height() // 2).name(),
                                 theme.qcolor(theme.ELEVATED).name())
                self.assertEqual(rendered.pixelColor(0, 0).alpha(), 0)
                scale = rendered.devicePixelRatio()
                x, y = card.action.x(), card.action.y()
                corner = rendered.pixelColor(round(x * scale), round(y * scale))
                self.assertEqual(corner.name(), theme.qcolor(theme.ELEVATED).name())
                self.assertNotEqual(corner, rendered.pixelColor(
                    round((x + card.action.width() // 2) * scale), round((y + 1) * scale)))
            for width in (240, 800):
                owner.resize(width, 700)
                self.app.processEvents()
                for card in (update, notice):
                    self.assertLessEqual(card.width(), width - 32)
                    self.assertEqual(card.x(), owner.mapToGlobal(owner.rect().topLeft()).x()
                                     + 16)
                    self.assertGreaterEqual(card.title.height(),
                                            card.title.heightForWidth(card.title.width()))
                    self.assertLess(card.action.geometry().bottom(), card.height())
                self.assertGreater(notice.y(), update.geometry().bottom())

    def test_startup_all_platform_batches_and_shared_room_are_silent(self):
        rooms = [{'room_id': '1001', 'live': False, 'live_known': False},
                 {'room_id': 'douyu:1002', 'live': False, 'live_known': True}]
        window = self.window(rooms)
        window.wall.tiles[0].room = window.sidebar._items[0].room
        with patch.object(window, '_show_notice') as notice, patch.object(window.sidebar, 'play_live_alerts') as alerts:
            window._on_status_updated({'1001': self.status(True)})
            window._on_status_updated({'douyu:1002': self.status(True)})
            notice.assert_not_called()
            alerts.assert_not_called()
            self.complete_startup(window)
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_not_called()
            window._on_status_updated({'1001': self.status(False)})
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_called_once()
            alerts.assert_called_once()
            self.assertEqual(notice.call_args.kwargs['kind'], 'live')
            window._on_status_updated({'1001': self.status(True)})
            self.assertEqual(notice.call_count, 1)

    def test_unknown_recovery_and_disabled_live_alert_are_silent(self):
        window = self.window([{'room_id': '1001', 'live': False, 'live_known': False}])
        self.complete_startup(window)
        with patch.object(window, '_show_notice') as notice:
            window._on_status_updated({'1001': self.status(False, live_known=False)})
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_not_called()
            window._on_status_updated({'1001': self.status(False)})
            window.settings['live_alert'] = False
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_not_called()

    def test_large_startup_snapshot_and_enrichment_do_not_notify(self):
        window = self.window([{'room_id': str(index), 'live': False, 'live_known': False}
                              for index in range(1001, 1061)])
        with patch.object(window, '_show_notice') as notice, patch.object(window.sidebar, 'play_live_alerts') as alerts:
            first = {str(index): self.status(True) for index in range(1001, 1031)}
            second = {str(index): self.status(True) for index in range(1031, 1061)}
            window._on_status_updated(first)
            window._on_status_updated(second)
            window._on_status_updated({**first, **second})
            self.complete_startup(window)
            window._on_status_updated({**first, **second})
            notice.assert_not_called()
            alerts.assert_not_called()
            self.assertTrue(all(item.room['live'] for item in window.sidebar._items))

    def test_batch_live_message_and_recording_use_main_notice(self):
        window = self.window([{'room_id': str(index), 'uname': '主播' + str(index),
                               'live': False, 'live_known': True} for index in range(1, 5)])
        self.complete_startup(window)
        with patch.object(window, '_show_notice') as notice:
            window._on_status_updated({str(index): self.status(True) for index in range(1, 5)})
            notice.assert_called_once()
            self.assertIn('等 4 位主播开播了', notice.call_args.args[0])
            self.assertEqual(len(notice.call_args.kwargs['rooms']), 4)
        window._record_notice('请先选择录制保存目录')
        self.assertEqual(window._result_notice.title.text(), '请先选择录制保存目录')
        self.assertEqual(window._result_notice.timer.interval(), 6000)
        window._closing = True
        with patch('ddm.online_ui.show_result') as result:
            window._record_notice('录制已完成')
            result.assert_not_called()
        window._closing = False


if __name__ == '__main__':
    unittest.main()
