"""导入关注紧凑界面：真实控件、假账号数据，不调用平台协议。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import bili, theme
from ddm.account_dialog import AccountPlatformDialog
from ddm.room_dialogs import FollowImportDialog

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
            self.assertEqual(dialog.width(), 430)
            self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
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
            dialog.import_bar.platform.setCurrentIndex(dialog.import_bar.platform.findData('test'))
            self.assertEqual(dialog.kind, 'test')
            self.assertFalse(dialog.import_bar.refresh.isEnabled())
            dialog.import_bar.platform.setCurrentIndex(dialog.import_bar.platform.findData('bilibili'))
            self.assertIsInstance(dialog.page, FollowImportDialog)
            self.assertEqual(dialog.width(), 430)
            dialog.import_bar.titlebar.close_button.click()
            self.assertFalse(dialog.isVisible())
        owner.close()


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(FollowImportUITests, __file__))
    unittest.main()
