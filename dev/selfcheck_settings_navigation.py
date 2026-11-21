"""Manual settings navigation, search, interruption and lifetime regressions."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget
from shiboken6 import isValid
from ddm.settings_pages import PAGE_INDEX
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_material_paint import glass_tint, window_background_tint
from ddm.settings_navigation import SettingsNavigation
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
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True, streamer_rooms=rooms)
        self.addCleanup(dialog.deleteLater)
        dialog.auto_save.start()
        sent = []
        dialog.auto_save.requested.connect(sent.append)
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
        self.assertEqual(list(page.picker.visible_groups), ['first', 'later'])
        self.assertIs(page.picker.grid.itemAtPosition(0, 0).widget(), page.picker.headings['first'])
        self.assertIs(page.picker.grid.itemAtPosition(2, 0).widget(), page.picker.headings['later'])
        platform = page.picker.buttons['huya:1001'].findChild(QLabel, 'RoomChoicePlatform')
        self.assertEqual(platform.accessibleName(), '虎牙')
        self.assertEqual(platform.text(), '')
        self.assertFalse(platform.pixmap().isNull())
        self.assertFalse(page.picker.view.viewport().autoFillBackground())
        page.picker.search.setText('zby')
        self.assertTrue(page.picker.buttons['1001'].isHidden())
        self.assertTrue(page.picker.headings['later'].isHidden())
        self.assertFalse(page.picker.buttons['huya:1001'].isHidden())
        page.picker.buttons['huya:1001'].click()
        page.picker.search.clear()
        page.picker.buttons['1001'].click()
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
        self.assertFalse(card.auto_record.isChecked())
        card.auto_record.click()
        card.windows_notice.click()
        card.auto_record_mode.setCurrentIndex(card.auto_record_mode.findData('clip'))
        APP.processEvents()
        card = page.cards[('huya:1001',)]
        self.assertFalse(card.auto_record_summary.isHidden())
        dialog.auto_save.flush()
        saved = sent[-1]['settings']['streamer_defaults']
        self.assertEqual(set(saved), {'1001', 'huya:1001'})
        self.assertEqual(saved['1001']['playback']['qn'], 10000)
        self.assertEqual(saved['huya:1001']['playback']['qn'], 1)
        self.assertIs(saved['huya:1001']['auto_record'], True)
        self.assertIs(saved['huya:1001']['windows_recording_notice'], True)
        self.assertEqual(saved['huya:1001']['auto_record_mode'], 'clip')
        self.assertNotIn('auto_record', saved['1001'])
        self.assertNotIn('windows_recording_notice', saved['1001'])
        self.assertNotIn('auto_record_mode', saved['1001'])
        dialog.auto_save.acknowledge()
        saved_page = type(page)(dialog.settings(), {})
        self.addCleanup(saved_page.deleteLater)
        self.assertEqual(saved_page.values()['streamer_defaults'], saved)
        self.assertIsNone(saved_page.cards[('huya:1001',)].auto_record_mode)
        card.remove_button.click()
        dialog.auto_save.flush()
        self.assertEqual(set(sent[-1]['settings']['streamer_defaults']), {'1001'})
        dialog.auto_save.acknowledge()
        self.assertEqual(page.undo_notice.undo_button.text(), '撤回')
        page.undo_notice.undo_button.click()
        dialog.auto_save.flush()
        self.assertEqual(sent[-1]['settings']['streamer_defaults'], saved)
        self.assertEqual(list(page.entries), ['huya:1001', '1001'])

    def test_streamer_recording_options_independently_split_merged_cards(self):
        rooms = {key: {'name': key, 'followed': True, 'clip_recording_available': True}
                 for key in ('1001', '1002')}
        rows = {key: {'name': key, 'auto_record': True} for key in rooms}
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS, streamer_defaults=rows,
                                     streamer_defaults_merge_identical=True), {}, preview=True, streamer_rooms=rooms)
        self.addCleanup(dialog.deleteLater)
        dialog.nav.setCurrentRow(PAGE_INDEX['streamer_defaults'])
        page = dialog.stack.currentWidget()
        group = ('1001', '1002')
        for field, change in (
                ('windows_recording_notice', lambda card: card.windows_notice.click()),
                ('auto_record_mode', lambda card: card.auto_record_mode.setCurrentIndex(
                    card.auto_record_mode.findData('normal')))):
            page.cards[group].avatars['1002'].click()
            change(page.cards[group])
            APP.processEvents()
            self.assertEqual(list(page.cards), [('1001',), ('1002',)])
            self.assertNotIn(field, page.entries['1001'])
            self.assertIn(field, page.entries['1002'])
            page.edit(field, {'1002': None})
            APP.processEvents()

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
