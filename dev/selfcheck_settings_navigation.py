"""Manual settings navigation, search, interruption and lifetime regressions."""
from copy import deepcopy
from datetime import date
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QMimeData, QPoint, QPointF, QUrl, Qt
from PySide6.QtGui import QColor, QContextMenuEvent, QCursor, QDragEnterEvent, QDropEvent, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QWidget
from shiboken6 import isValid
from ddm.settings_pages import PAGE_INDEX
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.recording_schedule_dialog import RecordingScheduleDialog
from ddm.settings_material_paint import glass_tint, window_background_tint
from ddm.settings_navigation import SettingsNavigation
from ddm.settings_streamer_defaults import StreamerDefaultsPage
from ddm.ui import SettingsSurface

APP = QApplication.instance() or QApplication([])


class SettingsNavigationTests(unittest.TestCase):
    def setUp(self):
        self.dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        self.dialog.setAttribute(Qt.WA_ShowWithoutActivating)
        self.dialog.resize(1000, 750)
        self.dialog.show()
        APP.processEvents()
        self.navigation = self.dialog.navigation
        self.position = self.dialog.content.mapToGlobal(QPoint(250, 160))
        self.patches = [patch.object(QCursor, 'pos', side_effect=lambda: QPoint(self.position)),
                        patch.object(self.dialog, 'isActiveWindow', return_value=True),
                        patch('ddm.settings_navigation.motion.enabled', return_value=False)]
        for item in self.patches:
            item.start()
        self.addCleanup(self.dispose)

    def dispose(self):
        for item in reversed(self.patches):
            item.stop()
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_grouped_search_keeps_page_indices_and_laziness(self):
        nav = self.dialog.nav
        self.assertEqual(nav.count(), 11)
        self.assertEqual(nav.item(PAGE_INDEX['diagnostics']).data(Qt.UserRole), "diagnostics")
        self.assertFalse(self.dialog._loaded_pages)
        self.assertEqual([nav.item(i).data(Qt.UserRole) for i in range(nav.count())],
                         [key for key, _label in self.dialog.PAGES])
        self.navigation.search.setText('lu zhi')
        self.assertFalse(nav.isRowHidden(3))
        self.assertEqual(self.navigation.heading(3), '观看与互动')
        self.assertTrue(nav.isRowHidden(2))
        nav.setCurrentRow(3)
        self.assertEqual(self.dialog.stack.currentIndex(), 3)
        self.assertEqual(list(self.dialog._loaded_pages), [3])
        self.navigation.search.setText('no-such-setting')
        self.assertTrue(self.navigation.empty_hint.isVisible())
        QTest.mouseClick(self.navigation.rail_button, Qt.LeftButton)
        self.assertTrue(self.navigation.search.isVisible())
        self.assertTrue(all(not nav.isRowHidden(i) for i in range(nav.count())))
        self.assertEqual(self.navigation.width(), SettingsNavigation.COMPACT_WIDTH)
        self.assertEqual(nav.item(3).toolTip(), '录制')
        nav.item(PAGE_INDEX['updates']).setData(Qt.UserRole+1, True)
        self.assertTrue(nav.item(PAGE_INDEX['updates']).data(Qt.UserRole+1))
        self.assertFalse(self.navigation.grab().isNull())
        nav.setCurrentRow(2)
        self.assertEqual(self.dialog.stack.currentWidget(), self.dialog.danmaku_page)
        self.assertTrue(self.navigation.collapsed)

    def test_streamer_cards_keep_two_native_configs_and_split_display_groups(self):
        rooms = {'1001': {'name': '主播甲', 'followed': True, 'platform': 'B 站',
                          'folder_id': 'later', 'folder': '音乐', 'folder_order': 1, 'clip_recording_available': True},
                 'huya:1001': {'name': '主播乙', 'followed': True, 'platform': '虎牙',
                               'folder_id': 'first', 'folder': '游戏', 'folder_order': 0}}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, notice_windows_recording=True), {},
                                preview=True, streamer_rooms=rooms)
        self.addCleanup(dialog.deleteLater)
        dialog.auto_save.start()
        sent = []

        def receive_save(changes):
            sent.append(changes)
            dialog.auto_save.acknowledge()

        dialog.auto_save.requested.connect(receive_save)
        options = {'1001': [{'qn': 400, 'label': '蓝光'}, {'qn': 10000, 'label': '原画'}, {'qn': 15000, 'label': '2K'}],
                   'huya:1001': [{'qn': 2000, 'label': '蓝光'}, {'qn': 1, 'label': '原画'}]}
        dialog.streamerQualityRequested.connect(
            lambda key, token: dialog.receive_streamer_quality(key, token, options[key], ''))
        dialog.navigation.search.setText('zbjk')
        page_index = PAGE_INDEX['streamer_defaults']
        self.assertEqual(page_index, PAGE_INDEX['shortcuts'] + 1)
        self.assertEqual(dialog.nav.item(page_index).text(), '主播监控')
        self.assertEqual(dialog.navigation.heading(page_index), '观看与互动')
        dialog.nav.setCurrentRow(page_index)
        page = dialog.stack.currentWidget()
        self.assertFalse(page.cards)
        from ddm.room_choice import RoomChoice
        picker = page.picker
        model = picker.model
        self.assertEqual(model.index(1, 0).data(Qt.UserRole), 'huya:1001')
        self.assertEqual(model.index(3, 0).data(Qt.UserRole), '1001')
        self.assertIn(rooms['huya:1001']['platform'], model.index(1, 0).data(Qt.AccessibleTextRole))
        self.assertFalse(picker.findChildren(RoomChoice))
        picker.search.setText('zby')
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.index(1, 0).data(Qt.UserRole), 'huya:1001')
        picker.scroll.clicked.emit(model.index(1, 0))
        picker.search.clear()
        self.assertEqual(model.index(1, 0).data(Qt.UserRole), '1001')
        picker.scroll.clicked.emit(model.index(1, 0))
        self.assertEqual(list(page.cards), [('huya:1001',), ('1001',)])
        for room_id in page.entries:
            card = page.cards[(room_id,)]
            self.assertFalse(card.details.isHidden())
            self.assertIn(rooms[room_id]['platform'], card.name.text())
            card.playback.setCurrentIndex(card.playback.findData({room_id: options[room_id][0]}))
            card.recording.setCurrentIndex(card.recording.findData({room_id: options[room_id][1]}))
            card.volume.setValue(0)
        page.merge.click()
        group = ('huya:1001', '1001')
        self.assertEqual(list(page.cards), [group])
        card = page.cards[group]
        self.assertLess(card.avatars['1001'].x() - card.avatars['huya:1001'].x(),
                        card.avatars['1001'].width())
        self.assertTrue(card.avatars['1001'].findChild(QWidget, 'StreamerAvatarPlatform'))
        self.assertIsNone(card.room_id)
        self.assertFalse(any(avatar.isChecked() for avatar in card.avatars.values()))
        self.assertEqual(card.playback.findText('2K'), -1)
        card.playback.setCurrentIndex(card.playback.findText('原画'))
        card.recording.setCurrentIndex(card.recording.findText('蓝光'))
        card.volume.setValue(61)
        APP.processEvents()
        self.assertEqual(list(page.cards), [group])
        self.assertEqual(page.entries['1001']['playback']['qn'], 10000)
        self.assertEqual(page.entries['huya:1001']['playback']['qn'], 1)
        self.assertEqual(page.entries['1001']['recording']['qn'], 400)
        self.assertEqual(page.entries['huya:1001']['recording']['qn'], 2000)
        self.assertEqual({row['volume'] for row in page.entries.values()}, {61})
        card.avatars['1001'].click()
        self.assertGreaterEqual(card.playback.findText('2K'), 0)
        card.avatars['1001'].click()
        self.assertIsNone(card.room_id)
        card.avatars['huya:1001'].click()
        card.volume.setValue(57)
        APP.processEvents()
        self.assertEqual(list(page.cards), [('huya:1001',), ('1001',)])
        self.assertEqual(page.entries['huya:1001']['volume'], 57)
        self.assertEqual(page.entries['1001']['volume'], 61)
        card = page.cards[('huya:1001',)]
        card.toggle.click()
        self.assertTrue(card.details.isHidden())
        self.assertTrue(card.remove_button.isVisibleTo(card))
        self.assertEqual(card.remove_button.accessibleName(), '移除设置')
        self.assertFalse(card.remove_button.text())
        self.assertFalse(any(widget.accessibleName() == '刷新画质' for widget in card.findChildren(QWidget)))
        self.assertIn('57%', card.summary_values['volume'].text())
        self.assertEqual(card.auto_record.currentData(), 'off')
        card.auto_record.setCurrentIndex(card.auto_record.findData('live'))
        APP.processEvents()
        card = page.cards[('huya:1001',)]
        card.windows_notice.click()
        card.auto_record_mode.setCurrentIndex(card.auto_record_mode.findData('clip'))
        APP.processEvents()
        card = page.cards[('huya:1001',)]
        self.assertFalse(card.auto_record_summary.isHidden())
        self.assertTrue(dialog.auto_save.flush())
        saved = sent[-1]['settings']['streamer_defaults']
        self.assertEqual(set(saved), {'1001', 'huya:1001'})
        self.assertEqual(saved['1001']['playback']['qn'], 10000)
        self.assertEqual(saved['huya:1001']['playback']['qn'], 1)
        self.assertEqual(saved['huya:1001']['recording_policy'], 'live')
        self.assertIs(saved['huya:1001']['windows_recording_notice'], True)
        self.assertEqual(saved['huya:1001']['auto_record_mode'], 'clip')
        self.assertNotIn('auto_record', saved['1001'])
        self.assertNotIn('windows_recording_notice', saved['1001'])
        self.assertNotIn('auto_record_mode', saved['1001'])
        saved_page = type(page)(dialog.settings(), {})
        self.addCleanup(saved_page.deleteLater)
        self.assertEqual(saved_page.values()['streamer_defaults'], saved)
        self.assertIsNone(saved_page.cards[('huya:1001',)].auto_record_mode)
        card.remove_button.click()
        self.assertTrue(dialog.auto_save.flush())
        self.assertEqual(set(sent[-1]['settings']['streamer_defaults']), {'1001'})
        self.assertEqual(page.undo_notice.undo_button.text(), '撤回')
        page.undo_notice.undo_button.click()
        self.assertTrue(dialog.auto_save.flush())
        self.assertEqual(sent[-1]['settings']['streamer_defaults'], saved)
        self.assertEqual(list(page.entries), ['huya:1001', '1001'])

    def test_streamer_recording_options_independently_split_merged_cards(self):
        rooms = {key: {'name': key, 'followed': True, 'clip_recording_available': True}
                 for key in ('1001', '1002')}
        rows = {key: {'name': key, 'auto_record': True} for key in rooms}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows,
                                     streamer_defaults_merge_identical=True, notice_windows_recording=True), {},
                                preview=True, streamer_rooms=rooms)
        self.addCleanup(dialog.deleteLater)
        dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        page = dialog.stack.currentWidget()
        group = ('1001', '1002')
        for field, change in (
                ('monitor_live', lambda card: card.monitor_live.click()),
                ('windows_live_notice', lambda card: card.live_notice.click()),
                ('windows_recording_notice', lambda card: card.windows_notice.click()),
                ('auto_record_mode', lambda card: card.auto_record_mode.setCurrentIndex(
                    card.auto_record_mode.findData('normal')))):
            page.cards[group].avatars['1002'].click()
            change(page.cards[group])
            APP.processEvents()
            self.assertEqual(list(page.cards), [('1001',), ('1002',)])
            if field == 'monitor_live':
                self.assertIs(page.entries['1001'][field], True)
                self.assertIs(page.entries['1002'][field], False)
                page.edit(field, {'1002': True})
                APP.processEvents()
                continue
            self.assertNotIn(field, page.entries['1001'])
            self.assertIn(field, page.entries['1002'])
            page.edit(field, {'1002': None})
            APP.processEvents()

    def test_streamer_windows_notice_tracks_total_switch_in_both_page_orders(self):
        streamer = PAGE_INDEX['streamer_defaults']
        notifications = PAGE_INDEX['notifications']
        rows = {'1001': {'name': '主播', 'auto_record': True, 'auto_record_mode': 'clip'}}
        for first, second in ((streamer, notifications), (notifications, streamer)):
            dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows), {}, preview=True)
            self.addCleanup(dialog.deleteLater)
            dialog.nav.setCurrentRow(first)
            if first == notifications:
                dialog.notification_page.windows_recording_notice.click()
            dialog.nav.setCurrentRow(second)
            page = dialog._loaded_pages[streamer]
            card = page.cards[('1001',)]
            self.assertEqual(card.windows_notice.isEnabled(), first == notifications)
            self.assertEqual(page.windows_notice_hint.text(), '在「通知」开启 Windows 通知。')
            self.assertEqual(page.windows_notice_hint.isHidden(), first == notifications)
            self.assertEqual(card.mode_summary_value.text(), '切片')
            self.assertFalse(card.auto_record_summary.isHidden())
            self.assertTrue(card.windows_notice_summary.isHidden())
            switch = dialog.notification_page.windows_recording_notice
            if first == streamer:
                card.windows_notice.click()
                self.assertNotIn('windows_recording_notice', page.entries['1001'])
                switch.click()
            self.assertTrue(card.windows_notice.isEnabled())
            self.assertTrue(page.windows_notice_hint.isHidden())
            self.assertFalse(card.live_notice.isChecked())
            card.live_notice.click()
            APP.processEvents()
            card.windows_notice.click()
            APP.processEvents()
            self.assertFalse(card.windows_notice_summary.isHidden())
            self.assertTrue(card.windows_notice_summary.isEnabled())
            dialog.notification_page.reset()
            self.assertFalse(card.windows_notice.isEnabled())
            self.assertFalse(page.windows_notice_hint.isHidden())
            self.assertFalse(card.windows_notice_summary.isEnabled())
            self.assertTrue(card.windows_notice.isChecked())
            saved = dialog.settings()['streamer_defaults']['1001']
            self.assertTrue(saved['windows_recording_notice'])
            self.assertIs(saved['windows_live_notice'], True)
            switch.click()
            self.assertTrue(card.windows_notice.isEnabled())
            self.assertTrue(card.windows_notice.isChecked())
            self.assertTrue(card.live_notice.isChecked())
            card.live_notice.click()
            self.assertNotIn('windows_live_notice', dialog.settings()['streamer_defaults']['1001'])

    def test_streamer_monitor_pause_preserves_both_notification_and_recording_preferences(self):
        rows = {'1001': {'name': '主播', 'auto_record': True, 'windows_live_notice': True,
                         'windows_recording_notice': True, 'recording': 720}}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows,
                                     notice_windows_recording=True), {}, preview=True)
        self.addCleanup(dialog.deleteLater)
        dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        page = dialog.stack.currentWidget()
        card = page.cards[('1001',)]
        self.assertTrue(card.monitor_live.isChecked())
        self.assertTrue(card.live_notice.isEnabled() and card.windows_notice.isEnabled())
        card.monitor_live.click()
        APP.processEvents()
        self.assertEqual(card.auto_record_summary.text(), '自动录制已暂停')
        self.assertFalse(card.auto_record.isEnabled())
        self.assertEqual(card.auto_record.currentData(), 'live')
        for toggle in (card.live_notice, card.windows_notice):
            self.assertFalse(toggle.isEnabled())
            self.assertTrue(toggle.isChecked())
        paused = dialog.settings()['streamer_defaults']['1001']
        self.assertEqual(paused, {**rows['1001'], 'monitor_live': False})
        reopened = type(page)(dict(config.DEFAULT_SETTINGS, streamer_defaults={'1001': paused},
                                   notice_windows_recording=True), {})
        self.addCleanup(reopened.deleteLater)
        card = reopened.cards[('1001',)]
        self.assertFalse(card.monitor_live.isChecked())
        card.monitor_live.click()
        APP.processEvents()
        self.assertTrue(card.live_notice.isEnabled() and card.windows_notice.isEnabled())
        self.assertEqual(card.auto_record_summary.text(), '自动录制')

    def test_merged_card_edits_recording_conditions_for_group_or_selected_room(self):
        ids = ('1001', '1002')
        page = StreamerDefaultsPage(
            {'streamer_defaults_merge_identical': True,
             'streamer_defaults': {room_id: {'monitor_live': True} for room_id in ids}},
            {room_id: {'name': room_id, 'followed': True} for room_id in ids})
        self.addCleanup(page.deleteLater)
        card = page.cards[ids]
        self.assertEqual(card.auto_record.findData('inherit'), -1)
        self.assertTrue(card.schedule_edit.isHidden())
        card.auto_record.setCurrentIndex(card.auto_record.findData('schedule'))
        self.assertFalse(card.schedule_edit.isHidden())
        self.assertEqual(card.schedule_edit.text(), '')
        self.assertEqual(card.schedule_edit.toolTip(), '编辑计划')
        strategy = card.auto_record.parentWidget().layout()
        self.assertEqual(strategy.indexOf(card.schedule_edit), strategy.indexOf(card.auto_record) + 1)
        changes = []
        page.changed.connect(lambda: changes.append(page.values()['streamer_defaults']))

        def edit_group(dialog):
            dialog.add_row(6, 60, 180)
            dialog.keyword_input.setText('BO3，赛事复盘、bo3')
            return QDialog.Accepted

        with patch.object(RecordingScheduleDialog, 'exec', new=edit_group):
            card.schedule_edit.click()
        APP.processEvents()
        self.assertEqual(len(changes), 1)
        for row in changes[0].values():
            self.assertEqual(row['recording_policy'], 'schedule')
            self.assertEqual(row['recording_schedule'], ((6, 60, 180),))
            self.assertEqual(row['recording_title_keywords'], ('bo3', '赛事复盘'))

        card = page.cards[ids]
        card.avatars['1002'].click()

        def edit_selected(dialog):
            dialog._remove(dialog.rows[0])
            for tag, remove in tuple(dialog.keyword_tags.tags.values()):
                tag.customContextMenuRequested.emit(tag.rect().center())
                remove.click()
            dialog.keyword_input.setText('决赛')
            return QDialog.Accepted

        with patch.object(RecordingScheduleDialog, 'exec', new=edit_selected):
            card.schedule_edit.click()
        APP.processEvents()
        profiles = page.values()['streamer_defaults']
        self.assertEqual(profiles['1001'], changes[0]['1001'])
        self.assertNotIn('recording_schedule', profiles['1002'])
        self.assertEqual(profiles['1002']['recording_title_keywords'], ('决赛',))
        self.assertEqual(page.cards[('1002',)].schedule_hint.text(), '按标题匹配')
        selected = page.cards[('1002',)]
        selected.auto_record.setCurrentIndex(selected.auto_record.findData('live'))
        self.assertTrue(selected.schedule_edit.isHidden())

    def test_recording_plan_editor_uses_settings_controls_and_marks_only_overnight_rows(self):
        from ddm.settings_window import SettingsTitleBar
        from ddm.ui import NavigationButton

        dialog = RecordingScheduleDialog(None, ((4, 1200, 1320), (5, 1380, 60)), ('决赛',))
        self.addCleanup(dialog.deleteLater)
        dialog.setAttribute(Qt.WA_ShowWithoutActivating)
        accepted = []
        dialog.accepted.connect(lambda: accepted.append(dialog.schedule()))
        dialog.show()
        APP.processEvents()
        self.assertIsInstance(dialog.titlebar, SettingsTitleBar)
        self.assertTrue(dialog.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(dialog.save.objectName(), 'PrimaryButton')
        self.assertEqual(dialog.keyword_input.accessibleName(), '直播间标题关键词')
        same_day, overnight = dialog.rows
        self.assertEqual(same_day[-1].text(), '')
        self.assertEqual(overnight[-1].text(), '次日')
        self.assertEqual(same_day[1].height(), same_day[2].height())
        same_day[3].setTime(same_day[2].time())
        self.assertFalse(dialog.save.isEnabled())
        self.assertTrue(dialog.error.isVisible())
        same_day[0].findChild(NavigationButton).click()
        self.assertTrue(dialog.save.isEnabled())
        self.assertFalse(dialog.error.isVisible())
        dialog.save.click()
        self.assertEqual(accepted, [((5, 1380, 60),)])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows OCR entry')
    def test_calendar_import_reviews_and_saves_selected_rows(self):
        from ddm.recording_calendar import CalendarEntry

        editor = RecordingScheduleDialog(None, ((0, 600, 720),), ('123',))
        self.addCleanup(editor.deleteLater)
        editor.setAttribute(Qt.WA_ShowWithoutActivating)
        editor.show()
        tags = editor.keyword_tags
        self.assertEqual(editor.import_calendar.text(), '周表识别')
        self.assertTrue(editor.calendar.isHidden())
        editor.import_calendar.click()
        APP.processEvents()
        self.assertEqual(editor.import_calendar.text(), '收起周表识别')
        self.assertEqual(tags.tag_area.height(), tags.tags['123'][0].height())
        for word in ('recording title A ' * 3, 'recording title B ' * 3, 'recording title C ' * 3):
            tags.input.setText(word)
            QTest.keyClick(tags.input, Qt.Key_Return)
        for expanded in (True, False, True):
            editor.import_calendar.setChecked(expanded)
            APP.processEvents()
            last_tag_bottom = max(tag.geometry().bottom() + 1 for tag, _ in tags.tags.values())
            self.assertGreater(last_tag_bottom, tags.tags['123'][0].height())
            self.assertEqual(tags.tag_area.height(), last_tag_bottom)
        calendar = editor.calendar
        self.assertTrue(calendar.isVisible())
        self.assertIs(calendar.window(), editor)
        self.assertTrue(calendar.drop_area.isVisible())
        self.assertGreater(editor.height(), editor.compact_height)
        image = QImage(100, 140, QImage.Format_RGB32)
        image.fill(Qt.white)
        with patch.object(calendar.process, 'start'):
            calendar.load_image(image)
        APP.processEvents()
        self.assertTrue(calendar.drop_area.isHidden())
        self.assertTrue(calendar.preview.isVisible())
        self.assertTrue(calendar.remove_image.isVisible())
        self.assertEqual(calendar.remove_image.geometry().topRight(), calendar.preview.geometry().topRight())
        calendar.today = date(2026, 11, 28)
        calendar._add_row(CalendarEntry(date(2026, 11, 25), 900, None, '15:00'))
        calendar._add_row(CalendarEntry(date(2026, 12, 1), 1200, None, '20:00'))
        calendar.review.show()
        past, chosen = calendar.rows
        self.assertFalse(calendar.confirm.isEnabled())
        past[0].setChecked(True)
        self.assertFalse(calendar.confirm.isEnabled())
        calendar.frequency.setCurrentIndex(1)
        self.assertEqual(calendar.schedule(), ((2, 900, None),))
        past[0].setChecked(False)
        calendar.frequency.setCurrentIndex(0)
        chosen[0].setChecked(True)
        self.assertTrue(calendar.confirm.isEnabled())
        calendar.confirm.click()
        self.assertEqual(editor.schedule(), ((0, 600, 720), ('2026-12-01', 1200, None)))
        calendar.rows[0][0].setChecked(True)
        calendar.remove_image.click()
        self.assertTrue(calendar.drop_area.isVisible())
        self.assertFalse(calendar.preview.isVisible())
        self.assertFalse(calendar.rows)
        editor.save.click()
        self.assertEqual(editor.result(), QDialog.Accepted)
        self.assertEqual(editor.schedule(), ((0, 600, 720), ('2026-12-01', 1200, None)))
        reopened = RecordingScheduleDialog(None, editor.schedule())
        self.addCleanup(reopened.deleteLater)
        self.assertEqual(reopened.schedule(), editor.schedule())
        self.assertEqual(reopened.rows[1][3].text(), '至下播')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows OCR entry')
    def test_calendar_accepts_image_drops_from_file_and_browser(self):
        editor = RecordingScheduleDialog(None, ())
        self.addCleanup(editor.deleteLater)
        editor.setAttribute(Qt.WA_ShowWithoutActivating)
        editor.show()
        APP.processEvents()

        def drop(widget, mime):
            pos = widget.rect().center()
            enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            APP.sendEvent(widget, enter)
            self.assertTrue(enter.isAccepted())
            event = QDropEvent(QPointF(pos), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            APP.sendEvent(widget, event)
            self.assertTrue(event.isAccepted())

        with tempfile.TemporaryDirectory() as workspace, patch.object(editor.calendar.loader, 'load') as load:
            file = QUrl.fromLocalFile(str(Path(workspace) / '周表.png'))
            image = QImage(10, 10, QImage.Format_RGB32)
            image.fill(Qt.white)
            self.assertTrue(image.save(file.toLocalFile()))
            local = QMimeData()
            local.setUrls([file])
            drop(editor, local)
            self.assertTrue(editor.calendar.isVisible())
            load.assert_called_with(file)

            web = QMimeData()
            web.setUrls([QUrl('https://example.com/dynamic/1')])
            web.setHtml('<a href="/dynamic/1"><img src="//cdn.example.com/calendar.webp"></a>')
            drop(editor.calendar.drop_area, web)
            load.assert_called_with(QUrl('https://cdn.example.com/calendar.webp'))
            bitmap = QMimeData()
            bitmap.setImageData(image)
            drop(editor.calendar.drop_area, bitmap)
            self.assertEqual(load.call_args.args[0].size(), image.size())

            thumbnail = 'https://i1.hdslb.com/bfs/new_dyn/calendar.png@264w_264h_1e_1c.avif'
            web.setHtml(f'<img src="{thumbnail}">')
            web.setImageData(image)
            drop(editor.calendar.drop_area, web)
            load.assert_called_with(QUrl(thumbnail))

            enlarged = QMimeData()
            enlarged.setHtml('<img src="//i1.hdslb.com/bfs/new_dyn/calendar.png@1052w_!web-dynamic.avif">')
            drop(editor.calendar.drop_area, enlarged)
            load.assert_called_with(QUrl('https://i1.hdslb.com/bfs/new_dyn/calendar.png@1052w_!web-dynamic.avif'))

        loader = editor.calendar.loader
        with patch.object(loader, '_get') as get:
            loader.load(QUrl(thumbnail))
            get.assert_called_once_with(QUrl('https://i1.hdslb.com/bfs/new_dyn/calendar.png@2560w.webp'),
                                        QUrl('https://i1.hdslb.com/bfs/new_dyn/calendar.png'))
            get.reset_mock()
            direct = QUrl('https://example.com/calendar@256w.webp')
            loader.load(direct)
            get.assert_called_once_with(direct)

    def test_recording_keywords_add_with_enter_and_save_pending_text(self):
        editor = RecordingScheduleDialog(None, (), ('existing',))
        self.addCleanup(editor.deleteLater)
        editor.setAttribute(Qt.WA_ShowWithoutActivating)
        editor.show()
        editor.keyword_input.setText('BO3')
        QTest.keyClick(editor.keyword_input, Qt.Key_Return)
        self.assertTrue(editor.isVisible())
        self.assertEqual(editor.keyword_input.text(), '')
        tag, remove = editor.keyword_tags.tags['bo3']
        self.assertTrue(remove.isHidden())
        pos = tag.rect().center()
        APP.sendEvent(tag, QContextMenuEvent(QContextMenuEvent.Mouse, pos, tag.mapToGlobal(pos)))
        self.assertTrue(remove.isVisible())
        remove.click()
        self.assertEqual(editor.title_keywords(), ('existing',))
        editor.keyword_input.setText('决赛复盘')
        editor.save.click()
        self.assertEqual(editor.result(), QDialog.Accepted)
        self.assertEqual(editor.title_keywords(), ('existing', '决赛复盘'))
        self.assertIn('决赛复盘', editor.keyword_tags.tags)

    def test_streamer_monitor_card_groups_and_fits_wide_and_narrow_windows(self):
        settings = {'notice_windows_recording': True, 'streamer_defaults': {
            '1001': {'name': '布局示例', 'monitor_live': True, 'auto_record': True}}}
        page = StreamerDefaultsPage(settings, {'1001': {
            'name': '布局示例', 'followed': True, 'clip_recording_available': True}})
        self.addCleanup(page.deleteLater)
        page.setAttribute(Qt.WA_ShowWithoutActivating)
        page.show()
        card = page.cards[('1001',)]
        header = page.scroll.widget().layout().itemAt(0).layout()
        self.assertEqual([header.itemAt(i).widget().text() for i in range(header.count())], ['主播监控'])
        self.assertEqual(page.merge.toolTip(), '未选头像时编辑整组，选中后单独编辑。')
        self.assertEqual(card.monitor_live.toolTip(), '关闭后暂停 Windows 开播通知及后续自动录制，保留设置。')
        self.assertEqual(card.windows_notice.toolTip(), '自动开录、确认下播或计划结束时通知。')
        self.assertEqual(card.windows_notice.accessibleDescription(), card.windows_notice.toolTip())
        card.toggle.click()
        left, right = card.details.section('playback'), card.details.section('capture')
        strategy = card.auto_record.parentWidget()
        capture_fields = (strategy, card.recording, card.auto_record_mode, card.windows_notice)
        for size, columns in (((1040, 700), 2), ((480, 760), 1)):
            page.resize(*size)
            # Resizing the outer scroll area and switching the column layout
            # can post separate layout requests.
            for _ in range(50):
                QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
                if card.details.columns == columns and all(
                        control.isVisible() and right.rect().contains(control.geometry())
                        for control in capture_fields):
                    break
                QTest.qWait(20)
            self.assertEqual(card.details.columns, columns)
            self.assertIs(card.monitor_live.parentWidget(), left)
            self.assertIs(card.live_notice.parentWidget(), left)
            live_label = left.layout().labelForField(card.live_notice)
            recording_label = right.layout().labelForField(card.windows_notice)
            if columns == 2:
                self.assertEqual(live_label.mapTo(card.details, live_label.rect().center()).y(),
                                 recording_label.mapTo(card.details, recording_label.rect().center()).y())
            self.assertEqual(live_label.text(), '开播时发送 Windows 通知')
            self.assertEqual(recording_label.text(), '录制时发送 Windows 通知')
            self.assertLess(strategy.y(), card.windows_notice.y())
            self.assertLess(card.windows_notice.y(), card.recording.y())
            for control in capture_fields:
                self.assertIs(control.parentWidget(), right)
                self.assertTrue(right.rect().contains(control.geometry()),
                                (size, control.accessibleName(), right.rect(), control.geometry()))
                label = right.layout().labelForField(control)
                self.assertTrue(right.rect().contains(label.geometry()))
                self.assertFalse(label.geometry().intersects(control.geometry()))

    def test_streamer_quality_stays_editable_without_common_platform_tiers(self):
        rooms = {'1001': '主播甲', '1002': '主播乙'}
        rows = {key: {'name': name} for key, name in rooms.items()}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows,
                                     streamer_defaults_merge_identical=True), {}, preview=True, streamer_rooms=rooms)
        self.addCleanup(dialog.deleteLater)
        requests = {}
        dialog.streamerQualityRequested.connect(lambda key, token: requests.update({key: token}))
        dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        page = dialog.stack.currentWidget()
        card = page.cards[('1001', '1002')]
        card.toggle.click()
        self.assertTrue(card.playback.isEnabled() and card.recording.isEnabled())
        self.assertIn('正在读取', card.status.text())
        dialog.receive_streamer_quality('1001', requests['1001'], [{'qn': 400, 'label': '蓝光'}], '')
        dialog.receive_streamer_quality('1002', requests['1002'], [], '')
        self.assertEqual(card.status.text(), '无共有档位。点头像查看。')
        self.assertEqual(card.remove_button.toolTip(), '移除整组主播设置')
        for control in (card.playback, card.recording):
            self.assertEqual([control.itemText(index) for index in range(control.count())], ['继承', '最高可用'])
            control.setCurrentIndex(control.findText('最高可用'))
        APP.processEvents()
        self.assertEqual({(row['playback'], row['recording']) for row in page.entries.values()}, {(0, 0)})
        stale = requests['1002']
        card.toggle.click()
        card.toggle.click()
        self.assertNotEqual(requests['1002'], stale)
        self.assertEqual(card.recording.currentText(), '最高可用')
        dialog.receive_streamer_quality('1002', requests['1002'], [
            {'qn': 250, 'label': '超清'}, {'qn': 400, 'label': '1080p 常规画质'}], '')
        self.assertEqual(card.playback.itemData(card.playback.findText('1080P')), {
            '1001': {'qn': 400, 'label': '蓝光'}, '1002': {'qn': 400, 'label': '1080p 常规画质'}})
        card.avatars['1001'].click()
        self.assertEqual(card.playback.currentText(), '最高可用')
        self.assertIn('1080P', [card.playback.itemText(index) for index in range(card.playback.count())])
        card.playback.setCurrentIndex(card.playback.findText('继承'))
        APP.processEvents()
        self.assertNotIn('playback', page.entries['1001'])
        self.assertEqual(page.entries['1002']['playback'], 0)

    def test_collapsed_group_removal_and_undo_respect_avatar_selection(self):
        rows = {'1001': {'name': '甲', 'volume': 20}, 'huya:1002': {'name': '乙', 'volume': 20},
                '1003': {'name': '丙', 'volume': 30}}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows,
                                     streamer_defaults_merge_identical=True), {}, preview=True,
                                streamer_rooms={key: row['name'] for key, row in rows.items()})
        self.addCleanup(dialog.deleteLater)
        dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        page = dialog.stack.currentWidget()
        group = ('1001', 'huya:1002')
        card = page.cards[group]
        self.assertTrue(card.details.isHidden())
        self.assertIsNone(card.room_id)
        self.assertTrue(card.remove_button.isEnabled())
        card.remove_button.click()
        self.assertEqual(list(page.entries), ['1003'])
        self.assertEqual(page.undo_notice.undo_button.text(), '全部撤回')
        self.assertEqual(page.undo_notice.timer.interval(), 10000)
        page.undo_notice.undo_button.click()
        self.assertEqual(list(page.entries), list(rows))
        self.assertEqual(page.entries, rows)
        self.assertTrue(page.undo_notice.undo_button.isHidden())

        card = page.cards[group]
        card.avatars['huya:1002'].click()
        card.toggle.click()
        self.assertTrue(card.details.isHidden())
        card.remove_button.click()
        self.assertEqual(list(page.entries), ['1001', '1003'])
        self.assertFalse(page.undo_notice.pile.isHidden())
        self.assertEqual(page.undo_notice.undo_button.text(), '撤回')
        page.add('huya:1002')
        page.cards[('huya:1002',)].volume.setValue(88)
        page.undo_notice.undo_button.click()
        self.assertEqual(page.entries['huya:1002']['volume'], 88)
        self.assertEqual(page.entries['1001']['volume'], 20)

        page.cards[('1003',)].remove_button.click()
        page.undo_notice._expire()
        page.undo_removal()
        self.assertNotIn('1003', page.entries)

    def test_separate_removals_share_notice_with_selective_and_remaining_undo(self):
        rows = {str(number): {'name': f'主播 {number}', 'volume': number - 1000}
                for number in range(1001, 1007)}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows), {}, preview=True,
                                streamer_rooms={key: row['name'] for key, row in rows.items()})
        self.addCleanup(dialog.deleteLater)
        dialog.resize(920, 660)
        dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        dialog.show()
        APP.processEvents()
        page = dialog.stack.currentWidget()
        notice = page.undo_notice
        for room_id in ('1004', '1002', '1006', '1001'):
            page.cards[(room_id,)].remove_button.click()
        self.assertEqual(list(notice.rooms), ['1004', '1002', '1006', '1001'])
        self.assertEqual(notice.undo_button.text(), '全部撤回')
        self.assertFalse(notice.expand_button.isHidden())
        self.assertTrue(notice.details.isHidden())
        bottom = notice.geometry().bottom()
        scroll_size = page.scroll.size()
        notice.expand_button.click()
        APP.processEvents()
        self.assertFalse(notice.details.isHidden())
        self.assertEqual(notice.geometry().bottom(), bottom)
        self.assertEqual(page.scroll.size(), scroll_size)
        self.assertEqual(list(notice.detail_rows), list(notice.rooms))
        notice.detail_rows['1002'].findChild(QPushButton).click()
        self.assertEqual(list(page.entries), ['1002', '1003', '1005'])
        self.assertEqual(list(notice.detail_rows), ['1004', '1006', '1001'])
        self.assertFalse(notice.details.isHidden())
        page.add('1004')
        page.cards[('1004',)].volume.setValue(88)
        self.assertEqual(list(notice.detail_rows), ['1006', '1001'])
        notice.undo_button.click()
        self.assertEqual(list(page.entries), ['1001', '1002', '1003', '1005', '1006', '1004'])
        self.assertEqual(page.entries['1004']['volume'], 88)
        self.assertEqual(page.entries['1006'], rows['1006'])
        self.assertFalse(page.removed_profiles)
        self.assertTrue(notice.expand_button.isHidden())
        self.assertTrue(notice.details.isHidden())

    @patch('ddm.settings_window.apply_blur', return_value=False)
    def test_streamer_removal_notice_matches_settings_card_material(self, native_blur):
        self.dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        page = self.dialog.stack.currentWidget()
        notice = page.undo_notice
        notice.present({'1001': {'name': '主播甲'}, '1002': {'name': '主播乙'}})
        reference = SettingsSurface(page)

        def surface_pixels(widget, backdrop):
            image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(backdrop)
            with QPainter(image) as painter:
                widget.render(painter, QPoint(), QRegion(), QWidget.RenderFlag(0))
            return image

        for expanded in (False, True):
            if expanded:
                notice.expand_button.click()
                self.assertTrue(notice.details.isVisible())
            for enabled, native, no_shadows in ((False, False, False), (True, False, False),
                                                (True, True, False), (True, True, True)):
                with self.subTest(expanded=expanded, enabled=enabled, native=native, no_shadows=no_shadows):
                    native_blur.return_value = native
                    self.dialog.set_material({'settings_glass_enabled': enabled, 'settings_no_shadows': no_shadows})
                    self.dialog._sync_frame()
                    APP.processEvents()
                    reference.resize(notice.size())
                    backdrop = glass_tint(notice, window_background_tint(notice)) if native else Qt.transparent
                    actual = surface_pixels(notice, backdrop)
                    expected = surface_pixels(reference, backdrop)
                    if native:
                        for sample in (actual.rect().center(), QPoint(10, 10), QPoint(1, 1)):
                            for channel, target in zip(actual.pixelColor(sample).getRgb(),
                                                       expected.pixelColor(sample).getRgb()):
                                self.assertAlmostEqual(channel, target, delta=2)
                    else:
                        self.assertEqual(actual, expected)

        class Marker(QWidget):
            def paintEvent(self, _event):
                with QPainter(self) as painter:
                    for x in range(0, self.width(), 8):
                        painter.fillRect(x, 0, 4, self.height(), QColor('#ff0000'))

        # Text-sized edges should disappear while the broad tint remains visible.
        marker = Marker(page.scroll.viewport())
        marker.resize(128, 48)
        marker.move(page.scroll.viewport().mapFrom(page, notice.mapTo(page, QPoint(200, -12))))
        inside = notice.mapTo(self.dialog, QPoint(249, 8))
        outside = notice.mapTo(self.dialog, QPoint(249, -6))
        before = self.dialog.grab().toImage()
        marker.show()
        after = self.dialog.grab().toImage()
        gap = QPoint(4, 0)
        self.assertGreater(after.pixelColor(outside).red() - after.pixelColor(outside + gap).red(), 100)
        self.assertGreater(after.pixelColor(inside).red() - before.pixelColor(inside).red(), 8)
        self.assertLessEqual(abs(after.pixelColor(inside).red() - after.pixelColor(inside + gap).red()), 6)

    def test_header_button_collapses_and_expands_without_changing_edits_or_page(self):
        button = self.navigation.rail_button
        self.assertTrue(button.isVisible())
        self.assertEqual(button.accessibleName(), '收起设置分类')
        self.dialog.nav.setCurrentRow(3)
        page = self.dialog.recording_page
        page.directory.setText('offline-recording-draft')
        before = page.values()
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertTrue(self.navigation.collapsed)
        self.assertTrue(button.isVisible())
        self.assertEqual(button.kind, 'expand')
        self.assertEqual(button.accessibleName(), '展开设置分类')
        self.assertEqual(self.dialog.nav.currentRow(), 3)
        self.assertEqual(page.values(), before)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertFalse(self.navigation.collapsed)
        self.assertEqual(button.kind, 'collapse')
        self.assertTrue(self.navigation.search.isVisible())
        self.assertEqual(self.navigation.width(), SettingsNavigation.EXPANDED_WIDTH)
        self.assertIs(self.dialog.recording_page, page)
        self.assertEqual(page.values(), before)

    def test_pointer_dwell_and_return_never_change_the_manual_state(self):
        QApplication.sendEvent(self.dialog.content, QEvent(QEvent.Enter))
        QTest.qWait(2250)
        self.assertFalse(self.navigation.collapsed)
        QTest.mouseClick(self.navigation.rail_button, Qt.LeftButton)
        self.position = self.navigation.mapToGlobal(QPoint(20, 140))
        QApplication.sendEvent(self.navigation, QEvent(QEvent.Enter))
        QTest.qWait(250)
        self.assertTrue(self.navigation.collapsed)
        self.assertEqual(self.navigation.width(), SettingsNavigation.COMPACT_WIDTH)

    def test_keyboard_button_and_category_navigation_keep_manual_state(self):
        button = self.navigation.rail_button
        self.assertFalse(button.autoDefault())
        button.setFocus()
        QTest.keyClick(button, Qt.Key_Space)
        self.assertTrue(self.navigation.collapsed)
        QTest.keyClick(self.dialog.nav, Qt.Key_Down)
        self.assertTrue(self.navigation.collapsed)
        QTest.keyClick(button, Qt.Key_Space)
        self.assertFalse(self.navigation.collapsed)

    def test_interrupted_transition_and_reduced_motion(self):
        button = self.navigation.rail_button
        with patch('ddm.settings_navigation.motion.enabled', return_value=True):
            QTest.mouseClick(button, Qt.LeftButton)
            self.navigation.animation.setCurrentTime(70)
            width = self.navigation.width()
            QTest.mouseClick(button, Qt.LeftButton)
            self.assertEqual(self.navigation.animation.startValue(), width)
            self.navigation.animation.setCurrentTime(200)
            self.assertEqual(self.navigation.width(), SettingsNavigation.EXPANDED_WIDTH)
        QTest.mouseClick(button, Qt.LeftButton)
        self.assertEqual(self.navigation.animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.navigation.width(), SettingsNavigation.COMPACT_WIDTH)

    def test_hide_stops_transition_and_reopen_keeps_the_manual_choice(self):
        with patch('ddm.settings_navigation.motion.enabled', return_value=True):
            self.navigation.rail_button.click()
            self.navigation.animation.setCurrentTime(70)
            self.dialog.hide()
        self.assertEqual(self.navigation.animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.navigation.width(), SettingsNavigation.COMPACT_WIDTH)
        self.dialog.show()
        APP.processEvents()
        self.assertTrue(self.navigation.collapsed)
        self.assertTrue(self.navigation.rail_button.isVisible())

    def test_dialog_has_no_pointer_controller_and_releases_its_animation(self):
        self.assertFalse(hasattr(self.dialog, 'pointer_navigation'))
        probe = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        probe.setAttribute(Qt.WA_ShowWithoutActivating)
        probe.show()
        APP.processEvents()
        animation = probe.navigation.animation
        probe.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(animation))

    def test_solid_navigation_keeps_legacy_glass_artwork_behind_the_opaque_base(self):
        from ddm import skin_parts
        package, personal = deepcopy(skin_parts._package), deepcopy(skin_parts._personal)
        try:
            with tempfile.TemporaryDirectory() as directory:
                image = QImage(24, 24, QImage.Format_ARGB32)
                image.fill(QColor('#ff8800'))
                path = Path(directory)/'background.png'
                image.save(str(path))
                skin_parts.configure({}, {'settings': {'image': path.as_posix()},
                                          'settings.navigation': {'background': '#00000000'}})
                self.dialog.set_material({'settings_glass_enabled': True, 'settings_glass_opacity': 0})
                APP.processEvents()
                capture = self.dialog.grab().toImage()
                point = self.dialog.nav.mapTo(self.dialog, QPoint(5, 5))
                colour = capture.pixelColor(point)
                self.assertEqual(colour.name(), '#eeedf4' if theme.is_light() else '#33373b')
                self.assertEqual(colour.alpha(), 255)
                self.assertNotEqual(colour, theme.qcolor(theme.SIDEBAR))
        finally:
            skin_parts.configure(package, personal)


if __name__ == '__main__':
    APP.setStyleSheet(theme.qss())
    unittest.main()
