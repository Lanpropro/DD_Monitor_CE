"""Selection/order boundaries with hidden Qt controls; temporary data, no media or accounts."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QApplication, QMenu
from shiboken6 import isValid
from ddm import config, images, motion
from ddm.sidebar_widgets import Sidebar
from ddm.sidebar_selection import SidebarSelection
from ddm.sidebar_sort import SidebarSort
from ddm.watch_history import SORT_TIP


class SidebarOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-sidebar-order-'))
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', directory))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        self.stack.enter_context(patch.object(images, 'REPO', directory))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.sidebar = Sidebar([{'room_id': rid, 'uname': rid.upper(), 'live': index % 2 == 0}
            for index, rid in enumerate(('p1', 'p2', 'a', 'b', 'c', 'd'))], auto_compact=False)
        self.items = {item.room['room_id']: item for item in self.sidebar.items()}

    def tearDown(self):
        if isValid(self.sidebar):
            self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()

    def ids(self):
        return [item.room['room_id'] for item in self.sidebar.items()]

    def test_independent_imports_legacy_identity_and_single_state_owner(self):
        for name in ('sidebar_selection', 'sidebar_sort'):
            code = 'import sys; import ddm.' + name + '; ' + \
                "assert not {'ddm.app','ddm.widgets','ddm.sidebar_widgets','ddm.player','mpv'}.intersection(sys.modules)"
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        from ddm.widgets import Sidebar as OldSidebar
        self.assertIs(OldSidebar, Sidebar)
        self.assertIsInstance(self.sidebar.selection_control, SidebarSelection)
        self.assertIsInstance(self.sidebar.sort_control, SidebarSort)
        self.assertEqual(vars(self.sidebar.selection_control), {'host': self.sidebar})
        self.assertEqual(vars(self.sidebar.sort_control), {'host': self.sidebar})

    def test_ctrl_shift_selection_uses_visible_order_and_retains_plain_click_anchor(self):
        self.sidebar.select_sort_item('a', Qt.ControlModifier)
        self.sidebar.select_sort_item('c', Qt.ShiftModifier)
        self.assertEqual(self.sidebar.selected_sort_ids(), ['a', 'b', 'c'])
        self.sidebar.select_sort_item('p1', Qt.ControlModifier)
        self.assertEqual(self.sidebar.selected_sort_ids(), ['p1', 'a', 'b', 'c'])
        self.sidebar.select_sort_item('b', Qt.ControlModifier)
        self.assertEqual(self.sidebar.selected_sort_ids(), ['p1', 'a', 'c'])
        self.sidebar.select_sort_item('a', Qt.NoModifier)
        self.assertEqual(self.sidebar.selected_sort_ids(), [])
        self.assertEqual(self.sidebar._sort_anchor, 'a')
        self.sidebar.apply_filter('p')
        self.sidebar.select_sort_item('p1', Qt.ControlModifier)
        self.sidebar.select_sort_item('p2', Qt.ShiftModifier)
        self.assertEqual(self.sidebar.selected_sort_ids(), ['p1', 'p2'])

    def test_batch_entry_clears_search_and_old_qt_signal_updates_count(self):
        self.sidebar.select_sort_item('a', Qt.ControlModifier)
        self.sidebar.search.setText('a')
        self.sidebar.batch_button.click()
        self.assertTrue(self.sidebar.select_mode)
        self.assertEqual(self.sidebar.filter_text, '')
        self.assertEqual(self.sidebar._sort_selected_ids, set())
        self.items['a'].check.click()
        self.assertEqual(self.sidebar.batch_label.text(), '已选 1 个')
        self.assertEqual(self.sidebar.selected_sort_ids(), ['a'])
        self.items['b'].check.click()
        self.assertEqual(self.sidebar.batch_label.text(), '已选 2 个')

    def test_batch_drag_excludes_filtered_checks_and_delete_emits_current_room_values(self):
        self.sidebar.set_select_mode(True)
        self.items['a'].check.setChecked(True)
        self.items['b'].check.setChecked(True)
        self.items['b'].set_filtered_out(True)
        self.assertEqual(self.sidebar.selected_sort_ids(), ['a'])
        self.assertEqual(self.sidebar.dragged_room_ids('a'), ['a'])
        deleted = []
        self.sidebar.deleteRequested.connect(deleted.append)
        self.sidebar._emit_delete()
        self.assertEqual(deleted, [[self.items['a'].room, self.items['b'].room]])
        self.assertFalse(self.sidebar.select_mode)

    def test_dragging_unselected_card_clears_only_normal_sort_selection(self):
        self.sidebar.select_sort_item('a', Qt.ControlModifier)
        self.sidebar.select_sort_item('b', Qt.ControlModifier)
        self.assertEqual(self.sidebar.dragged_room_ids('a'), ['a', 'b'])
        self.assertEqual(self.sidebar.dragged_room_ids('c'), ['c'])
        self.assertEqual(self.sidebar._sort_selected_ids, set())
        self.assertIsNone(self.sidebar._sort_anchor)
        self.sidebar.set_select_mode(True)
        self.items['a'].check.setChecked(True)
        self.assertEqual(self.sidebar.dragged_room_ids('c'), ['c'])
        self.assertTrue(self.items['a'].is_checked())

    def test_visible_drop_conversion_and_preview_do_not_mutate_saved_order(self):
        self.sidebar.apply_filter('p')
        self.assertEqual(self.sidebar._full_drop_index(0), 0)
        self.assertEqual(self.sidebar._full_drop_index(2), 2)
        self.sidebar.apply_filter('not-present')
        self.assertEqual(self.sidebar._full_drop_index(0), 6)
        self.sidebar.apply_filter('')
        before, saved = self.ids(), list(self.sidebar.custom_order)
        preview = self.sidebar._reordered_items(['a', 'b'], 6)
        self.assertEqual([i.room['room_id'] for i in preview], ['p1', 'p2', 'c', 'd', 'a', 'b'])
        self.assertEqual(self.ids(), before)
        self.assertEqual(self.sidebar.custom_order, saved)

    def test_group_move_respects_pins_folders_and_emits_order_after_commit(self):
        folder = self.sidebar.create_folder('Other')
        self.sidebar.move_to_folder(['c', 'd'], folder)
        self.sidebar.apply_pins(['p1', 'p2'])
        self.sidebar.set_folder_sort(folder, 'live')
        changes = []
        self.sidebar.orderChanged.connect(lambda: changes.append(('order', list(self.sidebar.custom_order))))
        self.sidebar.pinChanged.connect(lambda value: changes.append(('pins', value)))
        self.assertTrue(self.sidebar.reorder_items(['p2', 'b'], 0))
        default = self.sidebar.default_folder()['id']
        self.assertEqual([rid for rid in self.ids() if self.sidebar.folder_for(rid) == default],
            ['p2', 'p1', 'b', 'a'])
        self.assertEqual(self.sidebar.get_folder(folder)['sort'], 'live')
        self.assertEqual(self.sidebar.pinned, ['p2', 'p1'])
        self.assertEqual([kind for kind, _ in changes], ['pins', 'order'])
        self.assertEqual(changes[-1][1], self.sidebar.custom_order)

    def test_noop_or_unknown_moves_do_not_save_or_emit(self):
        changes = []
        self.sidebar.orderChanged.connect(lambda: changes.append(True))
        before = self.ids(), list(self.sidebar.custom_order), self.sidebar.folder_state()
        self.assertFalse(self.sidebar.reorder_items(['unknown'], 0))
        self.assertFalse(self.sidebar.reorder_item('p1', 0))
        self.assertEqual((self.ids(), self.sidebar.custom_order, self.sidebar.folder_state()), before)
        self.assertEqual(changes, [])

    def test_import_custom_orders_and_invalid_sort_fallback_keep_notification_contract(self):
        self.sidebar.set_import_order(['d', 'a', 'missing'])
        self.sidebar.set_custom_order(['b', 'b', 'missing', 'a'])
        self.assertEqual(self.sidebar.custom_order, ['b', 'a', 'p1', 'p2', 'c', 'd'])
        self.sidebar.set_sort_mode('imported', notify=False)
        self.assertEqual(self.ids(), ['d', 'a', 'p1', 'p2', 'b', 'c'])
        changes = []
        self.sidebar.sortChanged.connect(changes.append)
        self.sidebar.set_sort_mode('not-a-mode')
        self.assertEqual(changes, ['custom'])
        self.assertEqual(self.ids(), ['b', 'a', 'p1', 'p2', 'c', 'd'])

    def test_freeze_current_order_only_updates_requested_folder(self):
        other = self.sidebar.create_folder('Other')
        self.sidebar.move_to_folder(['a', 'b'], other)
        original_other_slots = [rid for rid in self.sidebar.custom_order if rid not in ('a', 'b')]
        self.sidebar.set_folder_sort(other, 'offline')
        shown = [rid for rid in self.ids() if rid in ('a', 'b')]
        self.sidebar.freeze_current_order(other)
        self.assertEqual(self.sidebar.get_folder(other)['sort'], 'custom')
        self.assertEqual([rid for rid in self.sidebar.custom_order if rid in ('a', 'b')], shown)
        self.assertEqual([rid for rid in self.sidebar.custom_order if rid not in ('a', 'b')], original_other_slots)

    def test_watch_history_owner_and_refresh_cache_remain_on_sidebar(self):
        history = self.sidebar.watch_history
        folder = self.sidebar.default_folder()
        folder['sort'] = 'frequent'
        with patch.object(history, 'scores', return_value={'a': 9, 'b': 2}) as scores:
            self.sidebar._sync_watch_history_mode()
            scores.assert_called_once_with()
            self.assertEqual(self.sidebar._frequent_scores, {'a': 9, 'b': 2})
            self.sidebar._sync_watch_history_mode()
            scores.assert_called_once()
            self.sidebar.refresh_frequent_order()
            self.assertEqual(scores.call_count, 2)
        self.assertIs(self.sidebar.watch_history, history)
        self.assertEqual(self.sidebar._frequent_folders, {folder['id']})
        folder['sort'] = 'custom'
        self.sidebar._sync_watch_history_mode()
        self.assertEqual(self.sidebar._frequent_folders, set())

    def test_sort_menu_parent_exclusive_group_tooltip_and_dynamic_actions(self):
        menu = QMenu(self.sidebar)
        folder = self.sidebar.default_folder()
        self.sidebar.add_folder_sort_menu(menu, folder)
        group = menu.findChild(QActionGroup)
        self.assertIs(group.parent(), menu)
        self.assertTrue(group.isExclusive())
        self.assertEqual(sum(action.isChecked() for action in group.actions()), 1)
        with patch.object(self.sidebar, 'set_folder_sort') as choose, \
                patch.object(self.sidebar, 'freeze_current_order') as freeze:
            for (mode, _label), action in zip(self.sidebar.SORT_MODES, group.actions()):
                action.trigger()
                choose.assert_called_with(folder['id'], mode)
                if mode == 'frequent':
                    self.assertEqual(action.toolTip(), SORT_TIP)
            menu.actions()[-1].trigger()
            freeze.assert_called_once_with(folder['id'])

    def test_resort_keeps_filter_layout_count_strip_order_and_animation_arguments(self):
        calls = []
        revealing = (self.items['a'],)
        with patch.object(self.sidebar, '_apply_filter_marks', side_effect=lambda: calls.append('filter')), \
                patch.object(self.sidebar.list_box, 'relayout', side_effect=lambda **kw: calls.append(('layout', kw))), \
                patch.object(self.sidebar, '_sync_count', side_effect=lambda: calls.append('count')), \
                patch.object(self.sidebar, 'refresh_strip', side_effect=lambda: calls.append('strip')):
            self.sidebar.resort(True, duration=280, revealing=revealing, viewport_only=True)
        self.assertEqual(calls, ['filter', ('layout', {'animate': True, 'duration': 280,
            'revealing': revealing, 'viewport_only': True}), 'count', 'strip'])

    def test_parent_deletion_releases_menu_group_cards_and_timers(self):
        menu = QMenu(self.sidebar)
        self.sidebar.add_folder_sort_menu(menu, self.sidebar.default_folder())
        group = menu.findChild(QActionGroup)
        timer = self.sidebar._card_entry_timer
        self.assertIs(self.items['a'].parent(), self.sidebar.list_box)
        self.sidebar.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(menu))
        self.assertFalse(isValid(group))
        self.assertFalse(isValid(timer))
        self.assertFalse(isValid(self.items['a']))


if __name__ == '__main__':
    unittest.main()
