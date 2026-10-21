"""Offline checks for per-tile D shortcut, compact notices and startup live baseline."""
from contextlib import ExitStack
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock, patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
runpy.run_path(str(ROOT / 'main.py'), run_name='bootstrap')
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import motion, theme
from ddm.app import MainWindow
from ddm.dialogs import ShortcutSettingsPage
from ddm.online_ui import show_result


class MainNoticesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', '_start_avatar_loader',
                       '_check_startup_plugins'):
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
        self.assertLess(short_width, 200)
        self.assertEqual(notice.height(), 48)
        show_result(owner, '主播甲 开播了', rooms=[{'room_id': 'test', 'uname': '主播甲'}], kind='live')
        self.assertGreater(notice.width(), short_width)
        self.assertEqual(notice.timer.interval(), 5000)
        self.assertEqual(len(notice._avatars), 1)
        self.app.processEvents()
        self.assertGreaterEqual(notice.title.width(), notice.title.fontMetrics().horizontalAdvance(notice.title.text()))
        self.assertEqual(notice.height(), 48)
        show_result(owner, '主播甲、主播乙 等 4 位主播开播了',
                    rooms=[{'room_id': str(index), 'uname': '主播'} for index in range(3)], kind='live')
        self.app.processEvents()
        self.assertGreaterEqual(notice.title.width(), notice.title.fontMetrics().horizontalAdvance(notice.title.text()))
        self.assertLessEqual(notice.title.heightForWidth(notice.title.width()), notice.title.fontMetrics().height() + 2)
        show_result(owner, '请先选择录制保存目录，再开始录制。' * 8, kind='warning')
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
