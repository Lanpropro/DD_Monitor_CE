"""Host-wide comment/user blocking, quick actions and persistence; isolated data only."""
import os
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, config, danmaku_actions, plugins, theme
from ddm.danmaku_filter import event_blocked, manual_user_error, normalize_users, user_identity
from ddm.settings_danmaku_blocking import BlockedUsersEditor
from ddm.settings_focus import SettingsInputFocus
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


    def test_block_origin_metadata_survives_normalization_without_changing_identity(self):
        rule = dict(platform='bilibili', uid='42', uname='User', blocked_at='2026-11-17T01:02:03+00:00',
                    source='message', source_text='<b>完整文本</b>\n第二行', source_room_id='1001', source_kind='danmaku')
        self.assertEqual(normalize_users([rule, dict(rule, source_text='later')]), [rule])
        legacy = {'platform': 'huya', 'uid': '123', 'uname': ''}
        self.assertEqual(normalize_users([legacy]), [legacy])
        self.assertTrue(event_blocked({'uid': '42', 'uname': 'Renamed'}, '2002',
                                     {'danmaku_blocked_users': [rule]}))

    def test_manual_identity_validation_follows_adapter_shapes_without_lookup(self):
        for platform in ('bilibili', 'douyin', 'douyu', 'huya', 'twitch'):
            self.assertEqual(manual_user_error(platform, '123456789012345'), '')
            for value in ('', '0', '-42', '昵称', '@login', 'https://example.invalid/42', '４２'):
                self.assertTrue(manual_user_error(platform, value), (platform, value))
        self.assertEqual(manual_user_error('youtube', 'UCfixture_123-abc'), '')
        self.assertIn('频道 ID', manual_user_error('youtube', '@handle'))
        self.assertTrue(manual_user_error('custom', 'opaque:user'))


