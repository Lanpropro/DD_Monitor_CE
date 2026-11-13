"""Status orchestration with synthetic signals; no live requests or application window."""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.room_status import RoomStatus


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class Poller:
    instances = []

    def __init__(self, room_ids, parent, **kwargs):
        self.room_ids, self.parent, self.kwargs = list(room_ids), parent, kwargs
        self.updated, self.failed, self.finished, self.status_ready = [Signal() for _ in range(4)]
        self.running = self.deleted = False
        self.instances.append(self)

    def isRunning(self):
        return self.running

    def start(self):
        self.running = True

    def deleteLater(self):
        self.deleted = True

    def finish(self):
        self.running = False
        self.finished.emit()


class Host:
    def __init__(self, rooms=None, tiles=None):
        self._closing = self._refresh_queued = self._startup_status_complete = False
        self._poller = self._stats_poller = None
        self.wall = SimpleNamespace(tiles=tiles or [])
        self.sidebar = SimpleNamespace(rooms=lambda: rooms or [], set_refreshing=Mock(),
            refresh_frequent_order=Mock(), count_label=SimpleNamespace(setText=Mock()))
        self.plugins = SimpleNamespace(platforms={'fixture': object()})
        self.load_room_avatars = Mock()
        self._on_status_updated = Mock()
        self._on_status_failed = Mock()
        self.room_status = RoomStatus(self)
        self._on_poller_finished = self.room_status.status_finished
        self._on_stats_finished = self.room_status.stats_finished
        self._on_stats_updated = self.room_status.apply_stats
        self.refresh_status = Mock(side_effect=lambda **kwargs:
            self.room_status.refresh_status(Poller, **kwargs))


