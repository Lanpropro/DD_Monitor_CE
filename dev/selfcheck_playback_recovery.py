"""Offline contracts for recovery policy, QObject ownership and MainWindow integration."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from ddm.playback_recovery import PlaybackRecovery


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QObject()
        self.host._resolvers, self.host.players = {}, {}
        self.host._closing = False
        self.host.start_tile, self.host.refresh_status = Mock(), Mock()
        self.recovery = PlaybackRecovery(self.host)
        self.tile = Mock(room={'room_id': '1001', 'uname': 'fixture', 'live': True}, paused=False)
        self.output = patch('builtins.print')
        self.output.start()

    def tearDown(self):
        self.recovery.shutdown()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.output.stop()

    def test_backoff_and_success_reset(self):
        for delay in (5000, 10000, 20000, 40000, 60000, 60000):
            self.recovery.schedule_retry(self.tile)
            timer = self.recovery.retry_timers[self.tile]
            self.assertIs(timer.parent(), self.recovery)
            self.assertEqual(timer.interval(), delay)
            timer.timeout.emit()
        self.assertEqual(self.host.start_tile.call_count, 6)
        self.recovery.reset_retry_after_playing(self.tile)
        self.recovery.schedule_retry(self.tile)
        self.assertEqual(self.recovery.retry_timers[self.tile].interval(), 5000)

    def test_huya_eof_and_stable_playback_generation(self):
        self.tile.room['room_id'] = 'huya:fixture'
        player = SimpleNamespace(source_failure='LIVE_EOF', state='playing', state_generation=3)
        self.host.players[self.tile] = player
        self.recovery.retry_count[self.tile] = 8
        self.recovery.schedule_retry(self.tile)
        self.assertEqual(self.recovery.retry_timers[self.tile].interval(), 5000)
        self.recovery.cancel_retry(self.tile)
        player.source_failure = 'HTTP_403'
        self.recovery.schedule_retry(self.tile)
        self.assertEqual(self.recovery.retry_timers[self.tile].interval(), 60000)
        with patch('ddm.playback_recovery.QTimer.singleShot') as schedule:
            self.recovery.reset_retry_after_playing(self.tile)
        delay, context, callback = schedule.call_args.args
        self.assertEqual(delay, 15000)
        self.assertIs(context, self.recovery)
        player.state_generation += 1
        callback()
        self.assertIn(self.tile, self.recovery.retry_count)
        player.state_generation -= 1
        self.host._closing = True
        callback()
        self.assertIn(self.tile, self.recovery.retry_count)
        self.host._closing = False
        callback()
        self.assertNotIn(self.tile, self.recovery.retry_count)

    def test_frozen_refresh_then_one_pending_timer_and_activity_cancellation(self):
        self.recovery.picture_frozen(self.tile)
        self.host.start_tile.assert_called_once_with(self.tile)
        self.host.refresh_status.assert_called_once()
        self.recovery.picture_frozen(self.tile)
        timer = self.recovery.freeze_retry_timers[self.tile]
        self.recovery.picture_frozen(self.tile)
        self.assertIs(self.recovery.freeze_retry_timers[self.tile], timer)
        self.assertEqual(timer.interval(), 5000)
        timer.start(0)
        self.recovery.picture_activity(self.tile)
        self.app.processEvents()
        self.assertEqual(self.host.start_tile.call_count, 1)
        self.assertNotIn(self.tile, self.recovery.freeze_refreshed)
        self.assertFalse(self.recovery.freeze_retry_timers)
        self.tile.set_status.assert_called_with('')

    def test_queued_retry_does_not_restart_a_cleared_room(self):
        self.recovery.schedule_retry(self.tile)
        self.tile.room.clear()
        self.recovery.retry_timers[self.tile].timeout.emit()
        self.host.start_tile.assert_not_called()
        self.assertFalse(self.recovery.retry_timers)

    def test_paused_picture_does_not_schedule_or_refresh(self):
        self.tile.paused = True
        self.recovery.picture_frozen(self.tile)
        self.assertFalse(self.recovery.freeze_refreshed)
        self.assertFalse(self.recovery.freeze_retry_timers)
        self.host.start_tile.assert_not_called()

    def test_shutdown_cancels_both_timer_families(self):
        frozen = Mock(room={'room_id': '2001'}, paused=False)
        self.recovery.schedule_retry(self.tile)
        self.recovery.freeze_refreshed.add(frozen)
        self.recovery.picture_frozen(frozen)
        timers = [*self.recovery.retry_timers.values(), *self.recovery.freeze_retry_timers.values()]
        for timer in timers:
            timer.start(0)
        self.recovery.shutdown()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.host.start_tile.assert_not_called()
        self.assertTrue(all(not isValid(timer) for timer in timers))
        self.assertFalse(self.recovery.retry_count)
        self.assertFalse(self.recovery.freeze_refreshed)
        self.assertFalse(self.recovery.retry_timers)
        self.assertFalse(self.recovery.freeze_retry_timers)

    def test_main_window_compatibility_views_and_playing_event(self):
        from ddm.app import MainWindow
        from ddm.plugins import EVENT_TILE_PLAYING, PluginManager
        room = {'room_id': '1001', 'uname': 'fixture', 'live': True}
        with patch.object(PluginManager, 'load'), patch('ddm.app.QTimer.singleShot'):
            window = MainWindow([room], [dict(room)], layout_id='1x1',
                state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
        try:
            recovery = window.playback_recovery
            self.assertIs(recovery.parent(), window)
            for old, new in (('_retry_timers', 'retry_timers'), ('_retry_count', 'retry_count'),
                             ('_freeze_retry_timers', 'freeze_retry_timers'),
                             ('_freeze_refreshed', 'freeze_refreshed')):
                self.assertIs(getattr(window, old), getattr(recovery, new))
            tile = window.wall.tiles[0]
            window._schedule_retry(tile)
            timer = window._retry_timers[tile]
            player = Mock()
            window.players[tile] = player
            with patch.object(window.plugins, 'emit') as emit:
                window._on_player_state(tile, 'playing')
            self.assertFalse(window._retry_timers)
            self.assertFalse(window._retry_count)
            self.assertFalse(timer.isActive())
            player.reapply_audio_channel.assert_called_once()
            emit.assert_called_once_with(EVENT_TILE_PLAYING, tile=tile, room=dict(tile.room))
            window._schedule_retry(tile)
            window.close()
            self.assertFalse(window._retry_timers)
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