class BlockingEditorTests(unittest.TestCase):
    def setUp(self):
        self.editor = BlockedUsersEditor([])
        self.editor.resize(850, 560)
        self.editor.show()
        APP.processEvents()

    def tearDown(self):
        self.editor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_manual_feedback_single_row_and_metadata_without_network_verification(self):
        editor = self.editor
        changed = []
        editor.changed.connect(lambda: changed.append(True))
        with patch('requests.sessions.Session.request', side_effect=AssertionError('No account lookup')) as request:
            editor.uid.setText('昵称')
            editor.add.click()
            self.assertEqual(editor.users(), [])
            self.assertIn('正整数', editor.feedback.text())
            editor.uid.setText('42')
            editor.add.click()
            self.assertEqual(changed, [True])
            rule = editor.users()[0]
            self.assertEqual(rule['source'], 'manual')
            self.assertNotIn('source_text', rule)
            self.assertIsNotNone(datetime.fromisoformat(rule['blocked_at']).tzinfo)
            self.assertIn('未核验', editor.feedback.text())
            editor.uid.setText('42')
            editor.add.click()
            self.assertEqual(changed, [True])
            self.assertEqual(editor.users(), [rule])
            self.assertIn('已在屏蔽列表', editor.feedback.text())
            request.assert_not_called()
        controls = (editor.platform, editor.uid, editor.add, editor.remove)
        centers = [widget.geometry().center().y() for widget in controls]
        self.assertLessEqual(max(centers) - min(centers), 1)
        editor.list.setCurrentRow(0)
        self.assertIn('手动添加，没有触发消息', editor.details.toPlainText())
        self.assertIn('手动填写ID，未查询昵称', editor.details.toPlainText())
        self.assertNotIn('平台：', editor.details.toPlainText())
        self.assertTrue(editor.list.item(0).icon().isNull())

    def test_details_preserve_full_text_and_legacy_unknowns_in_bounded_area(self):
        rule = dict(platform='youtube', uid='UCfixture', uname='User', source='message',
                    blocked_at='2026-11-17T01:02:03+00:00', source_room_id='youtube:live',
                    source_text='<b>完整原文</b>\n' + '完整长文本\n' * 300)
        self.editor.set_users([rule, dict(platform='huya', uid='123', uname='Old')])
        self.editor.list.setCurrentRow(0)
        APP.processEvents()
        text = self.editor.details.toPlainText()
        self.assertIn(rule['source_text'], text)
        self.assertIn('2026-11-17', text)
        self.assertIn('youtube:live', text)
        self.assertLessEqual(self.editor.details.height(), 190)
        self.assertGreater(self.editor.details.verticalScrollBar().maximum(), 0)
        self.editor.list.setCurrentRow(1)
        text = self.editor.details.toPlainText()
        self.assertIn('未记录屏蔽时间', text)
        self.assertIn('未记录触发消息', text)
        self.assertNotIn('2026-', text)

    def test_ctrl_shift_multi_selection_and_batch_remove(self):
        editor = self.editor
        editor.set_users([dict(platform='bilibili', uid=str(n), uname=f'用户{n}') for n in range(1, 9)])
        APP.processEvents()
        viewport = editor.list.viewport()
        def click(row, modifier=Qt.NoModifier):
            point = editor.list.visualItemRect(editor.list.item(row)).center()
            QTest.mouseClick(viewport, Qt.LeftButton, modifier, point)
        click(0)
        click(2, Qt.ControlModifier)
        self.assertEqual({editor.list.row(item) for item in editor.list.selectedItems()}, {0, 2})
        click(5, Qt.ShiftModifier)
        selected = editor.list.selectedItems()
        rows = {editor.list.row(item) for item in selected}
        self.assertTrue({2, 3, 4, 5} <= rows)
        removing = {item.data(Qt.UserRole)['uid'] for item in selected}
        before = {rule['uid'] for rule in editor.users()}
        changed = []
        editor.changed.connect(lambda: changed.append(True))
        editor.remove.click()
        self.assertEqual({rule['uid'] for rule in editor.users()}, before - removing)
        self.assertEqual(changed, [True])
        self.assertIn(str(len(removing)), editor.feedback.text())

    def test_inline_user_details_fit_the_real_blocking_card_after_selection_changes(self):
        page = DanmakuSettingsPage({'danmaku_blocked_users': [
            dict(platform='bilibili', uid=str(n), source='message',
                 blocked_at='2026-11-17T01:02:03+00:00', source_text='完整触发文本\n' * 100)
            for n in range(1, 4)]})
        page.setStyleSheet(theme.qss())
        try:
            page.show()
            editor = page.blocked_users
            card = page.sections.section('blocking')
            words = page.blocking_columns.section('words')
            self.assertTrue(words.isAncestorOf(editor.details), 'Details share the existing words-column space')
            self.assertFalse(editor.isAncestorOf(editor.details))
            def settle():
                for _ in range(3):
                    APP.processEvents()
            def details_fit():
                settle()
                center = editor.details.mapTo(page.scroll.widget(), editor.details.rect().center())
                page.scroll.ensureVisible(center.x(), center.y(), 0, editor.details.height() // 2 + 16)
                settle()
                self.assertTrue(editor.details.isVisible())
                self.assertEqual(editor.details.height(), 160)
                bottom = editor.details.mapTo(card, editor.details.rect().bottomRight())
                self.assertTrue(card.rect().contains(bottom), (page.width(), card.rect(), bottom))
                self.assertEqual(editor.details.visibleRegion().boundingRect().height(), 160)
                self.assertTrue(page.blocking_details_title.isVisible())
                self.assertGreaterEqual(editor.details.y(), page.block_edit.y() + page.block_edit.height())
            for width in (1200, 700):
                page.resize(width, 720)
                editor.list.clearSelection()
                editor.list.setCurrentRow(-1)
                settle()
                self.assertFalse(editor.details.isVisible())
                self.assertFalse(page.blocking_details_title.isVisible())
                editor.list.setCurrentRow(0)
                details_fit()
                editor.list.item(1).setSelected(True)
                self.assertEqual(len(editor.list.selectedItems()), 2)
                details_fit()
                editor.list.clearSelection()
                settle()
                self.assertFalse(editor.details.isVisible())
                bottom = editor.mapTo(card, editor.rect().bottomRight())
                self.assertTrue(card.rect().contains(bottom), (page.width(), card.rect(), bottom))
        finally:
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_user_list_and_origin_details_wheel_stay_local_at_both_boundaries(self):
        rules = [dict(platform='bilibili', uid=str(n), source='message',
                      source_text='完整原文\n' * 300) for n in range(1, 81)]
        page = DanmakuSettingsPage({'danmaku_blocked_users': rules})
        focus = SettingsInputFocus(page)
        try:
            page.resize(1200, 650)
            page.show()
            APP.processEvents()
            editor = page.blocked_users
            editor.list.setCurrentRow(0)
            APP.processEvents()
            outer = page.scroll.verticalScrollBar()
            self.assertGreater(outer.maximum(), 0)
            for control in (editor.list, editor.details):
                page.scroll.ensureWidgetVisible(control)
                APP.processEvents()
                bar = control.verticalScrollBar()
                self.assertGreater(bar.maximum(), 0)
                for position, delta in ((0, 120), (bar.maximum() // 2, -120), (bar.maximum(), -120)):
                    bar.setValue(position)
                    APP.processEvents()
                    value = outer.value()
                    viewport = control.viewport()
                    point = viewport.rect().center()
                    event = QWheelEvent(QPointF(point), QPointF(viewport.mapToGlobal(point)), QPoint(),
                                        QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
                    APP.sendEvent(viewport, event)
                    APP.processEvents()
                    self.assertTrue(event.isAccepted())
                    self.assertEqual(outer.value(), value, (type(control).__name__, position))
                    if position == bar.maximum() // 2:
                        self.assertGreater(bar.value(), position)
        finally:
            APP.removeEventFilter(focus)
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


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
        self.assertEqual({key: rule[key] for key in ('platform', 'uid', 'uname')},
                         {'platform': 'douyin', 'uid': '42', 'uname': '用户'})
        self.assertEqual(rule['source'], 'message')
        self.assertEqual(rule['source_text'], 'first')
        self.assertEqual(rule['source_room_id'], 'douyin:one')
        self.assertIsNotNone(datetime.fromisoformat(rule['blocked_at']).tzinfo)
        first = dict(rule)
        self.window.danmaku_blocking.block({'uid': '42', 'uname': '改名', 'text': 'later'},
                                          'douyin:two', user=True)
        self.assertEqual(self.window.settings['danmaku_blocked_users'][0], first)
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

    def test_both_menu_blocks_offer_undo_and_restore_the_clicked_comment(self):
        panel = self.window.wall.danmaku
        text = '需要撤回的弹幕'
        for action, key, label in ((2, 'danmaku_block_words', '屏蔽弹幕'),
                                   (3, 'danmaku_blocked_users', '屏蔽用户')):
            with self.subTest(action=action):
                self.route('1001', {'uid': '42', 'text': text})
                self.route('1001', {'uid': '43', 'text': '后一条'})
                received = panel._received
                menu = danmaku_actions.show_comment_menu
                with patch.object(danmaku_actions, 'show_comment_menu', wraps=menu) as opened:
                    panel._message_clicked(len(panel._blocks) - 2, QPoint(80, 80))
                    popup = APP.activePopupWidget()
                    popup.command_actions[action].trigger()
                    self.assertEqual(opened.call_count, 1)
                notices = self.window.findChildren(danmaku_actions.CommentUndoNotice)
                notice = next(item for item in notices if item.isVisible())
                self.assertEqual(notice.message.text(), '已' + label)
                self.assertEqual([entry['text'] for entry in panel._blocks], ['后一条'])
                self.assertTrue(self.window.settings[key])
                notice.undo.click()
                self.assertEqual(notice.message.text(), '已撤回' + label)
                self.assertFalse(self.window.settings[key])
                self.assertEqual([entry['text'] for entry in panel._blocks], [text, '后一条'])
                self.assertEqual(panel._received, received)
                notice.close()
                panel.set_placeholder('')

    def test_undo_does_not_remove_existing_or_replaced_rules(self):
        blocker = self.window.danmaku_blocking
        self.window.settings['danmaku_block_words'] = ['existing']
        self.assertIsNone(blocker.block({'text': 'EXISTING'}, '1001'))
        undo = blocker.block({'text': 'new rule'}, '1001')
        self.window.settings['danmaku_block_words'] = ['existing', 'manual']
        self.assertFalse(undo())
        self.assertEqual(self.window.settings['danmaku_block_words'], ['existing', 'manual'])

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
            self.assertEqual(self.window.settings['danmaku_blocked_users'][0]['source'], 'manual')
            self.assertNotIn('source_text', self.window.settings['danmaku_blocked_users'][0])
            self.assertTrue(editor.list.item(0).icon().isNull())
            manual_rule = dict(editor.users()[0])
            editor.set_users([{'platform': 'youtube', 'uid': str(index)} for index in range(20)])
            self.assertGreater(editor.list.verticalScrollBar().maximum(), 0)
            editor.set_users([manual_rule])
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

    def test_blocking_pushes_rules_to_isolated_settings_process(self):
        pushed = []
        class Process:
            def push_settings(self, values):
                pushed.append(values)
            def stop(self):
                pass
        self.window._settings_process = Process()
        self.window.danmaku_blocking.block({'text': 'fixture'}, '1001')
        self.assertEqual(pushed, [{'danmaku_block_words': ['fixture']}])
        self.window.danmaku_blocking.block({'uid': '42', 'text': '触发来源\n完整文本'}, '1001', user=True)
        rule = self.window.settings['danmaku_blocked_users'][0]
        self.assertEqual(pushed[-1], {'danmaku_blocked_users': [rule]})
        with patch.dict(os.environ):
            os.environ.pop('DDM_NO_SAVE', None)
            config.save(self.window.current_state(), raise_errors=True)
            saved = config.load()['settings']['danmaku_blocked_users']
        self.assertEqual(saved, [rule])
        self.assertEqual(saved[0]['source_text'], '触发来源\n完整文本')
        page = DanmakuSettingsPage({})
        try:
            page.sync_blocking(pushed[-1])
            self.assertEqual(page.values()['danmaku_blocked_users'], [rule])
        finally:
            page.deleteLater()


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        results = [run_widget_cases(case, __file__)
                   for case in (FilterTests, BlockingEditorTests, BlockingTests)]
        raise SystemExit(int(any(results)))
    else:
        unittest.main()
