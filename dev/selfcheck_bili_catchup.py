"""Offline regression checks for Bilibili live playback catch-up."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from ddm.app import MainWindow
from ddm.bili import BILI_PROFILES
from ddm.pip_parallel import ParallelPictureInPicture
from ddm.player import TilePlayer
from ddm.plugins import PluginManager


def fake_core(commands):
    return SimpleNamespace(
        speed=1.0, time_pos=10.0,
        demuxer_cache_state={"cache-end": 14.0}, vo_configured=True,
        paused_for_cache=False, seeking=False, eof_reached=False, idle_active=False,
        command=lambda *args: commands.append(args), terminate=lambda: None,
    )


class BilibiliCatchupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = QWidget()
        self.player = TilePlayer(self.widget)
        self.commands = []
        self.core = fake_core(self.commands)
        self.player.player = self.core
        self.binding = patch.object(self.player, "bind")
        self.binding.start()

    def tearDown(self):
        self.player.release()
        self.binding.stop()
        self.widget.close()
        self.widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def play(self, profile="app", url="https://cdn.example.test/live.flv"):
        self.player.play(url, profile)
        self.player._check()

    def tick(self, buffered):
        self.core.demuxer_cache_state = {"cache-end": self.core.time_pos + buffered}
        timer = getattr(self.player, "_catchup_watch", None)
        if timer is not None:
            timer.timeout.emit()

    def catchup_timer_active(self):
        timer = getattr(self.player, "_catchup_watch", None)
        return timer is not None and timer.isActive()

    def test_live_bilibili_stream_catches_up_without_seeking_or_reloading(self):
        self.play()
        loop = QEventLoop()
        QTimer.singleShot(650, loop.quit)
        loop.exec()
        self.assertEqual(self.core.speed, 1.3)
        self.assertEqual([command for command in self.commands if command[0] != "stop"], [
            ("loadfile", "https://cdn.example.test/live.flv", "replace")
        ])

    def test_speed_tiers_follow_forward_buffer_and_return_to_realtime(self):
        self.play()
        for buffered, expected in (
            (4.0, 1.3), (3.5, 1.2), (2.6, 1.2), (2.5, 1.1),
            (1.6, 1.1), (1.5, 1.0), (0.1, 1.0), (0.0, 1.0),
        ):
            with self.subTest(buffered=buffered):
                self.tick(buffered)
                self.assertEqual(self.core.speed, expected)

    def test_every_bilibili_profile_can_catch_up(self):
        for profile in BILI_PROFILES:
            with self.subTest(profile=profile):
                self.play(profile)
                self.tick(4.0)
                self.assertEqual(self.core.speed, 1.3)

    def test_other_platforms_and_local_media_are_excluded(self):
        for profile in ("douyu", "douyin", "custom", "web-plugin"):
            with self.subTest(profile=profile):
                self.play(profile, "https://cdn.example.test/live.m3u8")
                self.core.speed = 0.9
                self.tick(8.0)
                self.assertEqual(self.core.speed, 0.9)
                self.assertFalse(self.catchup_timer_active())
        self.play("web", "sample.flv")
        self.core.speed = 0.9
        self.tick(8.0)
        self.assertEqual(self.core.speed, 0.9)

        self.player.silent = True
        self.play()
        self.tick(8.0)
        self.assertEqual(self.core.speed, 0.9)
        self.assertFalse(self.catchup_timer_active())

    def test_pause_restores_normal_speed_and_resume_rechecks_buffer(self):
        self.play()
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.3)
        self.player.set_paused(True)
        self.assertEqual(self.core.speed, 1.0)
        self.tick(8.0)
        self.assertTrue(self.core.pause)
        self.assertEqual(self.core.speed, 1.0)
        self.player.set_paused(False)
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.3)

    def test_buffer_wait_seek_and_end_restore_normal_speed(self):
        self.play()
        for flag in ("paused_for_cache", "seeking", "eof_reached", "idle_active"):
            with self.subTest(flag=flag):
                self.tick(4.0)
                self.assertEqual(self.core.speed, 1.3)
                setattr(self.core, flag, True)
                self.tick(4.0)
                self.assertEqual(self.core.speed, 1.0)
                setattr(self.core, flag, False)
        self.tick(4.0)
        self.core.vo_configured = False
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.0)

    def test_nonplaying_states_do_not_accelerate(self):
        self.play()
        for state in ("connecting", "frozen", "buffering", "error"):
            with self.subTest(state=state):
                self.player._set_state("playing")
                self.tick(4.0)
                self.assertEqual(self.core.speed, 1.3)
                self.player._set_state(state)
                self.tick(4.0)
                self.assertEqual(self.core.speed, 1.0)

    def test_invalid_or_discontinuous_timestamps_restore_normal_speed(self):
        self.play()
        for position, cache in (
            (None, {"cache-end": 20.0}),
            (10.0, {}),
            (10.0, None),
            (10.0, {"cache-end": None}),
            (10.0, {"cache-end": 8.0}),
            (float("nan"), {"cache-end": 20.0}),
            (10.0, {"cache-end": float("inf")}),
            ("invalid", {"cache-end": 20.0}),
            (True, {"cache-end": 20.0}),
            (10.0, []),
        ):
            with self.subTest(position=position, cache=cache):
                self.tick(4.0)
                self.assertEqual(self.core.speed, 1.3)
                self.core.time_pos = position
                self.core.demuxer_cache_state = cache
                timer = getattr(self.player, "_catchup_watch", None)
                if timer is not None:
                    timer.timeout.emit()
                self.assertEqual(self.core.speed, 1.0)
                self.core.time_pos = 10.0

    def test_failed_speed_write_is_retried_and_unchanged_speed_is_not_rewritten(self):
        self.play()
        original_set = self.player._set
        with patch.object(self.player, "_set", side_effect=RuntimeError("media switching")):
            self.tick(4.0)
        self.assertEqual(self.core.speed, 1.0)
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.3)
        with patch.object(self.player, "_set", wraps=original_set) as set_property:
            self.tick(4.0)
            self.assertEqual(set_property.call_count, 0)

    def test_disabling_retries_a_failed_normal_speed_write(self):
        self.play()
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.3)
        with patch.object(self.player, "_set", side_effect=RuntimeError("media switching")):
            self.player.set_live_catchup_enabled(False)
        self.assertTrue(self.catchup_timer_active())
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.0)
        self.assertFalse(self.catchup_timer_active())

    def test_stop_channel_switch_and_release_restore_speed_and_stop_timer(self):
        self.play()
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.3)
        self.player.stop()
        self.assertEqual(self.core.speed, 1.0)
        self.assertFalse(self.catchup_timer_active())

        self.play()
        self.tick(4.0)
        self.assertEqual(self.core.speed, 1.3)
        self.play("douyu")
        self.assertEqual(self.core.speed, 1.0)
        self.assertFalse(self.catchup_timer_active())

        self.play("app")
        self.tick(4.0)
        self.player.release()
        self.assertEqual(self.core.speed, 1.0)
        self.assertFalse(self.catchup_timer_active())


class BilibiliCatchupMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        room = {"room_id": "1001", "uname": "fixture", "live": True}
        with patch.object(PluginManager, "load"), patch.object(PluginManager, "catalog", return_value=[]), \
                patch("ddm.app.QTimer.singleShot"):
            self.window = MainWindow([room], [dict(room)], layout_id="1x1",
                state={"plugins_enabled": [], "settings": {"close_behavior": "exit"}})
        self.tile = self.window.wall.tiles[0]
        self.commands = []

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def catchup_action(self):
        menu = self.tile.build_menu()
        return next((action for action in menu.actions() if action.data() == "live_catchup"), None)

    def play(self):
        def bind(player):
            if player.player is None:
                player.player = fake_core(self.commands)

        with patch.object(TilePlayer, "bind", bind):
            self.window._play_on(self.tile, "https://cdn.example.test/live.flv", profile="app")
        player = self.window.players[self.tile]
        player._check()
        return player

    def test_menu_toggles_the_playing_stream_without_reloading(self):
        player = self.play()
        player._check_live_catchup()
        self.assertEqual(player.player.speed, 1.3)
        action = self.catchup_action()
        self.assertIsNotNone(action)
        self.assertTrue(action.isCheckable())
        self.assertTrue(action.isChecked())

        commands_before_toggle = list(self.commands)
        action.trigger()
        self.assertEqual(player.player.speed, 1.0)
        self.assertFalse(player._catchup_watch.isActive())
        action = self.catchup_action()
        self.assertFalse(action.isChecked())
        action.trigger()
        self.assertTrue(player._catchup_watch.isActive())
        player._check_live_catchup()
        self.assertEqual(player.player.speed, 1.3)
        self.assertEqual(self.commands, commands_before_toggle)

    def test_turning_off_before_playback_survives_reconnecting(self):
        action = self.catchup_action()
        self.assertIsNotNone(action)
        action.trigger()
        for _ in range(2):
            player = self.play()
            player._check_live_catchup()
            self.assertEqual(player.player.speed, 1.0)
            self.assertFalse(player._catchup_watch.isActive())
            self.assertFalse(self.catchup_action().isChecked())
            self.window._stop_tile(self.tile)

    def test_menu_item_is_exclusive_to_bilibili_rooms(self):
        self.assertIsNotNone(self.catchup_action())
        for room_id in ("douyu:1001", "youtube:channel", ""):
            with self.subTest(room_id=room_id):
                self.tile.set_room({"room_id": room_id})
                self.assertIsNone(self.catchup_action())

    def test_independent_picture_in_picture_menu_controls_its_own_stream(self):
        parallel = ParallelPictureInPicture(self.window, self.window)
        pip_window = SimpleNamespace(track_tiles=lambda tiles: None, forget_tile=lambda tile: None)
        wall_tile = self.tile
        self.tile, = parallel.update({"1001": wall_tile.room}, "1001", pip_window)
        try:
            player = self.play()
            player._check_live_catchup()
            self.assertEqual(player.player.speed, 1.3)
            self.catchup_action().trigger()
            self.assertEqual(player.player.speed, 1.0)
            self.assertFalse(self.catchup_action().isChecked())
            self.tile = wall_tile
            self.assertTrue(self.catchup_action().isChecked())
        finally:
            parallel.close(pip_window)


if __name__ == "__main__":
    unittest.main()
