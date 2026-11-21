"""导入关注紧凑界面：真实控件、假账号数据，不调用平台协议。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QEvent, QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from ddm import bili, theme
from ddm.account_dialog import AccountPlatformDialog
from ddm.room_dialogs import FollowImportDialog
from ddm.follow_import_ui import AccountImportBar

ROOMS = [dict(room_id='100', uname='测试主播', live=True, title='直播标题'),
         dict(room_id='200', uname='小明', live=False, title='游戏直播'),
         dict(room_id='300', uname='其他主播', live=True)]


class FollowImportUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.page = FollowImportDialog(ROOMS, {'100'}, folders=[dict(id='games', name='赛事', type='normal')])
        self.page.show()
        QTest.qWait(20)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()

    def test_row_checkbox_keyboard_and_removal_summary(self):
        item = self.page.list.item(0)
        rect = self.page.list.visualItemRect(item)
        QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton, pos=rect.center())
        self.assertEqual(self.page.selected(), [])
        self.assertIn('移除 1', self.page.header.text())
        self.assertTrue(self.page.removal_hint.isVisible())
        self.page.list.setFocus()
        QTest.keyClick(self.page.list, Qt.Key_Space)
        self.assertEqual(self.page.selected(), [ROOMS[0]])
        self.assertFalse(self.page.removal_hint.isVisible())
        QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton,
                         pos=QPoint(rect.right() - 22, rect.center().y()))
        self.assertEqual(self.page.selected(), [])

    def test_scrolled_mouse_clicks_toggle_avatar_text_and_checkbox(self):
        self.page.close()
        rooms = [dict(room_id=str(i), uname=f'主播{i}', live=False) for i in range(100)]
        self.page = FollowImportDialog(rooms, set())
        self.page.show()
        QTest.qWait(25)
        self.page.list.scrollToItem(self.page.list.item(45))
        QTest.qWait(25)
        item = self.page.list.item(45)
        rect = self.page.list.visualItemRect(item)
        for x in (rect.left() + 30, rect.center().x(), rect.right() - 22):
            pos = QPoint(x, rect.center().y())
            QTest.mouseMove(self.page.list.viewport(), pos)
            QTest.mousePress(self.page.list.viewport(), Qt.LeftButton, pos=pos)
            QTest.qWait(15)
            QTest.mouseRelease(self.page.list.viewport(), Qt.LeftButton, pos=pos)
            QTest.qWait(5)
            self.assertEqual(item.checkState(), Qt.Checked)
            self.assertEqual(self.page.header.text(), '已选 1 · 新增 1')
            self.page._check_all(False)

    def test_pinyin_search_visible_actions_and_new_count(self):
        self.page.search_edit.setText('xiaoming')
        self.assertEqual([self.page.list.item(i).isHidden() for i in range(3)], [True, False, True])
        self.page._check_all(True)
        self.assertEqual(self.page.selected(), ROOMS[:2])
        self.assertEqual(self.page.header.text(), '已选 2 · 新增 1')
        self.page.search_edit.setText('cszb')
        self.assertFalse(self.page.list.item(0).isHidden())
        self.page._check_all(False)
        self.assertEqual(self.page.selected(), [ROOMS[1]])
        self.assertIn('移除 1', self.page.header.text())
        self.assertEqual(self.page.deselected_existing(), ['100'])

    def test_responsive_footer_and_folder_action_lifetime(self):
        for width in (700, 430, 700, 430):
            self.page.resize(width, 620)
            QTest.qWait(20)
            self.assertEqual(self.page.width(), width)
            for control in (self.page.folder_button, self.page.import_button):
                rect = control.rect().translated(control.mapTo(self.page, QPoint()))
                self.assertTrue(self.page.rect().contains(rect), (width, rect))
            action = next(a for a in self.page.folder_button.menu().actions() if a.data() == 'games')
            action.trigger()
            self.assertEqual(self.page.folder_id, 'games')
            row = self.page.footer.getItemPosition(self.page.footer.indexOf(self.page.confirm_controls))[0]
            self.assertEqual(row, 0 if width == 700 else 1)

    def test_new_folder_is_a_menu_action_and_preserves_selection(self):
        self.assertFalse(hasattr(self.page, 'new_folder_button'))
        self.assertEqual(self.page.new_folder_action.text(), '新建文件夹…')
        self.assertFalse(self.page.new_folder_action.isEnabled())
        self.page.close()
        self.page = FollowImportDialog(ROOMS, {'100'}, folder_creator=lambda *_: None)
        self.page.search_edit.setText('xiaoming')
        with patch('ddm.room_folder_controls.create_folder_dialog', return_value=('new', '新文件夹')):
            self.page.new_folder_action.trigger()
        self.assertEqual(self.page.folder_id, 'new')
        self.assertEqual(self.page.folder_button.text(), '新文件夹')
        self.assertEqual(self.page.selected(), [ROOMS[0]])
        self.assertEqual(self.page.search_edit.text(), 'xiaoming')

    def test_pending_selection_resolves_without_losing_checks(self):
        self.page.close()
        self.page = FollowImportDialog([dict(room_id='', anchor_uid='a', uname='小明', live=False,
                                            pending_import=True)], set(), room_menu=True)
        self.page.show()
        self.assertIn('待识别 1', self.page.header.text())
        self.assertTrue(self.page.list.item(0).isHidden())
        self.page.show_pending.setChecked(True)
        self.assertFalse(self.page.list.item(0).isHidden())
        self.page.update_account(dict(room_id='400', anchor_uid='a', uname='小明', live=True))
        self.assertEqual(self.page.selected()[0]['room_id'], '400')
        self.assertEqual(self.page.header.text(), '已选 1 · 新增 1')

    def test_batched_list_scroll_loads_last_avatar(self):
        self.page.close()
        rooms = [dict(room_id=str(i), uname=str(i), live=False, face='https://example.invalid/'+str(i))
                 for i in range(300)]
        self.page = FollowImportDialog(rooms, set())
        requests = []
        self.page.avatarRequested.connect(requests.append)
        self.page.show()
        for _ in range(100):
            if not self.page._populating:
                break
            QTest.qWait(10)
        self.assertEqual(self.page.list.count(), 300)
        self.page.list.scrollToBottom()
        QTest.qWait(80)
        self.assertTrue(any('299' in batch for batch in requests))
        avatar = QPixmap(32, 32)
        avatar.fill(Qt.red)
        self.page.set_avatar('299', avatar)
        self.assertFalse(self.page.list.item(299).icon().isNull())
        self.assertFalse(self.page.selected())

    def test_two_column_reflow_retains_selection_and_click_targets(self):
        for width, columns in ((760, 2), (430, 1), (760, 2)):
            self.page.resize(width, 620)
            QTest.qWait(25)
            self.assertEqual(self.page.list.columns, columns)
            first = self.page.list.visualItemRect(self.page.list.item(0))
            second = self.page.list.visualItemRect(self.page.list.item(1))
            if columns == 2:
                self.assertEqual(first.top(), second.top())
                self.assertGreater(second.left(), first.right())
            else:
                self.assertGreater(second.top(), first.bottom())
            self.assertEqual(self.page.selected(), [ROOMS[0]])
            QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton, pos=second.center())
            self.assertEqual(self.page.selected(), ROOMS[:2])
            QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton, pos=second.center())
            self.assertEqual(self.page.selected(), [ROOMS[0]])

        title = '完整的直播标题' * 20
        self.page.close()
        self.page = FollowImportDialog([dict(ROOMS[0], title=title)], set())
        self.assertIn(title, self.page.list.item(0).toolTip())

    def test_sort_and_hide_keep_existing_checks_and_explicit_folder_scope(self):
        page = self.page
        def order():
            return [page.list.item(i).data(Qt.UserRole)['room_id'] for i in range(page.list.count())]
        for mode, expected in [('live', ['100', '300', '200']), ('unadded', ['200', '300', '100']),
                               ('name', ['100', '300', '200']), ('original', ['100', '200', '300'])]:
            page.sort_control.setCurrentIndex(page.sort_control.findData(mode))
            self.assertEqual(order(), expected)
            self.assertEqual(page.selected(), [ROOMS[0]])
            self.assertEqual(page.deselected_existing(), [])
            self.assertEqual(page.folder_room_ids(), [])
        page.hide_existing.setChecked(True)
        self.assertTrue(page.list.item(0).isHidden())
        page._check_all(True)
        self.assertEqual(page.selected(), ROOMS)
        self.assertEqual(page.folder_room_ids(), ['200', '300'])
        self.assertEqual(page.deselected_existing(), [])
        page._check_all(False)
        self.assertEqual(page.selected(), [ROOMS[0]])
        self.assertEqual(page.deselected_existing(), [])
        page.hide_existing.setChecked(False)
        self.assertFalse(page.list.item(0).isHidden())

    def test_hide_all_existing_has_hint_without_removing_them(self):
        self.page.close()
        self.page = FollowImportDialog(ROOMS, {'100', '200', '300'})
        self.page.hide_existing.setChecked(True)
        self.assertTrue(all(self.page.list.item(i).isHidden() for i in range(3)))
        self.assertEqual(self.page.selected(), ROOMS)
        self.assertEqual(self.page.deselected_existing(), [])
        self.assertFalse(self.page.empty_label.isHidden())
        self.assertIn('取消', self.page.empty_label.text())

    def test_pending_resolution_updates_the_same_item_after_sorting(self):
        self.page.close()
        self.page = FollowImportDialog([
            dict(room_id='', anchor_uid='a', uname='Zed', live=False, pending_import=True),
            dict(room_id='known', anchor_uid='b', uname='Alice', live=True)], set(), room_menu=True)
        page = self.page
        page.show_pending.setChecked(True)
        page.sort_control.setCurrentIndex(page.sort_control.findData('name'))
        self.assertEqual(page.list.item(0).data(Qt.UserRole)['anchor_uid'], 'b')
        page.update_account(dict(room_id='resolved', anchor_uid='a', uname='Aaron', live=True))
        self.assertEqual(page.list.item(0).data(Qt.UserRole)['anchor_uid'], 'a')
        self.assertEqual(page.selected()[0]['room_id'], 'resolved')
        self.assertEqual(page.list.item(1).data(Qt.UserRole)['room_id'], 'known')
        page.sort_control.setCurrentIndex(page.sort_control.findData('original'))
        self.assertEqual(page.list.item(0).data(Qt.UserRole)['anchor_uid'], 'a')

    def test_login_segments_switch_platform_and_keep_overflow_actions(self):
        owner = QWidget()
        owner._accounts = {'douyu': {'uname': '测试'}}
        providers = {kind: SimpleNamespace(kind=kind, label=label, account_login_notice=label) for kind, label in (
            ('douyin', '抖音'), ('douyu', '斗鱼'), ('huya', '虎牙'), ('twitch', 'Twitch'), ('youtube', 'YouTube'))}
        dialog = AccountPlatformDialog(owner, providers, platform_kind='douyin')
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        tabs = dialog.account_bar.platform
        self.assertEqual(tabs.buttons['douyin'].parentWidget().objectName(), 'LoginPlatformSegments')
        self.assertTrue(tabs.buttons['douyin'].isChecked())
        self.assertTrue(tabs.buttons['douyu'].property('loggedIn'))
        QTest.mouseClick(tabs.buttons['douyu'], Qt.LeftButton)
        self.assertEqual(dialog.kind, 'douyu')
        self.assertTrue(tabs.buttons['douyu'].isChecked())
        self.assertFalse(tabs.buttons['douyin'].isChecked())
        dialog.resize(240, dialog.height())
        self.app.processEvents()
        self.assertTrue(tabs.more.isVisible())
        key = next(key for key, action in tabs.actions.items() if action.isVisible() and key != 'bilibili')
        tabs.actions[key].trigger()
        self.assertEqual(dialog.kind, key)
        self.assertTrue(tabs.buttons[key].isChecked())

    def test_platform_overflow_keeps_active_and_all_providers_reachable(self):
        owner = QDialog()
        bar = AccountImportBar([(str(i), f'平台{i}') for i in range(8)], owner)
        bar.resize(400, 90)
        owner.show()
        bar.show()
        bar.platform.set_current('7')
        QTest.qWait(20)
        tabs = bar.platform
        self.assertTrue(tabs.buttons['7'].isVisible())
        self.assertTrue(tabs.buttons['7'].isChecked())
        self.assertTrue(tabs.more.isVisible())
        for kind, button in tabs.buttons.items():
            self.assertEqual(button.isVisible(), not tabs.actions[kind].isVisible())
        requests = []
        tabs.selectionRequested.connect(requests.append)
        hidden = next(kind for kind, button in tabs.buttons.items() if not button.isVisible())
        tabs.actions[hidden].trigger()
        self.assertEqual(requests, [hidden])
        tabs.set_current(hidden)
        self.assertTrue(tabs.buttons[hidden].isChecked())
        self.assertTrue(tabs.buttons[hidden].isVisible())
        owner.close()

    def test_first_browser_platform_keeps_visible_window_and_native_handle(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Native HWND lifecycle requires the Windows backend')
        owner = QWidget()
        owner.resize(900, 800)
        owner.plugins = SimpleNamespace(_platform_owner={})
        owner._accounts = {'bilibili': dict(uname='Fixture')}
        owner._closing = False
        owner._clear_platform_account = lambda *_: None
        owner.sidebar = SimpleNamespace(rooms=lambda: [], folder_state=lambda: [], create_folder=lambda _: None)
        owner._start_avatar_loader = lambda *_: None
        provider = SimpleNamespace(kind='douyu', label='斗鱼', follow_cookie_domain='douyu.com',
                                   follow_login_url='about:blank', account_login_url='about:blank')
        events = []
        class VisibilityTrace(QObject):
            def eventFilter(self, watched, event):
                if event.type() in (QEvent.Hide, QEvent.Show, QEvent.WinIdChange):
                    events.append(event.type())
                return False
        with patch.object(bili, 'SESSION_DATA', 'fixture'), patch.object(
                AccountPlatformDialog, '_load_bili', lambda dialog: dialog._show_rooms(ROOMS)):
            dialog = AccountPlatformDialog(owner, {'douyu': provider}, import_follows=True)
            dialog.show()
            QTest.qWait(40)
            trace = VisibilityTrace(dialog)
            dialog.installEventFilter(trace)
            handle = int(dialog.winId())
            try:
                for kind in ('douyu', 'bilibili', 'douyu'):
                    QTest.mouseClick(dialog.import_bar.platform.buttons[kind], Qt.LeftButton)
                    QTest.qWait(30)
                    self.assertEqual(dialog.kind, kind)
                    self.assertTrue(dialog.isVisible())
                    self.assertEqual(int(dialog.winId()), handle)
                    self.assertEqual(events, [])
                self.assertIs(dialog._platform_pages['douyu'].browser.window(), dialog)
            finally:
                dialog.removeEventFilter(trace)
                dialog.reject()
                dialog.deleteLater()
                owner.close()

    def test_source_bar_refresh_and_platform_switch(self):
        owner = QWidget()
        owner.resize(430, 800)
        owner.plugins = SimpleNamespace(_platform_owner={})
        owner._accounts = {'bilibili': dict(uname='测试账号')}
        owner._closing = False
        owner.sidebar = SimpleNamespace(rooms=lambda: [], folder_state=lambda: [], create_folder=lambda _: None)
        owner._start_avatar_loader = lambda *_: None
        provider = SimpleNamespace(kind='test', label='其他平台', account_login_notice='测试平台说明')
        with patch.object(bili, 'SESSION_DATA', 'fixture'), patch.object(
                AccountPlatformDialog, '_load_bili', lambda dialog: dialog._show_rooms(ROOMS)):
            dialog = AccountPlatformDialog(owner, {'test': provider}, import_follows=True)
            dialog.show()
            QTest.qWait(20)
            self.assertEqual(dialog.import_bar.account.uname, '测试账号')
            QTest.mouseClick(dialog.import_bar.platform.buttons['bilibili'], Qt.LeftButton)
            self.assertTrue(dialog.import_bar.platform.buttons['bilibili'].isChecked())
            self.assertEqual(dialog.width(), 430)
            tabs = dialog.import_bar.platform
            for width in (430, 700, 430):
                dialog.resize(width, dialog.height())
                QTest.qWait(15)
                for button in [*tabs.buttons.values(), tabs.more]:
                    if button.isVisible():
                        rect = button.rect().translated(button.mapTo(tabs, QPoint()))
                        self.assertTrue(tabs.rect().contains(rect), (width, rect, tabs.rect()))
            self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
            self.assertTrue(dialog.testAttribute(Qt.WA_TranslucentBackground))
            self.assertEqual(dialog.grab().toImage().pixelColor(0, 0).alpha(), 0)
            self.assertLessEqual(dialog.import_bar.account.width(), 200)
            name = dialog.import_bar.account.name
            self.assertGreaterEqual(name.width(), name.fontMetrics().horizontalAdvance(name.text()))
            original = dialog.page
            dialog.import_bar.refresh.click()
            self.assertIsNot(dialog.page, original)
            dialog._busy(True)
            self.assertFalse(dialog.import_bar.platform.isEnabled())
            self.assertFalse(dialog.import_bar.refresh.isEnabled())
            dialog._busy(False)
            QTest.mouseClick(dialog.import_bar.platform.buttons['test'], Qt.LeftButton)
            self.assertEqual(dialog.kind, 'test')
            self.assertFalse(dialog.import_bar.refresh.isEnabled())
            QTest.mouseClick(dialog.import_bar.platform.buttons['bilibili'], Qt.LeftButton)
            self.assertIsInstance(dialog.page, FollowImportDialog)
            self.assertEqual(dialog.width(), 430)
            dialog.import_bar.titlebar.close_button.click()
            self.assertFalse(dialog.isVisible())
        owner.close()

    def test_import_reuses_sidebar_avatar_before_requesting_visible_rows(self):
        owner = QWidget()
        owner.setAttribute(Qt.WA_DontShowOnScreen)
        owner.plugins = SimpleNamespace(_platform_owner={})
        owner._accounts = {'bilibili': dict(uname='测试账号')}
        owner._closing = False
        avatar = QPixmap(48, 48)
        avatar.fill(Qt.red)
        local = {str(i): dict(room_id=str(i), face=f'https://example.invalid/local/{i}')
                 for i in (100, 200, 300)}
        items = [SimpleNamespace(room=room, thumb=SimpleNamespace(
            face_pixmap=lambda rid=rid: avatar if rid != '300' else None)) for rid, room in local.items()]
        owner.sidebar = SimpleNamespace(rooms=lambda: list(local.values()), items=lambda: items,
                                        folder_state=lambda: [], create_folder=lambda _: None)
        owner._start_avatar_loader = Mock()
        rooms = [dict(room) for room in ROOMS]
        rooms[1]['face'] = 'https://example.invalid/updated/200'
        rooms.append(dict(room_id='400', uname='新增主播', live=False, face='https://example.invalid/new/400'))
        with patch.object(bili, 'SESSION_DATA', 'fixture'), patch.object(
                AccountPlatformDialog, '_load_bili', lambda dialog: dialog._show_rooms(rooms)):
            dialog = AccountPlatformDialog(owner, {}, import_follows=True)
        dialog.setAttribute(Qt.WA_DontShowOnScreen)
        dialog.show()
        try:
            for _ in range(50):
                if owner._start_avatar_loader.called:
                    break
                QTest.qWait(10)
            page = dialog.page
            for rid in ('100', '200'):
                item = page._avatar_items[rid]
                self.assertFalse(item.icon().isNull())
                self.assertEqual(item.icon().pixmap(32, 32).toImage().pixelColor(16, 16), Qt.red)
                self.assertEqual(item.checkState(), Qt.Checked)
            requested = {rid: url for call in owner._start_avatar_loader.call_args_list
                         for rid, url in call.args[0].items()}
            self.assertEqual(requested, {'200': rooms[1]['face'], '300': local['300']['face'],
                                         '400': rooms[3]['face']})
            fresh = QPixmap(48, 48)
            fresh.fill(Qt.blue)
            page.set_avatar('200', fresh)
            self.assertEqual(page._avatar_items['200'].icon().pixmap(32, 32).toImage().pixelColor(16, 16), Qt.blue)
            self.assertNotIn('face', rooms[0])
        finally:
            dialog.reject()
            dialog.deleteLater()
            owner.close()


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(FollowImportUITests, __file__))
    unittest.main()
