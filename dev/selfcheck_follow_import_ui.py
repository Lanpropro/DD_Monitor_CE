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
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QWidget
from ddm import bili, theme
from ddm.account_dialog import AccountPlatformDialog
from ddm.badge_surface import BadgeSurface
from ddm.fullscreen_bar import FullscreenBar
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

    def test_follow_avatars_are_prominent_in_single_and_double_columns(self):
        avatar = QPixmap(88, 88)
        avatar.fill(Qt.red)
        for width, columns in ((580, 1), (790, 2)):
            self.page.resize(width, 620)
            QTest.qWait(20)
            listing = self.page.list
            self.assertEqual(listing.columns, columns)
            item = listing.item(0)
            self.page.set_avatar(item.data(Qt.UserRole)['room_id'], avatar)
            rect = listing.visualItemRect(item)
            pixmap = listing.viewport().grab()
            scale = pixmap.devicePixelRatio()
            screenshot = pixmap.toImage()
            point = QPoint(rect.left() + 36, rect.center().y() + 19)
            self.assertEqual(screenshot.pixelColor(round(point.x() * scale), round(point.y() * scale)), Qt.red)

    def test_native_controls_stay_below_owned_windows(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Native layer order requires the Windows backend')
        import ctypes
        from ctypes import wintypes

        owner = QWidget()
        owner.setAttribute(Qt.WA_ShowWithoutActivating)
        owner.setGeometry(-10000, -10000, 960, 720)
        owner._accounts = {}
        tile = QWidget(owner)
        tile._overlay_visible = True
        tile.wall_seamless = True
        tile._update_quick_danmaku_mask = lambda: None
        tile.resize(600, 460)
        bar = FullscreenBar(tile)
        bar.setGeometry(0, 400, 600, 38)
        bar.set_fullscreen(False, windowed_overlay=True)
        owner.show()
        bar.show()
        get_window = ctypes.windll.user32.GetWindow
        get_window.argtypes = (wintypes.HWND, wintypes.UINT)
        get_window.restype = wintypes.HWND

        def above(first, second):
            handle = int(first.winId())
            current = get_window(int(second.winId()), 3)  # GW_HWNDPREV
            while current and current != handle:
                current = get_window(current, 3)
            return current == handle

        def show(window):
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.setGeometry(bar.x() + 160, bar.y() - 200, 440, 420)
            window.show()
            window.move(bar.x() + 160, bar.y() - 12)
            self.assertTrue(window.frameGeometry().intersects(bar.geometry()), type(window).__name__)

        try:
            with patch.object(AccountPlatformDialog, 'select_platform'), patch.object(
                    AccountPlatformDialog, '_center_on_owner'):
                for import_follows in (True, False):
                    account = AccountPlatformDialog(owner, {}, import_follows=import_follows)
                    show(account)
                    bar.raise_()
                    self.assertTrue(above(account, bar), account.windowTitle())
                    account.close()
            settings = QDialog(owner, Qt.FramelessWindowHint)
            nested = QMessageBox(settings)
            tool = QWidget(owner, Qt.Tool | Qt.FramelessWindowHint)
            floating = QWidget(owner, Qt.Window | Qt.FramelessWindowHint)
            floating.setProperty('floatingDanmaku', True)
            windows = (settings, nested, tool, floating)
            for window in windows:
                show(window)
            for fullscreen in (False, True):
                bar.set_fullscreen(fullscreen, windowed_overlay=not fullscreen)
                bar.hide()
                bar.show()
                self.app.processEvents()
                for window in windows:
                    self.assertTrue(above(window, bar), (fullscreen, window.windowType()))
                tool.move(tool.pos() - QPoint(70, 30))
                nested.resize(nested.width() + 80, nested.height() + 40)
                bar.raise_()
                for window in windows:
                    self.assertTrue(above(window, bar), (fullscreen, window.windowType()))
            for window in reversed(windows):
                window.close()
            menu = QMenu(owner)
            menu.addAction('测试菜单')
            show(menu)
            bar.raise_()
            self.assertTrue(above(menu, bar), 'A popup must remain above the controls')
            menu.close()
            playback_badge = BadgeSurface(owner, Qt.Tool | Qt.FramelessWindowHint)
            show(playback_badge)
            bar.raise_()
            self.assertTrue(above(bar, playback_badge), 'Playback layers must retain their natural order')
        finally:
            owner.close()

    def test_only_new_rows_can_be_selected_by_mouse_or_keyboard(self):
        listing = self.page.list
        existing, new = listing.item(0), listing.item(1)
        self.assertEqual(self.page.selected(), [])
        self.assertFalse(self.page.import_button.isEnabled())
        self.assertFalse(existing.flags() & Qt.ItemIsUserCheckable)
        self.assertIn('已添加', existing.toolTip())
        QTest.mouseClick(listing.viewport(), Qt.LeftButton, pos=listing.visualItemRect(existing).center())
        QTest.keyClick(listing, Qt.Key_Space)
        self.assertEqual(self.page.selected(), [])
        rect = listing.visualItemRect(new)
        QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton,
                         pos=QPoint(rect.right() - 22, rect.center().y()))
        self.assertEqual(self.page.selected(), [ROOMS[1]])
        self.assertEqual(self.page.import_button.text(), '添加 1 位主播')
        QTest.keyClick(listing, Qt.Key_Space)
        self.assertEqual(self.page.selected(), [])
        self.assertFalse(self.page.import_button.isEnabled())

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
            self.assertEqual(self.page.header.text(), '已选 1 位主播')
            self.page._check_all(False)

    def test_pinyin_search_visible_actions_and_new_count(self):
        self.page.search_edit.setText('xiaoming')
        self.assertEqual([self.page.list.item(i).isHidden() for i in range(3)], [True, False, True])
        self.page._check_all(True)
        self.assertEqual(self.page.selected(), [ROOMS[1]])
        self.assertEqual(self.page.import_button.text(), '添加 1 位主播')
        self.page.search_edit.setText('cszb')
        self.assertFalse(self.page.list.item(0).isHidden())
        self.page._check_all(False)
        self.assertEqual(self.page.selected(), [ROOMS[1]])
        self.page.search_edit.clear()
        self.page._check_live()
        self.assertEqual(self.page.selected(), ROOMS[1:])
        self.assertEqual(self.page.import_button.text(), '添加 2 位主播')

    def test_responsive_footer_and_folder_action_lifetime(self):
        from PySide6.QtWidgets import QStyle, QStyleOptionButton
        for width in (700, 430, 700, 430):
            self.page.resize(width, 620)
            QTest.qWait(20)
            self.assertEqual(self.page.width(), width)
            for control in (self.page.folder_button, self.page.import_button):
                rect = control.rect().translated(control.mapTo(self.page, QPoint()))
                self.assertTrue(self.page.rect().contains(rect), (width, rect))
            folder = self.page.folder_button
            self.assertEqual(folder.mapTo(self.page, QPoint()).x(), self.page.list.x())
            self.assertGreaterEqual(folder.width(), 210 if width == 700 else 140)
            self.assertEqual(folder.height(), self.page.sort_control.height())
            self.assertTrue(folder.property('followFolderSelect'))
            option = QStyleOptionButton()
            folder.initStyleOption(option)
            content = folder.style().subElementRect(QStyle.SE_PushButtonContents, option, folder)
            self.assertGreaterEqual(content.left(), 10)
            self.assertLess(folder.mapTo(self.page, folder.rect().topRight()).x(),
                            self.page.confirm_controls.mapTo(self.page, QPoint()).x())
            if width == 700:
                self.assertLess(folder.mapTo(self.page, folder.rect().topRight()).x(),
                                self.page.header.mapTo(self.page, QPoint()).x())
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
        self.page._check_all(True)
        with patch('ddm.room_folder_controls.create_folder_dialog', return_value=('new', '新文件夹')):
            self.page.new_folder_action.trigger()
        self.assertEqual(self.page.folder_id, 'new')
        self.assertEqual(self.page.folder_button.text(), '新文件夹')
        self.assertEqual(self.page.selected(), [ROOMS[1]])
        self.assertEqual(self.page.search_edit.text(), 'xiaoming')

    def test_pending_selection_resolves_without_losing_checks(self):
        self.page.close()
        self.page = FollowImportDialog([dict(room_id='', anchor_uid='a', uname='小明', live=False)],
                                       set(), room_menu=True)
        self.page.show()
        self.assertTrue(self.page.list.item(0).isHidden())
        self.page.show_pending.setChecked(True)
        self.assertFalse(self.page.list.item(0).isHidden())
        self.page._check_all(True)
        self.assertEqual(self.page.import_button.text(), '保存 1 位待识别主播')
        self.page.update_account(dict(room_id='400', anchor_uid='a', uname='小明', live=True))
        self.assertEqual(self.page.selected()[0]['room_id'], '400')
        self.assertEqual(self.page.import_button.text(), '添加 1 位主播')

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
            self.assertEqual(self.page.selected(), [])
            QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton, pos=second.center())
            self.assertEqual(self.page.selected(), [ROOMS[1]])
            QTest.mouseClick(self.page.list.viewport(), Qt.LeftButton, pos=second.center())
            self.assertEqual(self.page.selected(), [])

        title = '完整的直播标题' * 20
        self.page.close()
        self.page = FollowImportDialog([dict(ROOMS[0], title=title)], set())
        self.assertIn(title, self.page.list.item(0).toolTip())

    def test_sort_and_hide_keep_new_checks_and_skip_existing_rows(self):
        page = self.page
        page.list.item(1).setCheckState(Qt.Checked)
        def order():
            return [page.list.item(i).data(Qt.UserRole)['room_id'] for i in range(page.list.count())]
        for mode, expected in [('live', ['100', '300', '200']), ('unadded', ['200', '300', '100']),
                               ('name', ['100', '300', '200']), ('original', ['100', '200', '300'])]:
            page.sort_control.setCurrentIndex(page.sort_control.findData(mode))
            self.assertEqual(order(), expected)
            self.assertEqual(page.selected(), [ROOMS[1]])
        page.hide_existing.setChecked(True)
        self.assertTrue(page.list.item(0).isHidden())
        page._check_all(True)
        self.assertEqual(page.selected(), ROOMS[1:])
        page._check_all(False)
        self.assertEqual(page.selected(), [])
        page.hide_existing.setChecked(False)
        self.assertFalse(page.list.item(0).isHidden())

    def test_hide_all_existing_has_hint_without_removing_them(self):
        self.page.close()
        self.page = FollowImportDialog(ROOMS, {'100', '200', '300'})
        self.page.hide_existing.setChecked(True)
        self.assertTrue(all(self.page.list.item(i).isHidden() for i in range(3)))
        self.assertEqual(self.page.selected(), [])
        self.assertFalse(self.page.import_button.isEnabled())
        self.assertFalse(self.page.empty_label.isHidden())
        self.assertIn('取消', self.page.empty_label.text())

    def test_pending_resolution_updates_the_same_item_after_sorting(self):
        self.page.close()
        self.page = FollowImportDialog([
            dict(room_id='', anchor_uid='a', uname='Zed', live=False),
            dict(room_id='known', anchor_uid='b', uname='Alice', live=True)], set(), room_menu=True)
        page = self.page
        page.show_pending.setChecked(True)
        page.list.item(0).setCheckState(Qt.Checked)
        page.sort_control.setCurrentIndex(page.sort_control.findData('name'))
        self.assertEqual(page.list.item(0).data(Qt.UserRole)['anchor_uid'], 'b')
        page.update_account(dict(room_id='resolved', anchor_uid='a', uname='Aaron', live=True))
        self.assertEqual(page.list.item(0).data(Qt.UserRole)['anchor_uid'], 'a')
        self.assertEqual(page.selected()[0]['room_id'], 'resolved')
        self.assertEqual(page.list.item(1).data(Qt.UserRole)['room_id'], 'known')
        page.sort_control.setCurrentIndex(page.sort_control.findData('original'))
        self.assertEqual(page.list.item(0).data(Qt.UserRole)['anchor_uid'], 'a')

    def test_single_platform_login_aligns_selection_on_first_show(self):
        from ddm.login import LoginWindow

        owner = QWidget()
        owner._accounts = {}
        owner._on_login = Mock()
        self.addCleanup(owner.deleteLater)
        with patch.object(bili, 'SESSION_DATA', ''), patch.object(LoginWindow, 'start_login'), patch.object(
                AccountPlatformDialog, '_center_on_owner'):
            dialog = AccountPlatformDialog(owner, {})
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.close)
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.move(-10000, -10000)
            dialog.show()
            self.app.processEvents()

        if dialog._opaque_login:
            self.assertFalse(dialog.testAttribute(Qt.WA_TranslucentBackground))
            self.assertEqual(dialog.mask().isEmpty(), dialog._native_corners)
        tabs = dialog.account_bar.platform
        self.assertTrue(tabs.buttons['bilibili'].isVisible())
        self.assertTrue(tabs.buttons['bilibili'].isChecked())
        self.assertTrue(tabs.more.isHidden())
        self.assertEqual(tabs._selection.rect, tabs._segment_rects()['bilibili'])

    def test_login_segments_switch_platform_and_keep_overflow_actions(self):
        from ddm import motion
        from ddm.settings_material import set_segment_motion
        owner = QWidget()
        set_segment_motion(owner, True)
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
        selection = tabs._selection
        origin = selection.rect
        with patch.object(motion, 'enabled', return_value=True):
            QTest.mouseClick(tabs.buttons['douyu'], Qt.LeftButton)
            self.assertEqual(selection.rect, origin)
            self.assertTrue(selection._timer.isActive())
            QTest.qWait(220)
            self.assertNotEqual(selection.rect, origin)
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
        self.assertEqual(selection.rect, tabs._segment_rects()[key])

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
        uid = '123456789'
        owner._accounts = {'bilibili': dict(uname='测试账号', uid=uid)}
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
            account = dialog.import_bar.account
            self.assertEqual(tabs.buttons['bilibili'].parentWidget().objectName(), 'LoginPlatformSegments')
            self.assertEqual(dialog.import_bar.refresh.objectName(), 'NavigationButton')
            self.assertEqual(dialog.import_bar.refresh.size(), dialog.import_bar.titlebar.close_button.size())
            for width in (430, 700, 430):
                dialog.resize(width, dialog.height())
                QTest.qWait(15)
                self.assertTrue(account.account_id.isVisible())
                self.assertEqual(account.account_id.text(), f'ID: {uid}')
                self.assertGreaterEqual(account.account_id.width(),
                                        account.account_id.fontMetrics().horizontalAdvance(f'ID: {uid}'))
                account_right = account.mapTo(dialog, account.rect().topRight()).x()
                refresh_left = dialog.import_bar.refresh.mapTo(dialog, QPoint()).x()
                self.assertLess(account_right, refresh_left)
                for button in [*tabs.buttons.values(), tabs.more]:
                    if button.isVisible():
                        rect = button.rect().translated(button.mapTo(tabs, QPoint()))
                        self.assertTrue(tabs.rect().contains(rect), (width, rect, tabs.rect()))
            self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
            self.assertTrue(dialog.testAttribute(Qt.WA_TranslucentBackground))
            self.assertEqual(dialog.grab().toImage().pixelColor(0, 0).alpha(), 0)
            self.assertEqual(account.name.text(), '测试账号')
            owner._accounts['bilibili']['uname'] = '很长的账号昵称' * 12
            dialog._update_platform_labels()
            QTest.qWait(15)
            self.assertLessEqual(account.width(), 200)
            self.assertTrue(account.name.text().endswith('…'))
            self.assertEqual(account.account_id.text(), f'ID: {uid}')
            dialog.resize(700, dialog.height())
            extended_uid = uid + '0123456789'
            owner._accounts['bilibili']['uid'] = extended_uid
            dialog._update_platform_labels()
            QTest.qWait(15)
            self.assertEqual(account.account_id.text(), f'ID: {extended_uid}')
            owner._accounts['bilibili']['uid'] = uid
            dialog._update_platform_labels()
            QTest.qWait(15)
            dialog.resize(430, dialog.height())
            original = dialog.page
            dialog.import_bar.refresh.click()
            self.assertIsNot(dialog.page, original)
            dialog._busy(True)
            self.assertFalse(dialog.import_bar.platform.isEnabled())
            self.assertFalse(dialog.import_bar.refresh.isEnabled())
            dialog._busy(False)
            QTest.mouseClick(dialog.import_bar.platform.buttons['test'], Qt.LeftButton)
            self.assertEqual(dialog.kind, 'test')
            self.assertTrue(account.account_id.isHidden())
            self.assertFalse(dialog.import_bar.refresh.isEnabled())
            QTest.mouseClick(dialog.import_bar.platform.buttons['bilibili'], Qt.LeftButton)
            QTest.qWait(15)
            self.assertIsInstance(dialog.page, FollowImportDialog)
            self.assertEqual(account.account_id.text(), f'ID: {uid}')
            self.assertEqual(dialog.width(), 430)
            dialog.import_bar.titlebar.close_button.click()
            self.assertFalse(dialog.isVisible())
        owner.close()

    def test_import_actions_use_shared_buttons(self):
        from ddm.ui import ActionButton
        page = self.page
        self.assertTrue(all(isinstance(button, ActionButton)
                            for button in (*page.filter_buttons, page.folder_button, page.import_button)))
        cancel = next(button for button in page.confirm_controls.findChildren(ActionButton)
                      if button.text() == '取消')
        self.assertEqual(cancel.objectName(), 'IconButton')
        self.assertEqual(page.import_button.objectName(), 'PrimaryButton')
        self.assertFalse(page.import_button.isEnabled())
        page.filter_buttons[0].click()
        self.assertTrue(page.import_button.isEnabled())

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
                self.assertFalse(item.flags() & Qt.ItemIsUserCheckable)
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
