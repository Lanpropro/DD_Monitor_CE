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
from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEvent, QPoint, Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from ddm import motion, theme
from ddm.config import DEFAULT_SETTINGS
from ddm.dialogs import NotificationSettingsPage, SettingsDialog
from ddm.notification_center import NotificationButton, remember_result
from ddm.online_ui import show_result, UpdateNotice
from ddm.widgets import Sidebar
from ddm.ui import NavigationButton, SegmentedControl, SettingsSlider, SettingsValueLabel
from ddm.settings_layout import SettingsSection


class NotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        if cls.app.platformName() == 'offscreen':
            font = Path('C:/Windows/Fonts/msyh.ttc')
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
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
        self.addCleanup(self.dispose, self.owner)

    def dispose(self, widget):
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def open(self):
        self.button.click()
        self.app.processEvents()
        self.assertTrue(self.center.isVisible())

    def wait_until(self, condition, timeout):
        deadline = QDeadlineTimer(timeout)
        while not condition() and not deadline.hasExpired():
            QTest.qWait(10)
        self.assertTrue(condition())

    def test_settings_navigation_places_notifications_before_shortcuts(self):
        dialog = SettingsDialog({}, {}, preview=True)
        self.addCleanup(self.dispose, dialog)
        keys = [dialog.nav.item(i).data(Qt.UserRole) for i in range(dialog.nav.count())]
        self.assertEqual(keys, ['general', 'appearance', 'danmaku', 'recording',
                                'notifications', 'shortcuts', 'streamer_defaults', 'tray',
                                'plugins', 'updates', 'diagnostics'])
        self.assertFalse(dialog._loaded_pages)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['tray'])
        self.assertEqual(dialog.stack.currentIndex(), SettingsDialog.PAGE_INDEX['tray'])
        self.assertIn('托盘行为', [label.text() for label in
                              dialog.stack.currentWidget().findChildren(QLabel)])
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['notifications'])
        self.assertIs(dialog.stack.currentWidget(), dialog.notification_page)
        dialog.notification_page._checks['live_alert'].setChecked(False)
        dialog.notification_page._checks['notifications_enabled'].setChecked(False)
        dialog.notification_page._checks['notice_persist_warning'].setChecked(True)
        self.assertFalse(dialog.settings()['live_alert'])
        self.assertFalse(dialog.settings()['notifications_enabled'])
        self.assertTrue(dialog.settings()['notice_persist_warning'])
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['shortcuts'])
        self.assertIs(dialog.stack.currentWidget(), dialog.shortcut_page)
        self.assertEqual(dialog.shortcuts(), dialog.shortcut_page.values())
        self.assertEqual(set(dialog._loaded_pages), {4, 5, SettingsDialog.PAGE_INDEX['tray']})
        dialog.nav.setCurrentRow(4)
        dialog._reset_current()
        self.assertEqual(dialog.notification_page.values(), {
            **{key: DEFAULT_SETTINGS[key] for key, _label in NotificationSettingsPage.ITEMS},
            'notice_banner_enabled': DEFAULT_SETTINGS['notice_banner_enabled'],
            'notice_banner_blur': DEFAULT_SETTINGS['notice_banner_blur']})

    def test_banner_display_switch_preserves_blur_and_uses_existing_autosave(self):
        dialog = SettingsDialog({'notice_banner_blur': 30}, {}, preview=True)
        self.addCleanup(self.dispose, dialog)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['notifications'])
        page = dialog.notification_page
        self.assertTrue(page.banner_enabled.isChecked())
        requested = []
        dialog.auto_save.requested.connect(requested.append)
        dialog.auto_save.start()
        self.addCleanup(dialog.auto_save.stop)
        page.banner_enabled.click()
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['settings'], {'notice_banner_enabled': False})
        self.assertFalse(page.banner_preview.banner_enabled)
        self.assertFalse(page.banner_blur.isEnabled())
        self.assertEqual(page.banner_blur.value(), 30)
        saved = page.values()
        reopened = NotificationSettingsPage(saved)
        self.addCleanup(self.dispose, reopened)
        self.assertFalse(reopened.banner_enabled.isChecked())
        self.assertEqual(reopened.banner_blur.value(), 30)
        page.banner_enabled.click()
        self.assertTrue(page.banner_preview.banner_enabled)
        self.assertTrue(page.banner_blur.isEnabled())
        self.assertEqual(page.banner_blur.value(), 30)
        page.reset()
        self.assertTrue(page.banner_enabled.isChecked())
        self.assertEqual(page.banner_blur.value(), DEFAULT_SETTINGS['notice_banner_blur'])

    def test_banner_display_switch_updates_existing_toast_and_history_without_losing_actions(self):
        from PySide6.QtGui import QPixmap, QColor
        from ddm import images, room_artwork
        from ddm.notification_center import NoticeEntry, NoticeRow
        from ddm.online_ui import ResultNotice
        picture = QPixmap(160, 90)
        picture.fill(QColor('#e06020'))
        room = {'room_id': '1001', 'uname': '测试主播'}
        window = QWidget()
        # Use an identifiable clear image here; blur strength is tested separately.
        window.settings = {'notice_banner_enabled': True, 'notice_banner_blur': 0}
        window.resize(800, 500)
        window.show()
        self.addCleanup(self.dispose, window)
        callback = Mock()
        with patch.object(images, 'load_room_banner', return_value=picture), \
                patch.object(images, 'load_room_cover', return_value=picture):
            notice = ResultNotice(window)
            notice.show_message('背景开关测试', [room], kind='live', persistent=True, on_click=callback)
            row = NoticeRow(NoticeEntry('背景开关测试', 'live', '12:00', callback=callback, rooms=(room,)), window)
        row.resize(360, row.sizeHint().height())
        row.show()
        self.app.processEvents()
        for card in (notice, row):
            self.assertTrue(card.property('roomBackdrop'))
        window.settings['notice_banner_enabled'] = False
        for card in (notice, row):
            room_artwork.style_room_notice(card, card.artwork)
        with patch.object(room_artwork, 'paint_room_background') as paint:
            self.app.processEvents()
            for card in (notice, row):
                self.assertFalse(card.property('roomBackdrop'))
                card.grab()
            paint.assert_not_called()
        notice.set_room_artwork('1001', picture, 'banners')
        row.set_room_artwork('1001', picture, 'banners')
        self.assertFalse(notice.property('roomBackdrop'))
        self.assertIs(notice._on_click, callback)
        self.assertIs(row.entry.callback, callback)
        window.settings['notice_banner_enabled'] = True
        for card in (notice, row):
            room_artwork.style_room_notice(card, card.artwork)
        for card in (notice, row):
            self.assertTrue(card.property('roomBackdrop'))
        with patch.object(room_artwork, 'paint_room_background', wraps=room_artwork.paint_room_background) as paint:
            notice.grab()
            row.grab()
            self.assertGreaterEqual(paint.call_count, 2)

    def test_banner_blur_settings_roundtrip_and_reset(self):
        dialog = SettingsDialog({'notice_banner_blur': 30}, {}, preview=True)
        self.addCleanup(self.dispose, dialog)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['notifications'])
        page = dialog.notification_page
        self.assertEqual(page.banner_blur.value(), 30)
        for strength in (0, 8, 40):
            page.banner_blur.setValue(strength)
            saved = dialog.settings()
            self.assertEqual(saved['notice_banner_blur'], strength)
            self.assertEqual(page.banner_preview.strength, strength)
            self.assertEqual(page.banner_blur_value.text(), str(strength) if strength else '关闭')
            reopened = NotificationSettingsPage(saved)
            self.addCleanup(self.dispose, reopened)
            self.assertEqual(reopened.banner_blur.value(), strength)
        dialog._reset_current()
        self.assertEqual(page.values()['notice_banner_blur'], DEFAULT_SETTINGS['notice_banner_blur'])

    def test_notification_switches_support_keyboard_click_and_explicit_states(self):
        page = NotificationSettingsPage({})
        self.addCleanup(self.dispose, page)
        page.resize(500, 650)
        page.show()
        self.app.processEvents()
        for key, box in page._checks.items():
            before = box.isChecked()
            target = box.buttons['auto' if before else 'manual'] if isinstance(box, SegmentedControl) else box
            target.setFocus()
            QTest.keyClick(target, Qt.Key_Space)
            self.assertEqual(box.isChecked(), not before)
            expected = ('已启用' if box.isChecked() else '已关闭') if not isinstance(box, SegmentedControl) else (
                '手动关闭' if box.isChecked() else '自动收起')
            self.assertEqual(page._states[key].text(), expected)
            target = box.buttons['manual' if before else 'auto'] if isinstance(box, SegmentedControl) else box
            QTest.mouseClick(target, Qt.LeftButton, pos=target.rect().center())
            self.assertEqual(box.isChecked(), before)
            self.assertTrue(box.accessibleName())
            self.assertTrue(box.accessibleDescription())
            self.assertEqual(target.focusPolicy(), Qt.StrongFocus)
            if isinstance(box, SegmentedControl):
                self.assertTrue(page._states[key].isHidden())

    def test_windows_recording_switch_round_trips_through_autosave_and_reset(self):
        dialog = SettingsDialog({}, {}, preview=True)
        self.addCleanup(self.dispose, dialog)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['notifications'])
        page = dialog.notification_page
        requested = []
        dialog.auto_save.requested.connect(requested.append)
        dialog.auto_save.start()
        self.addCleanup(dialog.auto_save.stop)
        control = page._checks['notice_windows_recording']
        self.assertFalse(control.isChecked())
        control.click()
        dialog.auto_save.flush()
        self.assertIs(requested[-1]['settings']['notice_windows_recording'], True)
        saved = NotificationSettingsPage(dialog.settings())
        self.addCleanup(self.dispose, saved)
        self.assertTrue(saved._checks['notice_windows_recording'].isChecked())
        saved.reset()
        self.assertFalse(saved.values()['notice_windows_recording'])

    def test_notification_master_switch_hides_float_but_keeps_history(self):
        self.owner.settings = {'notifications_enabled': False}
        show_result(self.owner, '被总开关隐藏的通知')
        self.assertEqual([entry.message for entry in self.center.entries], ['被总开关隐藏的通知'])
        self.assertFalse(hasattr(self.owner, '_result_notice'))

    def test_notification_settings_cards_fit_themes_and_small_dialog(self):
        previous = theme.mode()
        self.addCleanup(theme.apply, previous)
        dialog = SettingsDialog({}, {}, preview=True)
        self.addCleanup(self.dispose, dialog)
        dialog.nav.setCurrentRow(4)
        dialog.show()
        page = dialog.notification_page
        for mode in ('light', 'dark'):
            theme.apply(mode)
            for size in ((720, 500), (900, 650)):
                dialog.resize(*size)
                self.app.processEvents()
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                page.scroll.verticalScrollBar().setValue(0)
                preview = page.banner_preview
                self.assertTrue(page.scroll.viewport().rect().contains(
                    preview.mapTo(page.scroll.viewport(), preview.rect().center())))
                self.assertLess(preview.mapTo(page, QPoint()).y(),
                                page._checks['live_alert'].mapTo(page, QPoint()).y())
                page.banner_blur.setValue(0)
                sharp = preview.grab().toImage()
                page.banner_blur.setValue(40)
                self.assertNotEqual(preview.grab().toImage(), sharp)
                for key, box in page._checks.items():
                    state = page._states[key]
                    if isinstance(box, SegmentedControl):
                        self.assertTrue(state.isHidden())
                        continue
                    self.assertLess(state.mapTo(page, QPoint(state.width(), 0)).x(),
                                    box.mapTo(page, QPoint()).x()+1)
                    self.assertGreaterEqual(state.height(), state.fontMetrics().height())
                last = page._checks['notice_persist_info']
                page.scroll.ensureWidgetVisible(last)
                self.app.processEvents()
                rect = page.scroll.viewport().rect()
                self.assertTrue(rect.contains(last.mapTo(page.scroll.viewport(), last.rect().center())))

    def test_notification_sections_keep_compact_controls_readable_at_large_font_and_narrow_width(self):
        previous = dict(theme._preferences)
        self.addCleanup(theme.configure_appearance, previous)
        for font_size in (13, 20):
            theme.configure_appearance({'appearance_font_size': font_size})
            page = NotificationSettingsPage({})
            self.addCleanup(self.dispose, page)
            page.setStyleSheet(theme.qss())
            for width in (500, 1200):
                page.resize(width, 780)
                page.show()
                for _ in range(3):
                    self.app.processEvents()
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                self.assertEqual([card.findChild(QLabel, 'SettingsSectionTitle').text()
                                  for _key, card, _wide in page.sections.entries],
                                 ['背景预览', '接收通知', '停留方式'])
                self.assertTrue(all(isinstance(card, SettingsSection) for _key, card, _wide in page.sections.entries))
                self.assertIsInstance(page.banner_blur, SettingsSlider)
                self.assertEqual(page.banner_blur.width(), 160)
                self.assertIsInstance(page.banner_blur_value, SettingsValueLabel)
                self.assertTrue(page.banner_blur_value.font().bold())
                self.assertTrue(page.sections.section('background').isAncestorOf(page.banner_preview))
                preview = page.banner_preview
                example = preview.parentWidget()
                self.assertEqual(preview.height(), 100)
                self.assertEqual(preview.width(), min(260, example.width()))
                self.assertEqual(preview.mapTo(example, preview.rect().topRight()).x(), example.width() - 1)
                self.assertTrue(example.rect().contains(preview.geometry()))
                self.assertFalse(any('Banner' in label.text() for label in page.findChildren(QLabel)))
                for key, box in page._checks.items():
                    card = page.sections.section('persistence' if key.startswith('notice_persist_') else 'live')
                    self.assertTrue(card.rect().contains(box.mapTo(card, box.rect().bottomRight())), (font_size, width, key))
                    self.assertNotEqual(page._states[key].objectName(), 'NotificationSettingsState')
                    if isinstance(box, SegmentedControl):
                        for button in box.buttons.values():
                            self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()) + 8)
                    else:
                        state = page._states[key]
                        self.assertTrue(state.isVisible())
                        self.assertLess(state.mapTo(card, state.rect().topRight()).x(), box.mapTo(card, QPoint()).x())
            page.hide()

    def test_banner_preview_can_shrink_below_preferred_width_and_remains_right_aligned(self):
        from ddm.settings_notifications import NoticeBlurPreview
        parent = QWidget()
        self.addCleanup(self.dispose, parent)
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        preview = NoticeBlurPreview()
        layout.addWidget(preview, 0, Qt.AlignRight)
        for width in (420, 180, 300):
            parent.resize(width, 120)
            parent.show()
            self.app.processEvents()
            self.assertEqual(preview.size().height(), 100)
            self.assertEqual(preview.width(), min(260, parent.width()))
            self.assertEqual(preview.geometry().right(), parent.width() - 1)
            self.assertTrue(parent.rect().contains(preview.geometry()))

    def test_notification_retention_segments_trigger_existing_autosave_contract(self):
        dialog = SettingsDialog({}, {}, preview=True)
        self.addCleanup(self.dispose, dialog)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['notifications'])
        page = dialog.notification_page
        requested = []
        dialog.auto_save.requested.connect(requested.append)
        dialog.auto_save.start()
        self.addCleanup(dialog.auto_save.stop)
        control = page._checks['notice_persist_warning']
        control.buttons['manual'].click()
        self.assertTrue(dialog.auto_save.timer.isActive())
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['settings']['notice_persist_warning'], True)
        dialog.auto_save.acknowledge()
        control.buttons['auto'].click()
        dialog.auto_save.flush()
        self.assertEqual(requested[-1]['settings']['notice_persist_warning'], False)

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

    def test_outside_close_marks_only_its_own_record_read(self):
        callback = Mock()
        show_result(self.owner, '重复文字', on_click=callback, persistent=True)
        first = self.owner._result_notice
        first_entry = self.center.entries[-1]
        show_result(self.owner, '重复文字', persistent=True)
        second_entry = self.center.entries[-1]
        first.findChild(QPushButton, 'NoticeClose').click()
        self.assertEqual(self.center.entries, [first_entry, second_entry])
        self.assertFalse(first_entry.unread)
        self.assertTrue(second_entry.unread)
        self.assertEqual(self.button._unread, 1)
        callback.assert_not_called()

    def test_outside_body_click_marks_history_read_with_or_without_action(self):
        for callback in (None, Mock()):
            show_result(self.owner, '外侧通知', on_click=callback, persistent=True)
            notice = self.owner._result_notice
            entry = self.center.entries[-1]
            QTest.mouseClick(notice, Qt.LeftButton, pos=QPoint(8, 8))
            self.assertIn(entry, self.center.entries)
            self.assertFalse(entry.unread)
            self.assertEqual(self.button._unread, 0)
            if callback is not None:
                callback.assert_called_once()

    def test_timeout_preserves_record_and_handling_after_clear_is_safe(self):
        show_result(self.owner, '未处理通知')
        self.owner._result_notice.timer.timeout.emit()
        self.assertEqual(len(self.center.entries), 1)
        show_result(self.owner, '清空后的旧浮窗', persistent=True)
        notice = self.owner._result_notice
        self.center.clear()
        self.center.add('清空后新通知')
        notice.findChild(QPushButton, 'NoticeClose').click()
        self.assertEqual([entry.message for entry in self.center.entries], ['清空后新通知'])

    def test_outside_update_action_keeps_one_handled_deduplicated_record(self):
        notice = UpdateNotice(self.owner)
        self.addCleanup(self.dispose, notice)
        entry = self.center.add('版本更新', key=('update', 'test'))
        self.assertIs(self.center.add('版本更新', key=('update', 'test')), entry)
        notice.track_history((self.center, entry))
        notice.show_offer({'version': 'test'}, persistent=True)
        notice.action.click()
        self.assertEqual(self.center.entries, [entry])
        self.assertFalse(entry.unread)
        self.center.add('版本更新', key=('update', 'test'))
        self.assertEqual(self.center.entries, [entry])
        self.assertFalse(entry.unread)

    def test_unread_indicator_open_read_and_new_while_open(self):
        self.assertEqual(self.center.title.text(), '通知')
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

    def test_menu_header_and_card_metadata_follow_active_history(self):
        self.open()
        empty_height = self.center.height()
        self.assertTrue(self.center.empty.isVisible())
        self.assertEqual(self.center.summary.text(), '本次启动 · 0 条')
        self.assertLess(empty_height, 200)

        entry = self.center.add('更新已准备好', kind='update', callback=Mock())
        self.app.processEvents()
        row = self.center.rows[entry]
        self.assertEqual(self.center.summary.text(), '本次启动 · 1 条')
        self.assertFalse(self.center.empty.isVisible())
        self.assertGreater(self.center.height(), empty_height)
        self.assertLess(self.center.height(), 300)
        self.assertEqual(row.category.text(), '版本更新')
        self.assertEqual(row.timestamp.text(), entry.time[:5])
        self.assertEqual(row.timestamp.toolTip(), entry.time)
        self.assertLess(row.timestamp.geometry().bottom(), row.message.y())

        clear = self.center.clear_button
        close = self.center.close_button
        self.assertIsInstance(clear, NavigationButton)
        self.assertIsInstance(close, NavigationButton)
        self.assertEqual(clear.size(), close.size())
        self.assertEqual(clear.objectName(), close.objectName())
        self.assertEqual(clear.text(), '')
        self.assertEqual(clear.accessibleName(), '清空通知')
        QTest.keyClick(close, Qt.Key_Space)
        self.assertFalse(self.center.isVisible())
        self.assertEqual(self.center.entries, [entry])
        self.open()
        with patch.object(motion, 'enabled', return_value=True):
            QTest.mouseClick(clear, Qt.LeftButton)
            self.assertTrue(self.center.isVisible())
            self.wait_until(lambda: not self.center.isVisible(), 500)
        self.assertFalse(self.button.isChecked())
        self.assertFalse(self.center.entries)
        self.open()
        self.app.processEvents()
        self.assertTrue(self.center.empty.isVisible())
        self.assertEqual(self.center.summary.text(), '本次启动 · 0 条')
        self.assertEqual(self.center.height(), empty_height)

    def test_menu_header_buttons_share_hover_surface(self):
        self.addCleanup(theme.apply, theme.mode())
        self.owner.settings = {'settings_glass_enabled': True}
        self.center.add('操作完成')
        self.open()

        def surface_pixel(button):
            self.app.processEvents()
            image = button.grab().toImage()
            scale = image.devicePixelRatio()
            return image.pixelColor(round(5 * scale), round(button.height() / 2 * scale))

        for mode in ('dark', 'light'):
            theme.apply(mode)
            hovered = []
            for button in (self.center.clear_button, self.center.close_button):
                with self.subTest(mode=mode, button=button.accessibleName()):
                    QTest.mouseMove(self.center, QPoint(5, self.center.height() // 2))
                    idle = surface_pixel(button)
                    QTest.mouseMove(button, button.rect().center())
                    hovered.append(surface_pixel(button))
                    self.assertNotEqual(idle, hovered[-1])
            self.assertEqual(*hovered)

    def test_menu_material_keeps_corners_clear_and_follows_opacity_without_native_blur(self):
        self.owner.settings = {'settings_glass_enabled': False, 'settings_glass_opacity': 0}
        for _ in range(6):
            self.center.add('操作完成')

        def gutter_alpha():
            image = self.center.grab().toImage()
            for point in (image.rect().topLeft(), image.rect().topRight(),
                          image.rect().bottomLeft(), image.rect().bottomRight()):
                self.assertEqual(image.pixelColor(point).alpha(), 0, point)
            scale = image.devicePixelRatio()
            return image.pixelColor(round(6 * scale), round(self.center.height() / 2 * scale)).alpha()

        with patch('ddm.notification_center.apply_blur', return_value=True, create=True) as native_blur:
            self.open()
            self.assertEqual(gutter_alpha(), 255)

            self.center.hide()
            self.owner.settings['settings_glass_enabled'] = True
            self.open()
            translucent = gutter_alpha()
            self.assertGreaterEqual(translucent, 190)
            self.assertLess(translucent, 210)

            self.center.hide()
            self.owner.settings.pop('settings_glass_opacity')
            self.open()
            self.assertGreaterEqual(gutter_alpha(), 232)
            self.assertLess(gutter_alpha(), 246)

            self.center.hide()
            self.owner.settings['settings_glass_opacity'] = 100
            self.open()
            self.assertEqual(gutter_alpha(), 255)

            self.center.hide()
            self.owner.settings['settings_glass_enabled'] = False
            self.open()
            self.assertEqual(gutter_alpha(), 255)
            native_blur.assert_not_called()

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
        self.assertEqual(entry.message, '已保存录制：' + Path(path).name)
        self.assertEqual(entry.file_path, path)
        self.assertEqual(entry.action, '打开文件位置')
        with patch('ddm.notification_center.reveal_file') as reveal:
            entry.callback()
            reveal.assert_called_once_with(path)

    def test_single_removal_fades_and_closes_the_gap(self):
        remaining = self.center.add('保留的通知')
        entry = self.center.add('删除这条通知', callback=Mock())
        self.open()
        row = self.center.rows[entry]
        following = self.center.rows[remaining]
        original_height = row.height()
        original_y = following.y()
        geometry = self.center.geometry()
        with patch.object(motion, 'enabled', return_value=True):
            QTest.mouseClick(row.remove_button, Qt.LeftButton)
            row.animation.setCurrentTime(60)
            self.center.list_layout.activate()
            self.assertGreater(row._progress, 0)
            self.assertLess(row._progress, 1)
            self.assertFalse(row.grab().isNull())
            self.assertLess(row.height(), original_height)
            self.assertLess(following.y(), original_y)
            self.assertIn(entry, self.center.entries)
            row.remove()
            self.wait_until(lambda: entry not in self.center.entries, 500)
        self.assertEqual(self.center.geometry(), geometry)
        self.assertIn('1 条', self.center.summary.text())
        entry.callback.assert_not_called()

    def test_clear_button_closes_with_the_last_card(self):
        for animate in (True, False):
            with self.subTest(animate=animate), patch.object(motion, 'enabled', return_value=animate):
                first = self.center.add('第一条')
                second = self.center.add('第二条')
                self.open()
                geometry = self.center.geometry()
                row = self.center.rows[first]
                last_row = self.center.rows[second]
                height = row.height()
                QTest.mouseClick(self.center.clear_button, Qt.LeftButton)
                if animate:
                    self.assertTrue(self.center.isVisible())
                    self.assertFalse(self.center.clear_button.isEnabled())
                    row._close_timer.stop()
                    last_row._close_timer.stop()
                    row.animation.setCurrentTime(60)
                    self.assertLess(row._progress, 1)
                    self.assertGreater(row._progress, 0)
                    self.assertEqual(row.height(), height)
                    row.animation.setCurrentTime(row.animation.duration())
                    self.assertEqual(self.center.entries, [second])
                    self.assertTrue(self.center.isVisible())
                    self.assertEqual(self.center.geometry(), geometry)
                    last_row.animation.setCurrentTime(last_row.animation.duration())
                self.assertFalse(self.center.isVisible())
                self.assertFalse(self.center.entries)
                self.assertEqual(self.center.summary.text(), '本次启动 · 0 条')
                self.assertFalse(self.button.isChecked())
                self.open()
                self.assertEqual(self.center.empty.text(), '暂无通知')
                self.center.hide()

    def test_clear_keeps_new_notices_even_when_a_key_is_reused(self):
        self.center.add('清空时已有', key='fixture')
        self.center.add('清空时已有2')
        self.open()
        with patch.object(motion, 'enabled', return_value=True):
            QTest.mouseClick(self.center.clear_button, Qt.LeftButton)
            self.center.add('清空后新到达', key='fixture', replace=True)
            self.wait_until(lambda: not self.center.isVisible(), 500)
        self.assertEqual([entry.message for entry in self.center.entries], ['清空后新到达'])
        self.assertEqual(self.button._unread, 1)

    def test_manual_close_finishes_clear_before_reopening(self):
        with patch.object(motion, 'enabled', return_value=True):
            self.center.add('清空时已有')
            self.open()
            QTest.mouseClick(self.center.clear_button, Qt.LeftButton)
            self.assertTrue(self.center.isVisible())
            QTest.mouseClick(self.center.close_button, Qt.LeftButton)
            self.assertFalse(self.center.isVisible())
            self.assertFalse(self.center.entries)
            self.open()
            QTest.qWait(250)
            self.assertTrue(self.center.isVisible())
            self.assertEqual(self.center.empty.text(), '暂无通知')

    def test_recording_paths_keep_cards_and_actions_inside_viewport(self):
        previous = theme.mode()
        self.addCleanup(theme.apply, previous)
        path = 'F:\\CodexAppManager\\Code\\DD_Monitor_CE\\videos\\' + '主播Shiori_' * 12 + '.mp4'
        room = {'room_id': '1001', 'uname': '主播Shiori'}
        with patch('ddm.images.load_cached_avatar', return_value=None), \
                patch('ddm.images.load_room_avatar', return_value=None):
            for message in ('已保存录制：', '已保存即时回放：'):
                remember_result(self.owner, message, file_path=path, rooms=[room])
            self.open()
            for mode in ('dark', 'light'):
                theme.apply(mode)
                for width in (300, 900, 400):
                    self.owner.resize(width, 800)
                    self.app.processEvents()
                    viewport = self.center.scroll.viewport()
                    content = self.center.scroll.widget()
                    self.assertLessEqual(content.width(), viewport.width())
                    for row in self.center.rows.values():
                        self.assertLessEqual(row.geometry().right(), content.width())
                        self.assertGreaterEqual(row.action.x(), 0)
                        self.assertLess(row.action.geometry().right(), row.width())
                        self.assertLess(row.remove_button.geometry().right(), row.width())
                        self.assertLessEqual(row.message.geometry().right(), row.remove_button.x())
                        self.assertGreaterEqual(row.message.height(), row.message.heightForWidth(row.message.width()))
                        self.assertGreaterEqual(row.height(), row.layout().totalHeightForWidth(row.width()))
                        self.assertIn(Path(path.replace('\\', '/')).name, row.message.text())
                        self.assertNotIn('CodexAppManager', row.message.text())
                        self.assertEqual(row.toolTip(), path)
                        self.assertEqual(row.message.toPlainText(), row.entry.message)
                        self.assertLessEqual(row.message.document().size().height(), row.message.viewport().height())
                        block = row.message.document().begin()
                        while block.isValid():
                            text_layout = block.layout()
                            for index in range(text_layout.lineCount()):
                                self.assertLessEqual(text_layout.lineAt(index).naturalTextWidth(),
                                                     row.message.viewport().width() + 1)
                            block = block.next()
                        row.message.selectAll()
                        self.assertEqual(row.message.textCursor().selectedText(), row.entry.message)

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
                self.assertEqual(button.width(), 34)
                self.assertIs(button.parentWidget(), sidebar.navigation.rail)
                sidebar.navigation.count.setText('107')
                self.app.processEvents()
                self.assertGreaterEqual(sidebar.navigation.count.width(),
                    sidebar.navigation.count.fontMetrics().horizontalAdvance('107'))
            else:
                self.assertIs(button.parentWidget(), sidebar._bar_row)
            sidebar.set_collapsed(True, animate=False)
            self.assertTrue(button.isVisible())
            sidebar.set_collapsed(False, animate=False)
            self.assertTrue(button.isVisible())

    def test_bottom_dock_opens_upward_and_keeps_newest_message_first(self):
        self.button.setProperty('dockRail', True)
        layout = self.owner.layout()
        layout.removeWidget(self.button)
        layout.addWidget(self.button, 0, Qt.AlignBottom)
        self.center.add('较早消息')
        self.center.add('最新消息')
        self.app.processEvents()
        self.open()
        top = self.button.mapToGlobal(QPoint()).y()
        self.assertLess(self.center.frameGeometry().bottom(), top)
        self.assertGreaterEqual(self.center.height(), 240)
        self.assertTrue(self.owner.screen().availableGeometry().contains(self.center.frameGeometry()))
        rows = sorted(self.center.rows.values(), key=lambda row: row.y())
        self.assertEqual([row.entry.message for row in rows], ['最新消息', '较早消息'])

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
                self.assertGreater(bar.maximum(), 0)
                for item in self.center.rows.values():
                    self.assertGreaterEqual(item.height(), item.layout().totalHeightForWidth(item.width()))
                    self.assertGreaterEqual(item.message.height(), item.message.heightForWidth(item.message.width()))
                rows = sorted(self.center.rows.values(), key=lambda item: item.y())
                for first, second in zip(rows, rows[1:]):
                    self.assertLess(first.geometry().bottom(), second.y())
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
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(NotificationTests, __file__))
    unittest.main()
