"""Host-wide comment/user blocking, quick actions and persistence; isolated data only."""
import os
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, config, danmaku_actions, plugins
from ddm.danmaku_filter import event_blocked, normalize_users, user_identity
from ddm.settings_danmaku import DanmakuSettingsPage
from dev.selfcheck_tile_fullscreen import SilentPoller

APP = QApplication.instance() or QApplication([])


class FilterTests(unittest.TestCase):
    def test_bilibili_adapter_keeps_sender_id(self):
        from ddm.danmaku import _Handler
        events = []
        _Handler(events.append)._on_danmaku(SimpleNamespace(uid=0),
            SimpleNamespace(uid=1234567890123, uname='User', msg='text', dm_type=0))
        self.assertEqual(events[0]['uid'], '1234567890123')

    def test_platform_ids_are_independent_and_uid_survives_rename(self):
        settings = {'danmaku_blocked_users': [{'platform': 'douyin', 'uid': '42', 'uname': '旧名字'}]}
        self.assertTrue(event_blocked({'uid': 42, 'uname': '新名字'}, 'douyin:other-room', settings))
        for event, room in (({'uid': '43', 'uname': '旧名字'}, 'douyin:1'),
                            ({'uid': '42', 'uname': '旧名字'}, 'huya:1'),
                            ({'uid': '42'}, '1001'), ({}, 'douyin:1')):
            self.assertFalse(event_blocked(event, room, settings))
        self.assertEqual(user_identity({'uid': 'UCabc'}, 'youtube:live')['uid'], 'UCabc')
        self.assertEqual(user_identity({'uid': 42}, '1001')['platform'], 'bilibili')

    def test_normalization_nickname_fallback_and_control_messages(self):
        users = normalize_users([None, {}, {'uid': '42'},
            {'platform': 'twitch', 'uid': 42, 'uname': 'User'},
            {'platform': 'twitch', 'uid': '42', 'uname': 'Renamed'},
            {'platform': 'huya', 'uid': 0, 'uname': '昵称'}])
        self.assertEqual(len(users), 2)
        settings = {'danmaku_blocked_users': users, 'danmaku_block_words': [' 广告 ', 'HELLO', '']}
        self.assertTrue(event_blocked({'uname': '昵称'}, 'huya:2', settings))
        self.assertFalse(event_blocked({'uname': '昵称'}, 'douyu:2', settings))
        self.assertTrue(event_blocked({'text': 'say hello'}, 'twitch:x', settings))
        self.assertFalse(event_blocked({'kind': 'super_chat', 'text': '广告'}, '1', settings))
        self.assertTrue(event_blocked({'kind': 'super_chat', 'uid': '42'}, 'twitch:x', settings))
        self.assertFalse(event_blocked({'kind': 'super_chat_delete', 'uid': '42'}, 'twitch:x', settings))


class BlockingTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        root = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(config, 'REPO', root))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(root) / 'config.json')))
        self.stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(root) / 'plugins')))
        self.stack.enter_context(patch.object(app_module, 'StatusPoller', SilentPoller))
        self.stack.enter_context(patch.object(app_module, 'StatsPoller', SilentPoller))
        self.stack.enter_context(patch('ddm.app.QTimer.singleShot', lambda *args: None))
        self.stack.enter_context(patch.object(app_module.MainWindow, 'sync_danmaku'))
        self.window = app_module.MainWindow([], [], layout_id='dm_main2', state={
            'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit',
                                               'preview_on_hover': False}})
        self.window.resize(1400, 800)
        self.window.show()
        APP.processEvents()
        self.emitted = self.stack.enter_context(patch.object(self.window.plugins, 'emit'))

    def tearDown(self):
        self.window._danmaku_clients.clear()  # Routing sentinels are not worker threads.
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def route(self, room_id, event):
        source = object()
        self.window._danmaku_clients = {room_id: source}
        self.window.wall.tiles[0].room = {'room_id': room_id}
        self.window.wall.danmaku._linked_room_id = room_id
        self.window._on_danmaku_message(source, event)

    def quick_action(self, index):
        parent = self.window.wall.danmaku
        class Choose(danmaku_actions.CommentToolbar):
            def popup(menu, position):
                menu.command_actions[index].trigger()
        with patch.object(danmaku_actions, 'CommentToolbar', Choose), \
                patch.object(danmaku_actions.QToolTip, 'showText'):
            parent._message_clicked(len(parent._blocks) - 1, QPoint())

    def test_all_platforms_filter_before_display_and_plugin_dispatch(self):
        for platform in ('bilibili', 'douyin', 'douyu', 'huya', 'twitch', 'youtube', 'custom'):
            with self.subTest(platform=platform):
                room = '1001' if platform == 'bilibili' else platform + ':room'
                self.window.settings['danmaku_blocked_users'] = [{'platform': platform, 'uid': '42'}]
                self.emitted.reset_mock()
                panel = self.window.wall.danmaku
                before = len(panel._blocks)
                self.route(room, {'kind': 'danmaku', 'uid': '42', 'uname': '被屏蔽', 'text': 'blocked'})
                self.assertEqual(len(panel._blocks), before)
                self.emitted.assert_not_called()
                self.route(room, {'kind': 'danmaku', 'uid': '43', 'uname': '被屏蔽', 'text': 'allowed'})
                self.assertEqual(len(panel._blocks), before + 1)
                self.assertEqual(panel._blocks[-1]['uid'], '43')
                self.assertEqual(panel._blocks[-1]['platform'], platform)
                self.assertEqual(self.emitted.call_count, 1)

    def test_left_click_user_block_retains_identity_and_removes_existing_messages(self):
        self.route('douyin:one', {'uid': '42', 'uname': '用户', 'text': 'first'})
        self.quick_action(3)
        rule = self.window.settings['danmaku_blocked_users'][0]
        self.assertEqual(rule, {'platform': 'douyin', 'uid': '42', 'uname': '用户'})
        self.assertFalse(self.window.wall.danmaku._blocks)
        self.route('douyin:two', {'uid': '42', 'uname': '已改名', 'text': 'second'})
        self.assertFalse(self.window.wall.danmaku._blocks)
        self.route('huya:one', {'uid': '42', 'uname': '用户', 'text': 'other platform'})
        self.assertEqual(len(self.window.wall.danmaku._blocks), 1)
        self.assertTrue(self.window._save_timer.isActive())

    def test_left_click_body_blocks_words_globally_and_deduplicates(self):
        self.route('1001', {'uid': '42', 'text': '这条 广告 hello'})
        self.quick_action(2)
        self.assertEqual(self.window.settings['danmaku_block_words'], ['这条 广告 hello'])
        self.assertFalse(self.window.wall.danmaku._blocks)
        self.window.danmaku_blocking.block({'text': '这条 广告 HELLO'}, '1001')
        self.assertEqual(len(self.window.settings['danmaku_block_words']), 1)
        self.emitted.reset_mock()
        self.route('twitch:test', {'uid': '43', 'text': '说：这条 广告 HELLO'})
        self.emitted.assert_not_called()
        self.window.danmaku_blocking.block({'text': '两行\n弹幕'}, '1001')
        self.assertEqual(self.window.settings['danmaku_block_words'][-1], '两行 弹幕')
        self.assertTrue(event_blocked({'text': '两行\r\n弹幕'}, 'youtube:test', self.window.settings))

    def test_pending_raster_and_super_chat_are_filtered_without_stopping_playback(self):
        tile = self.window.wall.tiles[0]
        tile.room = {'room_id': '1001'}
        video = tile.video_danmaku
        token, event = object(), {'uid': '42', 'text': 'pending'}
        video._pending_comments[token] = ('pending', '#ffffff', [('pending', '')], False, event)
        self.route('1001', {'kind': 'super_chat', 'id': 'sc-1', 'uid': '42', 'uname': 'User',
                            'message': 'SC', 'price': 30, 'time': 60})
        self.assertTrue(self.window.wall.danmaku.super_chats._events)
        with patch.object(self.window, 'start_tile') as start:
            self.window.danmaku_blocking.block(event, '1001', user=True)
            start.assert_not_called()
        self.assertNotIn(token, video._pending_comments)
        self.assertFalse(self.window.wall.danmaku.super_chats._events)
        self.route('1001', {'kind': 'super_chat_delete', 'ids': ['sc-1']})
        self.assertFalse(self.window._super_chats['1001'].active())

    def test_video_action_and_explicit_nickname_fallback(self):
        tile = self.window.wall.tiles[0]
        event = {'platform': 'youtube', 'room_id': 'youtube:live', 'uid': 'UCfixture', 'text': 'video'}
        class Choose(danmaku_actions.CommentToolbar):
            def popup(menu, position):
                menu.command_actions[3].trigger()
        with patch.object(danmaku_actions, 'CommentToolbar', Choose), \
                patch.object(danmaku_actions.QToolTip, 'showText'):
            tile._show_danmaku_actions(event, QPoint())
        self.assertEqual(self.window.settings['danmaku_blocked_users'][0]['uid'], 'UCfixture')
        self.route('huya:one', {'uname': '无ID昵称', 'text': 'fallback'})
        self.quick_action(3)
        self.assertEqual(self.window.settings['danmaku_blocked_users'][-1]['uid'], '')
        self.route('huya:two', {'uname': '无ID昵称', 'text': 'blocked'})
        self.assertFalse(self.window.wall.danmaku._blocks)
        menu = danmaku_actions.show_comment_menu(self.window.wall.danmaku, {'text': ''}, None, QPoint())
        try:
            self.assertFalse(menu.block_action.isEnabled())
            self.assertFalse(menu.block_user_action.isEnabled())
            self.assertIn('昵称', menu.block_user_button.toolTip())
        finally:
            menu.reject()

    def test_settings_add_remove_autosave_and_temporary_disk_persistence(self):
        dialog = self.window._create_settings_dialog()
        try:
            dialog.show()
            dialog.nav.setCurrentRow(2)
            APP.processEvents()
            page = dialog._loaded_pages[2]
            editor = page.blocked_users
            editor.platform.setCurrentIndex(editor.platform.findData('youtube'))
            editor.uid.setText('UCfixture')
            editor.add.click()
            dialog.auto_save.flush()
            self.assertEqual(self.window.settings['danmaku_blocked_users'][0]['uid'], 'UCfixture')
            self.assertFalse(editor.list.item(0).icon().isNull())
            editor.set_users([{'platform': 'youtube', 'uid': str(index)} for index in range(20)])
            self.assertGreater(editor.list.verticalScrollBar().maximum(), 0)
            editor.set_users([{'platform': 'youtube', 'uid': 'UCfixture'}])
            with patch.dict(os.environ):
                os.environ.pop('DDM_NO_SAVE', None)
                config.save(self.window.current_state(), raise_errors=True)
                saved = config.load()['settings']
            reopened = DanmakuSettingsPage(saved)
            self.assertEqual(reopened.blocked_users.users(), editor.users())
            reopened.deleteLater()
            editor.list.setCurrentRow(0)
            editor.remove.click()
            dialog.auto_save.flush()
            self.assertEqual(self.window.settings['danmaku_blocked_users'], [])
            page.block_edit.setPlainText('fixture')
            dialog.auto_save.flush()
            self.assertEqual(self.window.settings['danmaku_block_words'], ['fixture'])
            page.reset()
            dialog.auto_save.flush()
            self.assertEqual(self.window.settings['danmaku_block_words'], [])
        finally:
            dialog.auto_save.stop()
            dialog.close()
            dialog.deleteLater()

    def test_menu_updates_loaded_and_lazy_settings_without_restoring_old_rules(self):
        dialog = self.window._create_settings_dialog()
        try:
            dialog.show()
            self.assertNotIn(2, dialog._loaded_pages)
            self.window.danmaku_blocking.block({'uid': '42', 'uname': 'User'}, 'huya:1', user=True)
            dialog.nav.setCurrentRow(2)
            APP.processEvents()
            page = dialog._loaded_pages[2]
            self.assertEqual(page.blocked_users.users(), self.window.settings['danmaku_blocked_users'])
            self.window.danmaku_blocking.block({'text': 'fixture'}, '1001')
            self.assertEqual(page.block_edit.toPlainText(), 'fixture')
            page.keep_spin.setValue(500)
            dialog.auto_save.flush()
            self.assertEqual(self.window.settings['danmaku_block_words'], ['fixture'])
            self.assertEqual(self.window.settings['danmaku_blocked_users'][0]['uid'], '42')
        finally:
            dialog.auto_save.stop()
            dialog.close()
            dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