class RoomStatusTests(unittest.TestCase):
    def setUp(self):
        Poller.instances = []

    def test_import_keeps_main_window_and_player_out(self):
        subprocess.run([sys.executable, '-c',
            'import sys; import ddm.room_status; '
            'assert not {"ddm.app", "ddm.widgets", "ddm.player", "mpv"}.intersection(sys.modules)'],
            cwd=ROOT, check=True, timeout=15)

    def test_status_collects_unique_rooms_and_preserves_parent_and_platform_snapshot(self):
        room = {'room_id': '1001'}
        host = Host([room, room, {'room_id': 'douyu:2'}],
                    [SimpleNamespace(room=room), SimpleNamespace(room={'room_id': 'youtube:3'})])
        host.refresh_status()
        poller = host._poller
        self.assertEqual(poller.room_ids, ['1001', 'douyu:2', 'youtube:3'])
        self.assertIs(poller.parent, host)
        self.assertEqual(poller.kwargs['platforms'], host.plugins.platforms)
        self.assertIsNot(poller.kwargs['platforms'], host.plugins.platforms)
        poller.updated.emit({'fixture': {'live': True}})
        host._on_status_updated.assert_called_once_with({'fixture': {'live': True}})

    def test_numeric_rooms_do_not_require_platform_argument(self):
        host = Host([{'room_id': '1001'}])
        host.refresh_status()
        self.assertEqual(host._poller.kwargs, {})
        self.assertIs(host._poller.parent, host)

    def test_repeated_refresh_queues_one_round_and_old_ready_cannot_stop_it(self):
        host = Host([{'room_id': '1001'}])
        host.refresh_status()
        first = host._poller
        host.refresh_status()
        self.assertFalse(host._refresh_queued)
        for _ in range(5):
            host.refresh_status(force=True)
        self.assertEqual(len(Poller.instances), 1)
        self.assertTrue(host._refresh_queued)
        first.finish()
        current = host._poller
        self.assertIsNot(current, first)
        self.assertEqual(len(Poller.instances), 2)
        self.assertTrue(first.deleted and host._startup_status_complete)
        self.assertFalse(host._refresh_queued)
        host.sidebar.set_refreshing.reset_mock()
        first.status_ready.emit()
        host.sidebar.set_refreshing.assert_not_called()
        current.status_ready.emit()
        host.sidebar.set_refreshing.assert_called_once_with(False)
        self.assertTrue(current.running)

    def test_stale_finished_deletes_only_its_sender(self):
        host = Host([{'room_id': '1001'}])
        host.refresh_status()
        current = host._poller
        stale = Poller(['old'], host)
        host._refresh_queued = True
        host.room_status.status_finished(stale)
        self.assertTrue(stale.deleted)
        self.assertIs(host._poller, current)
        self.assertFalse(current.deleted)
        self.assertTrue(host._refresh_queued)
        host.sidebar.set_refreshing.assert_not_called()

    def test_stats_filters_sources_and_updates_only_nonempty_watched_text(self):
        tiles = [SimpleNamespace(room={'room_id': rid, 'live': live}, set_watched=Mock())
                 for rid, live in (('1001', True), ('1002', False), ('douyu:3', True), ('', True))]
        host = Host(tiles=tiles)
        host.room_status.refresh_stats(Poller)
        poller = host._stats_poller
        self.assertEqual(poller.room_ids, ['1001'])
        self.assertIs(poller.parent, host)
        host.room_status.refresh_stats(Poller)
        self.assertEqual(len(Poller.instances), 1)
        poller.updated.emit({'1001': {'online_text': '123'}, '1002': {'online_text': ''}})
        tiles[0].set_watched.assert_called_once_with('123')
        tiles[1].set_watched.assert_not_called()
        stale = Poller(['old'], host)
        host.room_status.stats_finished(stale)
        self.assertIs(host._stats_poller, poller)
        self.assertTrue(stale.deleted)
        poller.finish()
        self.assertIsNone(host._stats_poller)
        self.assertTrue(poller.deleted)

    def test_closing_blocks_new_requests_and_discards_finished_round_without_requeue(self):
        host = Host([{'room_id': '1001'}])
        host.refresh_status()
        current = host._poller
        host._closing = host._refresh_queued = True
        current.finish()
        self.assertIsNone(host._poller)
        self.assertTrue(current.deleted)
        host.refresh_status(force=True)
        host.room_status.refresh_stats(Poller)
        self.assertEqual(len(Poller.instances), 1)
        host.sidebar.set_refreshing.assert_not_called()

    def test_destroyed_worker_reference_is_replaced(self):
        host = Host([{'room_id': '1001'}])
        deleted = Mock()
        deleted.isRunning.side_effect = RuntimeError('deleted fixture')
        host._poller = deleted
        host.refresh_status()
        self.assertIsNot(host._poller, deleted)
        self.assertTrue(host._poller.running)

    def test_empty_follow_refresh_restores_feedback_and_failure_is_visible(self):
        host = Host()
        host.room_status.refresh_follow()
        host.sidebar.refresh_frequent_order.assert_called_once_with()
        host.load_room_avatars.assert_called_once_with()
        host.refresh_status.assert_called_once_with(force=True)
        self.assertEqual([call.args[0] for call in host.sidebar.set_refreshing.call_args_list], [True, False])
        self.assertEqual(Poller.instances, [])
        host.room_status.status_failed('fixture')
        host.sidebar.count_label.setText.assert_called_once_with('状态刷新失败 · 点击重试')

    def test_unchanged_live_status_skips_sidebar_resort_and_sync_work(self):
        room = {'room_id': '1001', 'live': True, 'live_known': True}
        item = Mock(room=room, set_title=Mock(), set_uname=Mock())
        item.set_live = Mock(side_effect=lambda value: room.update(live=value))
        item_was_live = room['live']
        host = Host(rooms=[room])
        host.sidebar._items = [item]
        host.sidebar._folder_pending = set()
        host.sidebar.resort = Mock()
        host._sync_replay_scope = Mock()
        host.sync_danmaku = Mock()
        host._load_room_banners = Mock()
        host._startup_status_complete = True
        host.settings = {}
        host.hover_preview = SimpleNamespace(_room_id=lambda: '', cancel=Mock())
        host._status_avatar_loader = None
        host._aside_cover_loader = None
        host._start_avatar_loader = Mock()
        host.room_status.apply_status({'1001': {
            'live': item_was_live, 'title': '', 'uname': '', 'live_known': True,
        }})
        host.sidebar.resort.assert_not_called()
        host._sync_replay_scope.assert_not_called()
        host.sync_danmaku.assert_not_called()
        host.room_status.apply_status({'1001': {
            'live': False, 'title': '', 'uname': '', 'live_known': True,
        }})
        host.sidebar.resort.assert_called_once_with()
        host._sync_replay_scope.assert_called_once_with()
        host.sync_danmaku.assert_called_once_with()

    def test_wall_only_live_status_change_keeps_sync_work(self):
        sidebar_room = {'room_id': '1001', 'live': True, 'live_known': True}
        wall_room = {'room_id': '2002', 'live': True, 'live_known': True}
        item = Mock(room=sidebar_room, set_title=Mock(), set_uname=Mock())
        tile = Mock(room=wall_room, _status_text='直播中',
                    set_live=Mock(side_effect=lambda value, *_: wall_room.update(live=value)),
                    set_uname_title=Mock(), set_status=Mock(),
                    start_elapsed_timer=Mock())
        host = Host(rooms=[sidebar_room], tiles=[tile])
        host.sidebar._items = [item]
        host.sidebar._folder_pending = set()
        host.sidebar.resort = Mock()
        host._sync_replay_scope = Mock()
        host.sync_danmaku = Mock()
        host._offline_tile = Mock()
        host.players = {}
        host._resolvers = {}
        host._retry_timers = {}
        host.plugins.emit = Mock()
        host._load_room_banners = Mock()
        host._startup_status_complete = True
        host.settings = {}
        host.hover_preview = SimpleNamespace(_room_id=lambda: '', cancel=Mock())
        host._status_avatar_loader = None
        host._aside_cover_loader = None
        host._start_avatar_loader = Mock()
        host.room_status.apply_status({'2002': {
            'live': False, 'viewers': '', 'title': '', 'uname': '', 'live_known': True,
        }})
        host.sidebar.resort.assert_called_once_with()
        host._sync_replay_scope.assert_called_once_with()
        host.sync_danmaku.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
