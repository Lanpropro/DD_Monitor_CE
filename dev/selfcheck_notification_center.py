"""通知收件箱：会话隔离、未读、历史操作、删除动画与横竖屏入口。"""
from contextlib import ExitStack
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from ddm import motion, theme
from ddm.notification_center import NotificationButton, remember_result
from ddm.online_ui import show_result
from ddm.widgets import Sidebar


class NotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.owner = QWidget()
        self.owner.resize(900, 800)
        layout = QVBoxLayout(self.owner)
        self.button = NotificationButton(self.owner)
        layout.addWidget(self.button, 0, Qt.AlignTop)
        layout.addStretch()
        self.owner.sidebar = Mock(notification_button=self.button)
        self.center = self.button.center
        self.owner.show()
        self.app.processEvents()
        self.addCleanup(self.owner.close)

    def open(self):
        self.button.click()
        self.app.processEvents()
        self.assertTrue(self.center.isVisible())

    def test_all_results_survive_toast_dismissal_and_hidden_owner(self):
        show_result(self.owner, '<b>原样文本</b>', kind='warning')
        self.owner._result_notice.dismiss(animate=False)
        self.owner.hide()
        show_result(self.owner, '隐藏时完成的操作')
        self.assertEqual([entry.message for entry in self.center.entries],
                         ['<b>原样文本</b>', '隐藏时完成的操作'])
        self.assertTrue(all(entry.unread for entry in self.center.entries))
        self.owner._closing = True
        show_result(self.owner, '退出时不再写入')
        self.assertEqual(len(self.center.entries), 2)

    def test_unread_indicator_open_read_and_new_while_open(self):
        self.center.add('新通知')
        self.assertEqual(self.button._unread, 1)
        self.assertIn('1 条未读', self.button.accessibleName())
        self.open()
        self.assertEqual(self.button._unread, 0)
        self.center.add('正在查看时抵达')
        self.assertEqual(self.button._unread, 0)
        QTest.keyClick(self.center, Qt.Key_Escape)
        self.assertFalse(self.center.isVisible())
        self.assertFalse(self.button.isChecked())
        self.center.add('收起后抵达')
        self.assertEqual(self.button._unread, 1)

    def test_child_dialog_notifications_reach_the_same_session(self):
        dialog = QWidget(self.owner, Qt.Dialog)
        dialog.show()
        self.addCleanup(dialog.close)
        show_result(dialog, '插件安装完成')
        self.assertEqual([entry.message for entry in self.center.entries], ['插件安装完成'])
        dialog._result_notice.dismiss(animate=False)
        self.owner._closing = True
        show_result(dialog, '退出时的子窗口消息')
        self.assertEqual(len(self.center.entries), 1)

    def test_memory_only_and_no_limit_or_widgets_while_closed(self):
        for number in range(120):
            self.center.add(str(number))
        self.assertEqual(len(self.center.entries), 120)
        self.assertFalse(self.center.rows)
        other = NotificationButton(self.owner)
        self.assertFalse(other.center.entries)
        self.center.clear()
        self.assertFalse(self.center.entries)
        self.assertEqual(self.button._unread, 0)

    def test_history_action_does_not_delete_entry_and_delete_does_not_activate(self):
        callback = Mock()
        self.center.add('操作说明', callback=callback, action='执行操作')
        self.open()
        entry = self.center.entries[0]
        row = self.center.rows[entry]
        QTest.mouseClick(row.action, Qt.LeftButton)
        callback.assert_called_once_with()
        self.assertIn(entry, self.center.entries)
        self.open()
        QTest.mouseClick(row.remove_button, Qt.LeftButton)
        callback.assert_called_once_with()
        self.assertFalse(self.center.entries)
        self.assertTrue(self.center.empty.isVisible())
        self.assertFalse(self.center.clear_button.isEnabled())

    def test_update_deduplication_is_per_session(self):
        self.center.add('更新', key=('update', '0.5'))
        self.center.add('更新', key=('update', '0.5'))
        self.assertEqual(len(self.center.entries), 1)
        self.center.clear()
        self.center.add('更新', key=('update', '0.5'))
        self.assertFalse(self.center.entries)
        self.center.add('另一个更新', key=('update', '0.6'))
        self.assertEqual(len(self.center.entries), 1)

    def test_recording_history_keeps_full_path_without_toast_lifetime_dependency(self):
        path = 'C:/recordings/很长的目录/' + '文件名' * 30 + '.mp4'
        remember_result(self.owner, '已保存录制：', file_path=path)
        entry = self.center.entries[0]
        self.assertIn(path, entry.message)
        self.assertEqual(entry.action, '打开文件位置')
        with patch('ddm.notification_center.reveal_file') as reveal:
            entry.callback()
            reveal.assert_called_once_with(path)

    def test_paper_animation_renders_then_removes_and_can_be_interrupted(self):
        self.center.add('删除这张通知纸片', callback=Mock())
        self.open()
        entry = self.center.entries[0]
        row = self.center.rows[entry]
        original_height = row.height()
        with patch.object(motion, 'enabled', return_value=True):
            row.remove()
            row.animation.setCurrentTime(120)
            self.assertGreater(row._progress, 0)
            self.assertLess(row._progress, 1)
            self.assertFalse(row.grab().isNull())
            self.assertEqual(row.height(), original_height)
            self.assertIn(entry, self.center.entries)
            row.remove()
            row.animation.setCurrentTime(240)
            self.assertNotIn(entry, self.center.entries)
        entry.callback.assert_not_called()
        self.center.add('清空时已有')
        self.center.add('清空时已有2')
        with patch.object(motion, 'enabled', return_value=True):
            self.center.clear()
            self.center.add('清空后新到达')
            self.center.hide()
        self.assertEqual([entry.message for entry in self.center.entries], ['清空后新到达'])

    def test_resize_move_and_owner_hide(self):
        self.center.add('长通知' * 30)
        self.open()
        for width in (300, 900):
            self.owner.resize(width, 800)
            self.app.processEvents()
            self.assertLessEqual(self.center.width(), width - 24)
            self.assertGreater(self.center.y(), self.button.mapToGlobal(self.button.rect().bottomLeft()).y())
            self.assertGreaterEqual(self.center.rows[self.center.entries[0]].message.height(),
                self.center.rows[self.center.entries[0]].message.heightForWidth(
                    self.center.rows[self.center.entries[0]].message.width()))
        self.owner.hide()
        self.assertFalse(self.center.isVisible())

    def test_sidebar_button_geometry_and_orientation(self):
        sidebar = Sidebar([{'room_id': '1', 'uname': '测试'}])
        sidebar.resize(248, 800)
        sidebar.show()
        self.addCleanup(sidebar.close)
        for side in ('left', 'top', 'left'):
            sidebar.set_side(side)
            self.app.processEvents()
            button = sidebar.notification_button
            self.assertEqual(button.text(), '')
            if side == 'left':
                self.assertEqual(button.width(), 22)
                self.assertIs(button.parentWidget(), sidebar.status_row)
                sidebar.count_label.setText('关注中 · 107')
                self.app.processEvents()
                self.assertGreaterEqual(sidebar.count_label.width(),
                    sidebar.count_label.fontMetrics().horizontalAdvance(sidebar.count_label.text()))
                self.assertFalse(button.geometry().intersects(sidebar.count_label.geometry()))
            else:
                self.assertIs(button.parentWidget(), sidebar._bar_row)
            sidebar.set_collapsed(True, animate=False)
            self.assertFalse(button.isVisible())
            sidebar.set_collapsed(False, animate=False)
            self.assertTrue(button.isVisible())

    def test_card_style_scrollbar_and_four_corners_follow_theme(self):
        self.addCleanup(theme.apply, theme.mode())
        sidebar = Sidebar([{'room_id': '1'}])
        sidebar.ensurePolished()
        self.addCleanup(sidebar.close)
        self.app.processEvents()
        for index in range(15):
            self.center.add('主播开播了 ' + str(index), kind='live', callback=Mock(),
                            action='放入画面墙', rooms=[{'room_id': '1', 'uname': '主播'}])
        self.open()
        for mode in ('light', 'dark'):
            theme.apply(mode)
            self.app.processEvents()
            bar = self.center.scroll.verticalScrollBar()
            self.assertTrue(bar.isVisible())
            self.assertGreater(bar.maximum(), 0)
            self.assertEqual(bar.sizeHint().width(), sidebar.scroll.verticalScrollBar().sizeHint().width())
            self.assertEqual(bar.width(), theme.SCROLLBAR_SIZE)
            for width in (300, 900):
                self.owner.resize(width, 800)
                self.app.processEvents()
                panel = self.center.grab().toImage()
                for point in (QPoint(0, 0), QPoint(self.center.width() - 1, 0),
                              QPoint(0, self.center.height() - 1), self.center.rect().bottomRight()):
                    self.assertFalse(self.center.mask().contains(point))
                    scale = panel.devicePixelRatio()
                    self.assertEqual(panel.pixelColor(round(point.x() * scale),
                                                       round(point.y() * scale)).alpha(), 0)
            row = self.center.rows[self.center.entries[-1]]
            self.assertIn('1', row.avatars)
            self.assertEqual(row.category.objectName(), 'NoticeHeading')
            self.assertEqual(row.message.objectName(), 'NoticeText')
            self.assertEqual(row.action.objectName(), 'PrimaryButton')
            self.assertEqual(row.remove_button.y(), 14 + row.frameWidth())
            self.assertGreater(row.action.y(), row.message.geometry().bottom())
            rendered = row.grab().toImage()
            scale = rendered.devicePixelRatio()
            self.assertEqual(rendered.pixelColor(round(row.action.x() * scale),
                round(row.action.y() * scale)).name(), theme.qcolor(theme.ELEVATED).name())


if __name__ == '__main__':
    unittest.main()
