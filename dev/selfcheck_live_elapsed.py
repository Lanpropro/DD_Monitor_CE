"""Live-duration metadata delivery with isolated Qt windows and no live requests."""
import time
import unittest
from unittest.mock import patch

import selfcheck_main_notices as fixtures


class LiveElapsedTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.MainNoticesTests.setUpClass.__func__)
    setUp = fixtures.MainNoticesTests.setUp
    window = fixtures.MainNoticesTests.window
    close_window = fixtures.MainNoticesTests.close_window

    def live_window(self):
        window = self.window([dict(room_id='7001', uname='Fixture', live=True)], offscreen=True)
        tile = window.wall.tiles[0]
        tile.set_controls_visible(True)
        return window, tile

    def status(self, window, *, live=True, start=0, known=True):
        window._on_status_updated({'7001': dict(live=live, title='Fixture', uname='Fixture',
            viewers='', face='', cover_url='', live_start_ts=start, live_known=known)})

    def test_late_start_time_starts_visible_clock_without_another_playing_event(self):
        window, tile = self.live_window()
        window._on_player_state(tile, 'playing')
        self.assertFalse(tile._elapsed_timer.isActive())
        start = int(time.time()) - 600
        self.status(window, start=start)
        self.assertEqual(tile.room['live_start_ts'], start)
        self.assertTrue(tile._elapsed_timer.isActive())
        self.assertFalse(tile.time_badge.isHidden())
        window.start_tile.assert_not_called()
        self.status(window)  # Partial follow-up data must not erase a valid clock.
        self.assertEqual(tile.room['live_start_ts'], start)
        self.assertTrue(tile._elapsed_timer.isActive())
        tile.set_controls_visible(False)
        self.assertTrue(tile.time_badge.isHidden())
        self.assertTrue(tile._elapsed_timer.isActive())

    def test_valid_start_time_does_not_wait_for_the_first_playing_callback(self):
        window, tile = self.live_window()
        self.assertFalse(tile._player_active)
        self.status(window, start=int(time.time()) - 600)
        self.assertTrue(tile._elapsed_timer.isActive())
        self.assertFalse(tile.time_badge.isHidden())

    def test_sidebar_start_time_is_reused_when_the_room_is_put_on_wall(self):
        window, tile = self.live_window()
        tile.set_room(None)
        start = int(time.time()) - 600
        self.status(window, start=start)
        item = window.sidebar._items[0]
        self.assertEqual(item.room.get('live_start_ts'), start)
        window.add_to_wall(dict(item.room))
        self.assertIs(window._tile_of('7001'), tile)
        self.assertEqual(tile.room['live_start_ts'], start)
        self.assertTrue(tile._elapsed_timer.isActive())
        tile.set_controls_visible(True)
        self.assertFalse(tile.time_badge.isHidden())

    def test_offline_clears_previous_session_time_from_tile_and_sidebar(self):
        window, tile = self.live_window()
        self.status(window, start=int(time.time()) - 600)
        self.status(window, live=False)
        self.assertFalse(tile._elapsed_timer.isActive())
        self.assertFalse(tile.room.get('live_start_ts'))
        self.assertFalse(window.sidebar._items[0].room.get('live_start_ts'))
        self.assertTrue(tile.time_badge.isHidden())
        self.status(window)
        self.assertFalse(tile._elapsed_timer.isActive())
        self.assertFalse(tile.room.get('live_start_ts'))
        self.status(window, start=int(time.time()) - 30)
        self.assertTrue(tile._elapsed_timer.isActive())

    def test_missing_start_time_keeps_the_badge_hidden(self):
        window, tile = self.live_window()
        self.status(window)
        self.assertFalse(tile._elapsed_timer.isActive())
        self.assertTrue(tile.time_badge.isHidden())

    def test_confirmed_end_is_displayed_saved_and_cleared_on_new_live(self):
        from ddm import config
        window, tile = self.live_window()
        item = window.sidebar._items[0]
        end = int(time.time()) - 60
        with patch('ddm.room_status.time.time', return_value=end):
            self.status(window, live=False, known=False)
            self.assertNotIn('last_live_end_ts', tile.room)
            self.status(window, live=False)
        self.assertEqual(tile.room['last_live_end_ts'], end)
        self.assertEqual(item.room['last_live_end_ts'], end)
        stamp = time.strftime('%Y-%m-%d %H:%M', time.localtime(end))
        self.assertIn(f'约于 {stamp} 下播', tile.cover.text())
        self.status(window, live=False)
        self.assertEqual(tile.room['last_live_end_ts'], end)
        saved = window.current_state()
        self.assertEqual(saved['last_live_ends'], {'7001': end})
        followed, wall = config.build_rooms(saved)
        self.assertEqual(followed[0]['last_live_end_ts'], end)
        self.assertEqual(wall[0]['last_live_end_ts'], end)
        tile.set_room(wall[0])
        self.assertNotIn(stamp, tile.cover.text())
        self.status(window, live=False)
        self.assertIn(stamp, tile.cover.text())
        self.status(window)
        self.assertNotIn('last_live_end_ts', tile.room)
        self.assertEqual(window.current_state()['last_live_ends'], {})

    def test_first_offline_observation_does_not_invent_end_time(self):
        window = self.window([dict(room_id='7001', live=False, live_known=False)], offscreen=True)
        self.status(window, live=False)
        self.assertEqual(window.wall.tiles[0].cover.text(), '未开播')
        self.assertEqual(window.current_state()['last_live_ends'], {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
