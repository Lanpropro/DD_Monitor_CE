"""Folder/filter boundaries with hidden real Qt cards; temporary data, no network or media."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import isValid
from ddm import config, images, motion
from ddm import sidebar_widgets as module
from ddm.sidebar_folder_control import SidebarFolderControl
from ddm.sidebar_filter import SidebarFilter


class SidebarFolderControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-folder-control-'))
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(images, 'REPO', directory))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.sidebar = module.Sidebar([
            {'room_id': '1001', 'uname': '小明', 'live': True},
            {'room_id': 'huya:fixture', 'uname': 'Alice', 'live': False},
            {'room_id': '1003', 'uname': 'Other', 'live': True}], auto_compact=False)
        self.items = {str(item.room['room_id']): item for item in self.sidebar.items()}

    def tearDown(self):
        if isValid(self.sidebar):
            self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def test_independent_imports_and_legacy_sidebar_identity(self):
        for name in ('sidebar_folder_control', 'sidebar_filter'):
            code = 'import sys; import ddm.' + name + '; ' + \
                "assert not {'ddm.app','ddm.widgets','ddm.sidebar_widgets','ddm.player','mpv'}.intersection(sys.modules)"
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        from ddm.widgets import Sidebar
        self.assertIs(Sidebar, module.Sidebar)
        self.assertIsInstance(self.sidebar.folder_control, SidebarFolderControl)
        self.assertIsInstance(self.sidebar.filter_control, SidebarFilter)
        self.assertEqual(vars(self.sidebar.folder_control), {'host': self.sidebar})
        self.assertEqual(vars(self.sidebar.filter_control), {'host': self.sidebar})

    def test_default_switch_preserves_assignments_and_snapshot_is_detached(self):
        original = self.sidebar.default_folder()
        target = self.sidebar.create_folder('Music')
        self.sidebar.move_to_folder(['1001'], target)
        before = {rid: self.sidebar.folder_for(rid) for rid in self.items}
        self.sidebar.set_default_folder(target)
        self.assertIs(self.sidebar.default_folder(), self.sidebar.get_folder(target))
        self.assertEqual(original['type'], 'normal')
        self.assertEqual(before, {rid: self.sidebar.folder_for(rid) for rid in self.items})
        snapshot = self.sidebar.folder_state()
        snapshot[0]['name'] = 'changed snapshot'
        self.assertNotEqual(snapshot[0]['name'], self.sidebar.folders[0]['name'])
        self.sidebar.add_room({'room_id': '1004', 'uname': 'New'})
        self.assertEqual(self.sidebar.folder_for('1004'), target)

    def test_create_rename_and_move_deduplicate_without_duplicating_follows(self):
        target = self.sidebar.create_folder('Music')
        self.assertEqual(self.sidebar.create_folder('  Music  '), '')
        self.assertEqual(self.sidebar.create_folder('   '), '')
        self.sidebar.rename_folder(target, '  Games  ')
        self.assertEqual(self.sidebar.get_folder(target)['name'], 'Games')
        self.sidebar.move_to_folder(['1001', '1001', 'unknown', 'huya:fixture'], target)
        self.assertEqual(self.sidebar.get_folder(target)['rooms'], ['1001', 'huya:fixture'])
        self.sidebar.delete_folder(target)
        self.assertEqual(len(self.sidebar.rooms()), 3)
        self.assertEqual(self.sidebar.folder_for('1001'), self.sidebar.default_folder()['id'])

    def test_filter_keeps_order_live_only_pinyin_and_folded_selection_contract(self):
        folder = self.sidebar.create_folder('Music')
        self.sidebar.move_to_folder(['1001', 'huya:fixture'], folder)
        item = self.items['1001']
        self.sidebar._sort_selected_ids.add('1001')
        item.set_sort_selected(True)
        item.check.setChecked(True)
        self.sidebar.get_folder(folder)['collapsed'] = True
        self.sidebar._apply_filter_marks()
        self.assertTrue(item.filtered_out)
        self.assertNotIn('1001', self.sidebar._sort_selected_ids)
        self.assertFalse(item.check.isChecked())
        self.sidebar.apply_filter('  XM  ')
        self.assertEqual(self.sidebar.filter_text, 'xm')
        self.assertEqual(self.sidebar.visible_items(), [item])
        self.assertTrue(self.sidebar.get_folder(folder)['collapsed'])
        self.sidebar.apply_filter('music')
        self.assertEqual({str(i.room['room_id']) for i in self.sidebar.visible_items()}, {'1001', 'huya:fixture'})
        self.sidebar.live_only = True
        self.sidebar.refresh_filter()
        self.assertEqual(self.sidebar.visible_items(), [item])
        self.sidebar._folders_folded_by_drag.add(folder)
        self.sidebar.refresh_filter()
        self.assertTrue(item.filtered_out)

    def test_same_normalized_filter_does_not_repeat_refresh_and_refresh_order_is_preserved(self):
        self.sidebar.filter_text = 'music'
        with patch.object(self.sidebar, 'refresh_filter') as refresh, \
                patch.object(self.sidebar, 'clear_sort_selection') as clear:
            self.sidebar.apply_filter('  MUSIC  ')
            refresh.assert_not_called()
            clear.assert_not_called()
        calls = []
        with patch.object(self.sidebar, '_apply_filter_marks', side_effect=lambda: calls.append('marks')), \
                patch.object(self.sidebar.list_box, 'relayout', side_effect=lambda **kw: calls.append(('layout', kw))), \
                patch.object(self.sidebar, 'refresh_strip', side_effect=lambda: calls.append('strip')), \
                patch.object(self.sidebar, '_sync_count', side_effect=lambda: calls.append('count')):
            self.sidebar.refresh_filter()
        self.assertEqual(calls, ['marks', ('layout', {'animate': False}), 'strip', 'count'])

    def test_old_create_and_smart_dialog_factories_still_route_through_sidebar(self):
        def create(parent, callback, names):
            self.assertIs(parent, self.sidebar)
            self.assertIn(self.sidebar.default_folder()['name'], list(names))
            return callback('Created'), 'Created'
        with patch.object(module, 'create_folder_dialog', side_effect=create) as factory:
            self.sidebar.prompt_folder(['1001'])
        factory.assert_called_once()
        self.assertEqual(self.sidebar.get_folder(self.sidebar.folder_for('1001'))['name'], 'Created')
        dialog = SimpleNamespace(exec=Mock(return_value=QDialog.Accepted),
            values=lambda: {'name': 'Live copy', 'rule': {'status': 'live', 'display': 'copy'}})
        with patch.object(module, 'SmartFolderDialog', return_value=dialog) as factory:
            self.sidebar.prompt_smart_folder()
        factory.assert_called_once_with(self.sidebar, None)
        smart = next(f for f in self.sidebar.folders if f['name'] == 'Live copy')
        before = self.sidebar.folder_state()
        dialog.exec.return_value = QDialog.Rejected
        with patch.object(module, 'SmartFolderDialog', return_value=dialog):
            self.sidebar.prompt_smart_folder(smart['id'])
        self.assertEqual(self.sidebar.folder_state(), before)

    def test_create_menu_keeps_qt_parent_and_resolves_current_sidebar_actions(self):
        menu = self.sidebar._folder_create_menu()
        self.assertIs(menu.parent(), self.sidebar)
        with patch.object(self.sidebar, 'prompt_folder') as normal, \
                patch.object(self.sidebar, 'prompt_smart_folder') as smart:
            menu.actions()[0].trigger()
            menu.actions()[1].trigger()
        normal.assert_called_once_with()
        smart.assert_called_once_with()

    def test_copy_factory_reuses_original_room_and_existing_qt_children(self):
        original_count = len(self.sidebar.rooms())
        original = self.items['1001']
        with patch.object(module, 'FollowFolderButton', wraps=module.FollowFolderButton) as header, \
                patch.object(module, 'SmartFolderCard', wraps=module.SmartFolderCard) as card:
            smart = self.sidebar.create_folder('Copies', rule={'status': 'live', 'display': 'copy'})
            self.sidebar.folder_entries()
            copied = self.sidebar._smart_cards[(smart, '1001')]
            self.assertIs(copied.original, original)
            self.assertIs(copied.room, original.room)
            self.assertIs(copied.parent(), self.sidebar.list_box)
            self.assertIs(self.sidebar._folder_buttons[smart].parent(), self.sidebar.list_box)
            self.assertTrue(header.called)
            count = card.call_count
            self.sidebar.folder_entries()
            self.assertEqual(card.call_count, count)
        self.assertEqual(len(self.sidebar.rooms()), original_count)
        self.sidebar.apply_filter('not-present')
        self.sidebar.folder_entries()
        self.assertTrue(copied.isHidden())
        self.assertTrue(isValid(copied))

    def test_drag_folds_temporarily_reorders_and_restores_with_one_notification(self):
        first = self.sidebar.create_folder('First')
        second = self.sidebar.create_folder('Second')
        self.sidebar.get_folder(second)['collapsed'] = True
        previous = {f['id']: f['collapsed'] for f in self.sidebar.folders}
        changes = []
        self.sidebar.foldersChanged.connect(lambda: changes.append(True))
        self.sidebar.start_folder_drag()
        self.assertTrue(all(f['collapsed'] for f in self.sidebar.folders))
        self.assertEqual(changes, [])
        box = self.sidebar.list_box
        box.resize(220, 800)
        for index, folder in enumerate(self.sidebar.folders):
            button = self.sidebar._folder_buttons[folder['id']]
            button.setGeometry(0, index * 40, 220, 30)
            button.show()
        point = box.mapToGlobal(QPoint(10, 400))
        self.sidebar.hover_folder_drag(first, point)
        self.assertFalse(box.folder_drop_indicator.isHidden())
        self.sidebar.finish_folder_drag(first, point)
        self.assertEqual(self.sidebar.folders[-1]['id'], first)
        self.assertEqual(changes, [])
        self.sidebar.end_folder_drag()
        self.assertEqual({f['id']: f['collapsed'] for f in self.sidebar.folders}, previous)
        self.assertEqual(self.sidebar._folder_drag_previous, {})
        self.assertEqual(self.sidebar._folders_folded_by_drag, set())
        self.assertTrue(box.folder_drop_indicator.isHidden())
        self.assertEqual(changes, [True])

    def test_bulk_folder_state_refreshes_once_preserves_members_and_round_trips(self):
        normal = self.sidebar.create_folder('Music')
        self.sidebar.move_to_folder(['1001', 'huya:fixture'], normal)
        smart = self.sidebar.create_folder('Live copies', rule={
            'status': 'live', 'display': 'copy', 'sources': [normal]})
        before = self.sidebar.folder_state()
        assignments = {rid: self.sidebar.folder_for(rid) for rid in self.items}
        changes = []
        self.sidebar.foldersChanged.connect(lambda: changes.append(True))
        with patch.object(self.sidebar, '_refresh_folders', wraps=self.sidebar._refresh_folders) as refresh:
            self.sidebar.set_all_folders_collapsed(True)
            refresh.assert_called_once()
        self.assertTrue(all(folder['collapsed'] for folder in self.sidebar.folders))
        self.assertEqual(changes, [True])
        self.assertEqual(self.sidebar.visible_items(), [])
        self.assertFalse(any(getattr(entry, 'original', None) is self.items['1001']
                             for entry in self.sidebar.folder_entries()))
        saved = self.sidebar.folder_state()
        self.sidebar.set_all_folders_collapsed(True)
        self.assertEqual(changes, [True], 'An unchanged command must not save again')
        self.sidebar.set_all_folders_collapsed(False)
        self.assertEqual(changes, [True, True])
        self.assertEqual(self.sidebar.folder_state(), before)
        self.assertEqual(assignments, {rid: self.sidebar.folder_for(rid) for rid in self.items})
        copies = [entry for entry in self.sidebar.folder_entries()
                  if getattr(entry, 'original', None) is self.items['1001']]
        self.assertEqual(len(copies), 1)
        self.assertIs(copies[0], self.sidebar._smart_cards[(smart, '1001')])
        self.sidebar.set_folders(saved)
        self.assertEqual(self.sidebar.folder_state(), saved)
        self.assertTrue(all(folder['collapsed'] for folder in self.sidebar.folders))

    def test_bulk_expand_and_collapse_preserve_live_and_search_filters(self):
        normal = self.sidebar.create_folder('Music')
        self.sidebar.move_to_folder(['1001', 'huya:fixture'], normal)
        smart = self.sidebar.create_folder('Copies', rule={
            'status': 'any', 'display': 'copy', 'sources': [normal]})
        self.sidebar.live_only = True
        self.sidebar.set_all_folders_collapsed(True)
        self.sidebar.set_all_folders_collapsed(False)
        self.assertTrue(self.sidebar.live_only)
        self.assertEqual({str(item.room['room_id']) for item in self.sidebar.visible_items()},
                         {'1001', '1003'})
        self.assertTrue(self.items['huya:fixture'].filtered_out)
        offline_copy = self.sidebar._smart_cards[(smart, 'huya:fixture')]
        self.assertNotIn(offline_copy, self.sidebar.folder_entries())
        self.assertTrue(offline_copy.isHidden())
        self.sidebar.apply_filter('xm')
        self.assertEqual(self.sidebar.visible_items(), [self.items['1001']])
        self.sidebar.set_all_folders_collapsed(True)
        self.assertEqual(self.sidebar.filter_text, 'xm')
        self.assertTrue(self.sidebar.live_only)
        self.assertEqual(self.sidebar.visible_items(), [])
        self.assertFalse(any(getattr(entry, 'original', None) is self.items['1001']
                             for entry in self.sidebar.folder_entries()))
        self.sidebar.set_all_folders_collapsed(False)
        self.assertEqual(self.sidebar.filter_text, 'xm')
        self.assertEqual(self.sidebar.visible_items(), [self.items['1001']])
        self.assertTrue(any(getattr(entry, 'original', None) is self.items['1001']
                            for entry in self.sidebar.folder_entries()))
        self.sidebar.set_all_folders_collapsed(True)
        self.sidebar.apply_filter('other')
        self.assertTrue(all(folder['collapsed'] for folder in self.sidebar.folders))
        self.assertEqual(self.sidebar.visible_items(), [self.items['1003']],
                         'A new search still temporarily exposes matching folded rooms')

    def test_bulk_toolbar_button_toggles_mixed_state_without_changing_filters(self):
        normal = self.sidebar.create_folder('Music')
        self.sidebar.move_to_folder(['1001'], normal)
        self.sidebar.resize(320, 720)
        self.sidebar.show()
        self.sidebar.live_only = True
        self.sidebar.refresh_filter()
        self.sidebar.toggle_folder(normal)
        button = self.sidebar.navigation.folder_toggle_button
        self.app.processEvents()
        self.assertTrue(button.isVisible())
        self.assertIn('全部展开', button.toolTip())
        QTest.mouseClick(button, Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(all(not folder['collapsed'] for folder in self.sidebar.folders))
        self.assertIn('全部折叠', button.toolTip())
        self.assertTrue(self.sidebar.live_only)
        self.assertTrue(self.items['huya:fixture'].filtered_out)
        QTest.mouseClick(button, Qt.LeftButton)
        self.app.processEvents()
        self.assertTrue(all(folder['collapsed'] for folder in self.sidebar.folders))
        self.assertIn('全部展开', button.toolTip())
        self.assertEqual(self.sidebar.visible_items(), [])

    def test_bulk_commands_during_folder_drag_do_not_replace_restore_state(self):
        first = self.sidebar.create_folder('First')
        self.sidebar.create_folder('Second')
        self.sidebar.toggle_folder(first)
        previous = {folder['id']: folder['collapsed'] for folder in self.sidebar.folders}
        changes = []
        self.sidebar.foldersChanged.connect(lambda: changes.append(True))
        self.sidebar.start_folder_drag()
        self.sidebar.set_all_folders_collapsed(False)
        self.sidebar.toggle_all_folders()
        self.assertEqual(self.sidebar._folder_drag_previous, previous)
        self.assertTrue(all(folder['collapsed'] for folder in self.sidebar.folders))
        self.assertEqual(changes, [])
        self.sidebar.end_folder_drag()
        self.assertEqual({folder['id']: folder['collapsed'] for folder in self.sidebar.folders}, previous)
        self.assertEqual(changes, [True])

    def test_previous_mode_restores_only_originally_closed_folders(self):
        first = self.sidebar.create_folder('Closed')
        second = self.sidebar.create_folder('Open')
        self.sidebar.move_to_folder(['1001'], first)
        self.sidebar.move_to_folder(['1003'], second)
        self.sidebar.toggle_folder(first)
        self.sidebar.set_folder_collapse_mode('previous')
        self.sidebar.live_only = True
        self.sidebar.toggle_all_folders()
        self.assertTrue(all(not folder['collapsed'] for folder in self.sidebar.folders))
        self.assertEqual(self.sidebar._bulk_fold_previous, {first})
        self.sidebar.set_folder_collapse_mode('previous')
        self.sidebar.set_all_folders_collapsed(False)
        self.assertEqual(self.sidebar._bulk_fold_previous, {first}, 'Unrelated saves or repeated expand must retain the original snapshot')
        created = self.sidebar.create_folder('Added after expand')
        self.sidebar.toggle_all_folders()
        self.assertTrue(self.sidebar.get_folder(first)['collapsed'])
        self.assertFalse(self.sidebar.get_folder(second)['collapsed'])
        self.assertFalse(self.sidebar.get_folder(created)['collapsed'])
        self.assertFalse(self.sidebar.default_folder()['collapsed'])
        self.assertIsNone(self.sidebar._bulk_fold_previous)
        self.assertTrue(self.sidebar.live_only)
        self.assertTrue(self.items['huya:fixture'].filtered_out)
        self.assertEqual(self.sidebar.folder_for('1001'), first)
        self.sidebar.set_folder_collapse_mode('all')
        self.sidebar.set_all_folders_collapsed(True)
        self.assertTrue(all(folder['collapsed'] for folder in self.sidebar.folders))

    def test_previous_snapshot_is_cleared_on_mode_change_reload_and_deletion(self):
        closed = self.sidebar.create_folder('Closed')
        self.sidebar.toggle_folder(closed)
        self.sidebar.set_folder_collapse_mode('previous')
        self.sidebar.toggle_all_folders()
        self.sidebar.delete_folder(closed)
        self.assertIsNone(self.sidebar._bulk_fold_previous)
        self.assertFalse(self.sidebar.navigation.folder_toggle_button.isEnabled())
        self.sidebar.set_folder_collapse_mode('all')
        self.sidebar.set_all_folders_collapsed(True)
        self.sidebar.set_folder_collapse_mode('previous')
        self.sidebar.toggle_all_folders()
        self.assertIsNotNone(self.sidebar._bulk_fold_previous)
        self.sidebar.set_folder_collapse_mode('all')
        self.assertIsNone(self.sidebar._bulk_fold_previous)
        self.sidebar.set_folder_collapse_mode('previous')
        self.assertFalse(self.sidebar.navigation.folder_toggle_button.isEnabled())
        self.sidebar.set_folder_collapse_mode('all')
        self.sidebar.set_all_folders_collapsed(True)
        self.sidebar.set_folder_collapse_mode('previous')
        self.sidebar.set_all_folders_collapsed(False)
        self.sidebar.set_folders(self.sidebar.folder_state())
        self.assertIsNone(self.sidebar._bulk_fold_previous)

    def test_previous_restore_respects_current_search_and_icon_filters(self):
        closed = self.sidebar.create_folder('Closed')
        self.sidebar.move_to_folder(['1001'], closed)
        self.sidebar.toggle_folder(closed)
        self.sidebar.apply_filter('xm')
        self.sidebar.set_folder_collapse_mode('previous')
        self.sidebar.set_all_folders_collapsed(False)
        self.sidebar.toggle_all_folders()
        self.assertEqual(self.sidebar.filter_text, 'xm')
        self.assertEqual(self.sidebar.visible_items(), [])
        self.sidebar.apply_filter('other')
        self.assertEqual(self.sidebar.visible_items(), [self.items['1003']])
        self.sidebar.apply_filter('')
        self.sidebar.set_folder_collapse_mode('all')
        self.sidebar.set_all_folders_collapsed(False)
        self.sidebar.show()
        self.app.processEvents()
        navigation = self.sidebar.navigation
        self.assertEqual(navigation.all_button.text(), '')
        self.assertEqual(navigation.live_button.text(), '')
        self.assertEqual(navigation.all_button.accessibleName(), '全部直播间')
        self.assertIn('3', navigation.all_button.toolTip())
        QTest.mouseClick(navigation.live_button, Qt.LeftButton)
        self.assertTrue(self.sidebar.live_only)
        self.assertTrue(navigation.live_button.isChecked())
        self.assertFalse(navigation.all_button.isChecked())
        self.assertIn('2', navigation.live_button.toolTip())
        self.assertTrue(self.items['huya:fixture'].filtered_out)
        QTest.mouseClick(navigation.all_button, Qt.LeftButton)
        self.assertFalse(self.sidebar.live_only)
        self.assertTrue(navigation.all_button.isChecked())
        self.assertFalse(navigation.live_button.isChecked())
        self.assertFalse(self.items['huya:fixture'].filtered_out)

    def test_invalid_drop_keeps_folder_order_and_clears_indicator(self):
        folder = self.sidebar.create_folder('First')
        before = [f['id'] for f in self.sidebar.folders]
        point = self.sidebar.list_box.mapToGlobal(QPoint(-100, -100))
        self.sidebar.hover_folder_drag(folder, point)
        self.sidebar.finish_folder_drag(folder, point)
        self.assertEqual([f['id'] for f in self.sidebar.folders], before)
        self.assertTrue(self.sidebar.list_box.folder_drop_indicator.isHidden())

    def test_delete_releases_headers_and_copies_without_deleting_original_cards(self):
        smart = self.sidebar.create_folder('Copies', rule={'status': 'live', 'display': 'copy'})
        copy = self.sidebar._smart_cards[(smart, '1001')]
        timer = copy._preview_timer
        header = self.sidebar._folder_buttons[smart]
        original = self.items['1001']
        self.sidebar.delete_folder(smart)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(header))
        self.assertFalse(isValid(copy))
        self.assertFalse(isValid(timer))
        self.assertTrue(isValid(original))
        self.assertEqual(len(self.sidebar.rooms()), 3)

    def test_parent_deletion_releases_folder_children_and_original_callbacks(self):
        smart = self.sidebar.create_folder('Copies', rule={'status': 'live', 'display': 'copy'})
        copy = self.sidebar._smart_cards[(smart, '1001')]
        timer = copy._preview_timer
        header = self.sidebar._folder_buttons[smart]
        self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(header))
        self.assertFalse(isValid(copy))
        self.assertFalse(isValid(timer))
        self.assertFalse(isValid(self.items['1001']))


if __name__ == '__main__':
    unittest.main()
