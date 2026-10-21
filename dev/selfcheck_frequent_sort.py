"""常看计分、显式启用、稳定排序、智能副本、手动刷新和本机持久化。"""
from contextlib import ExitStack
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QMenu
from ddm import app as app_module, config, follow_folders
from ddm.watch_history import WatchHistory
from ddm.widgets import Sidebar, SmartFolderDialog

NOW = datetime(2026, 10, 19, 12).timestamp()
DAY = 86400


def record(score, ago=0):
    stamp = NOW - ago * DAY
    return dict(score=score, updated=stamp, day=datetime.fromtimestamp(stamp).date().isoformat())


def watch(history, rid, *, now=NOW, seconds=60):
    changed = False
    history.sample({rid}, {rid}, 1, now)
    for _ in range(seconds):
        changed |= history.sample({rid}, {rid}, 1, now)
    return changed


class HistoryTests(unittest.TestCase):
    def test_opt_in_threshold_daily_limit_and_decay(self):
        history = WatchHistory()
        history.select('1')
        self.assertFalse(watch(history, '1'))
        history.set_enabled(True)
        self.assertFalse(watch(history, '1'), '自动恢复或悬停不能产生主动观看记录')
        history.select('1')
        history.sample({'1'}, {'1'}, 1, NOW)
        for _ in range(59):
            self.assertFalse(history.sample({'1'}, {'1'}, 1, NOW))
        self.assertTrue(history.sample({'1'}, {'1'}, 1, NOW))
        self.assertEqual(history.scores(NOW)['1'], 1)
        history.select('1')
        self.assertFalse(watch(history, '1'))
        self.assertAlmostEqual(history.scores(NOW + 7 * DAY)['1'], 0.5)
        self.assertTrue(watch(history, '1', now=NOW + DAY))
        self.assertAlmostEqual(history.scores(NOW + DAY)['1'], 2 ** (-1 / 7) + 1)

    def test_pauses_sleep_duplicates_removal_and_disable(self):
        history = WatchHistory()
        history.set_enabled(True)
        history.select('1')
        history.sample({'1'}, {'1'}, 1, NOW)
        history.sample({'1'}, {'1'}, 3600, NOW)
        self.assertEqual(history._seconds['1'], 0)
        history.sample({'1'}, set(), 1, NOW)
        history.sample({'1'}, {'1'}, 1, NOW)
        self.assertEqual(history._seconds['1'], 0)
        for _ in range(59):
            history.sample({'1'}, ['1', '1'], 1, NOW)
        self.assertFalse(history.records)
        history.sample(set(), set(), 1, NOW)
        self.assertFalse(history._seconds)
        history.select('1')
        history.set_enabled(False)
        history.set_enabled(True)
        self.assertFalse(watch(history, '1'))

    def test_validation_roundtrip_platform_keys_and_clear(self):
        history = WatchHistory({'1': record(2), 'huya:1': record(3),
                                'bad': record(float('nan')), 'bool': record(True),
                                'date': dict(score=2, updated=NOW, day='invalid')})
        self.assertEqual(set(history.records), {'1', 'huya:1'})
        state = history.state()
        restored = WatchHistory(state)
        state['1']['score'] = 100
        self.assertEqual(restored.scores(NOW)['1'], 2)
        self.assertEqual(restored.scores(NOW)['huya:1'], 3)
        restored.clear()
        self.assertEqual(restored.state(), {})


class SidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        rooms = [dict(room_id=rid, uname=rid, live=rid != '4') for rid in ('1', '2', '3', '4')]
        self.sidebar = Sidebar(rooms, auto_compact=False)
        self.addCleanup(self.sidebar.close)
        self.sidebar.watch_history = WatchHistory({'1': record(1), '2': record(5), '4': record(100)})
        self.clock = patch('ddm.watch_history.time.time', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def order(self):
        return [item.room['room_id'] for item in self.sidebar.items()]

    def test_label_pins_live_first_stability_and_explicit_refresh(self):
        self.assertEqual(dict(self.sidebar.SORT_MODES)['frequent'], '常看优先')
        self.assertFalse(self.sidebar.watch_history.enabled)
        self.sidebar.apply_pins(['3', '1'])
        self.sidebar.set_sort_mode('frequent')
        self.assertEqual(self.order(), ['3', '1', '2', '4'])
        self.sidebar.apply_pins([])
        self.assertEqual(self.order(), ['2', '1', '3', '4'])
        menu = QMenu()
        self.sidebar.add_folder_sort_menu(menu, self.sidebar.get_folder(follow_folders.UNCLASSIFIED))
        option = next(action for action in menu.actions() if action.text() == '常看优先')
        self.assertTrue(option.isChecked())
        self.assertIn('手动刷新', option.toolTip())
        self.sidebar.watch_history.records['3'] = record(10)
        self.sidebar.resort()
        self.assertEqual(self.order(), ['2', '1', '3', '4'], '后台重排不能应用新观看分数')
        self.sidebar.refresh_frequent_order()
        self.assertEqual(self.order(), ['3', '2', '1', '4'])
        self.sidebar.set_sort_mode('custom')
        self.assertFalse(self.sidebar.watch_history.enabled)
        self.assertTrue(self.sidebar.watch_history.records)
        self.sidebar.set_sort_mode('frequent')
        self.assertEqual(self.order(), ['3', '2', '1', '4'])

    def test_normal_and_smart_copy_folders(self):
        folder = self.sidebar.create_folder('常看', sort='frequent')
        self.sidebar.move_to_folder(['1', '2'], folder)
        self.assertEqual(self.order()[:2], ['2', '1'])
        smart = self.sidebar.create_folder('智能副本', sort='frequent', rule={
            'status': 'any', 'platforms': [], 'sources': [], 'display': 'copy'})
        dialog = SmartFolderDialog(self.sidebar, self.sidebar.get_folder(smart))
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.sort_combo.currentData(), 'frequent')
        self.sidebar.resize(260, 1200)
        self.sidebar.show()
        self.app.processEvents()
        copies = [item for item in self.sidebar.folder_entries()
                  if getattr(item, 'original', None) is not None]
        self.assertEqual([item.room['room_id'] for item in copies], ['2', '1', '3', '4'])
        self.sidebar.apply_pins(['3', '1'])
        copies = [item for item in self.sidebar.folder_entries()
                  if getattr(item, 'original', None) is not None]
        self.assertEqual([item.room['room_id'] for item in copies], ['3', '1', '2', '4'])
        self.assertEqual(self.sidebar.get_folder(follow_folders.UNCLASSIFIED)['sort'], 'custom')

    def test_context_menus_do_not_offer_history_erasure(self):
        self.sidebar.set_sort_mode('frequent')
        before = dict(self.sidebar.watch_history.records)
        order = self.order()
        self.assertFalse(hasattr(self.sidebar, '_clear_watch_history'))
        for folder in self.sidebar.folders:
            menu = self.sidebar._folder_buttons[folder['id']]._context_menu()
            self.assertFalse(any('清除常看' in action.text() for action in menu.actions()))
            menu.deleteLater()
        self.assertEqual(self.sidebar.watch_history.records, before)
        self.assertEqual(self.order(), order)

    def test_manual_reordering_disables_collection_when_no_folder_uses_it(self):
        self.sidebar.set_sort_mode('frequent')
        self.sidebar.reorder_items(['4'], 0)
        self.assertEqual(self.sidebar.sort_mode, 'custom')
        self.assertFalse(self.sidebar.watch_history.enabled)
        self.assertTrue(self.sidebar.watch_history.records)


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch('ddm.app.QTimer.singleShot'))
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'load_room_avatars', 'sync_danmaku'):
            self.patches.enter_context(patch.object(app_module.MainWindow, method))
        rooms = [dict(room_id=rid, uname=rid, live=True) for rid in ('1', '2')]
        self.window = app_module.MainWindow(rooms, [dict(room) for room in rooms], layout_id='2x2',
            state={'plugins_enabled': [], 'settings': {'auto_quality': False,
                'recording_enabled': False, 'recording_replay_enabled': False, 'danmaku_enabled': False}})
        self.addCleanup(self.window.close)
        self.window.show()
        self.app.processEvents()
        self.window._watch_history_timer.stop()
        self.clock = 100.0
        self.window._watch_history_last_tick = self.clock
        self.history = self.window.sidebar.watch_history
        for tile in self.window.wall.tiles[:2]:
            self.window.players[tile] = SimpleNamespace(state='playing', paused=False, release=lambda: None)

    def tick(self, count=1):
        for _ in range(count):
            self.clock += 1
            with patch('ddm.app.time.monotonic', return_value=self.clock), \
                    patch('ddm.watch_history.time.time', return_value=NOW):
                self.window._tick_watch_history()

    def test_active_intent_no_restore_preview_reconnect_or_immediate_reorder(self):
        self.window.sidebar.set_sort_mode('frequent')
        self.tick(70)
        self.assertFalse(self.history.records, '启动恢复的格子不能计次')
        self.window._on_tile_clicked({'room_id': '2'})
        self.tick(61)
        self.assertEqual(set(self.history.records), {'2'})
        self.assertEqual([item.room['room_id'] for item in self.window.sidebar.items()], ['1', '2'])
        self.tick(70)
        self.assertEqual(self.history.records['2']['score'], 1)
        self.window.refresh_follow()
        self.assertEqual([item.room['room_id'] for item in self.window.sidebar.items()], ['2', '1'])
        saved = self.window.current_state()
        self.assertEqual(WatchHistory(saved['watch_history']).scores(NOW)['2'], 1)
        self.assertEqual(follow_folders.normalize_folders(saved['follow_folders'])[0]['sort'], 'frequent')
        with tempfile.TemporaryDirectory(prefix='ddm-watch-state-') as directory, \
                patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')), \
                patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            config.save(saved)
            restored_state = config.load()
        with patch('ddm.watch_history.time.time', return_value=NOW):
            rooms, wall = config.build_rooms(restored_state)
            restored = app_module.MainWindow(rooms, wall, layout_id='2x2', state=restored_state)
            self.addCleanup(restored.close)
        self.assertEqual([item.room['room_id'] for item in restored.sidebar.items()], ['2', '1'])
        self.assertTrue(restored.sidebar.watch_history.enabled)
        self.assertFalse(restored.sidebar.watch_history._seconds, '重启不能恢复上次的主动观看会话')

    def test_pause_buffering_hidden_window_and_user_drop(self):
        self.window.sidebar.set_sort_mode('frequent')
        with patch.object(self.window, '_hot_swap', return_value=False):
            self.window._on_room_dropped(self.window.wall.tiles[2], '1')
        tile = self.window._tile_of('1')
        player = SimpleNamespace(state='buffering', paused=False, release=lambda: None)
        self.window.players[tile] = player
        self.tick(70)
        self.assertFalse(self.history.records)
        player.state = 'playing'
        tile.paused = True
        self.tick(70)
        self.assertFalse(self.history.records)
        tile.paused = False
        self.window.hide()
        self.tick(70)
        self.assertFalse(self.history.records)
        self.window.show()
        self.app.processEvents()
        self.tick(61)
        self.assertIn('1', self.history.records)

    def test_add_and_duplicate_tiles_only_count_once_and_preserve_order(self):
        self.window.sidebar.set_sort_mode('frequent')
        self.window.add_to_wall({'room_id': '2', 'uname': '2', 'live': True})
        self.window.wall.tiles[0].set_room(dict(self.window.wall.tiles[1].room))
        self.tick(61)
        self.assertEqual(self.history.records['2']['score'], 1)
        self.tick(80)
        self.assertEqual(self.history.records['2']['score'], 1)
        self.assertEqual([item.room['room_id'] for item in self.window.sidebar.items()], ['1', '2'])


if __name__ == '__main__':
    unittest.main()
