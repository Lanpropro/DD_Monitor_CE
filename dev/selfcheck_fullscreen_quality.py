"""Offline regression for fullscreen quality; no Qt or network required."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.fullscreen_quality import FullscreenQuality


class Tile:
    def __init__(self, room_id="123", quality=250):
        self.room = {"room_id": room_id, "quality": quality, "live": True}
        self.quality = quality
        self.paused = False
        self.blocked = False

    def blockSignals(self, blocked):
        before, self.blocked = self.blocked, blocked
        return before

    def set_quality(self, quality):
        self.quality = quality


class Window(SimpleNamespace):
    pass


class QualityTest(unittest.TestCase):
    def setUp(self):
        self.tile = Tile()
        self.other = Tile("456", 400)
        self.restarts = []
        self.window = Window(
            wall=SimpleNamespace(tiles=[self.tile, self.other]), settings={},
            _fullscreen_tile=self.tile, _capture_quality={}, _closing=False,
            _save_timer=SimpleNamespace(start=lambda: None),
            start_tile=lambda tile: self.restarts.append((tile, tile.quality)))
        self.quality = FullscreenQuality(self.window)

    def exit_fullscreen(self):
        self.window._fullscreen_tile = None
        self.quality.sync()

    def test_enter_and_restore_only_current_tile(self):
        self.quality.sync()
        self.assertEqual((self.tile.quality, self.other.quality), (10000, 400))
        self.assertEqual(self.quality.original(self.tile), 250)
        self.exit_fullscreen()
        self.assertEqual(self.tile.room["quality"], 250)
        self.assertEqual(self.restarts, [(self.tile, 10000), (self.tile, 250)])

    def test_independent_from_audio_setting(self):
        self.window.settings["fullscreen_solo_audio"] = False
        self.quality.sync()
        self.assertEqual(self.tile.quality, 10000)

    def test_advertised_2k_original_instead_of_1080p_high_bitrate(self):
        self.tile.quality_options = [
            {"qn": 25000, "desc": "2K 原画"},
            {"qn": 10000, "desc": "1080P 高码率"},
            {"qn": 30000, "desc": "杜比"}]
        self.quality.sync()
        self.assertEqual(self.tile.quality, 25000)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 250)

    def test_missing_original_tier_uses_existing_resolver_fallback(self):
        self.tile.quality_options = [{"qn": 400, "desc": "蓝光"}]
        self.quality.sync()
        self.assertEqual(self.tile.quality, 10000)

    def test_recording_release_selects_advertised_original(self):
        self.tile.quality_options = [{"qn": 25000, "label": "原画"}]
        self.tile.quality = 10000
        self.window._capture_quality[self.tile] = ("123", 400)
        self.quality.sync()
        self.assertEqual(self.tile.quality, 10000)
        room_id, before = self.window._capture_quality.pop(self.tile)
        selected = self.quality.capture_released(self.tile, room_id, before)
        self.assertEqual(selected, 25000)
        self.quality.change(self.tile, selected)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 400)

    def test_disabled_does_not_change_quality(self):
        self.window.settings["fullscreen_original_quality"] = False
        self.quality.sync()
        self.exit_fullscreen()
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.tile.quality, 250)

    def test_toggle_while_fullscreen(self):
        self.quality.sync()
        self.window.settings["fullscreen_original_quality"] = False
        self.quality.sync()
        self.assertEqual(self.tile.quality, 250)
        self.window.settings["fullscreen_original_quality"] = True
        self.quality.sync()
        self.assertEqual(self.tile.quality, 10000)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 250)

    def test_repeat_sync_does_not_overwrite_or_restart(self):
        self.quality.sync()
        self.quality.sync()
        self.assertEqual(len(self.restarts), 1)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 250)

    def test_already_original_does_not_restart(self):
        self.tile.quality = 10000
        self.quality.sync()
        self.exit_fullscreen()
        self.assertEqual(self.restarts, [])

    def test_actual_quality_fallback_is_not_a_retry_loop(self):
        self.quality.sync()
        self.tile.actual_quality = 400
        self.quality.sync()
        self.assertEqual(len(self.restarts), 1)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 250)

    def test_manual_change_is_temporary(self):
        self.quality.sync()
        self.tile.quality = 80
        self.quality.sync()
        self.assertEqual(self.tile.quality, 80)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 250)

    def test_room_replacement_does_not_restore_stale_quality(self):
        self.quality.sync()
        self.tile.room = {"room_id": "789", "live": True}
        self.tile.quality = 400
        self.assertEqual(self.quality.original(self.tile), 400)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 400)

    def test_removed_tile_is_ignored(self):
        self.quality.sync()
        self.window.wall.tiles.remove(self.tile)
        self.exit_fullscreen()
        self.assertEqual(len(self.restarts), 1)
        self.assertFalse(self.quality.saved)

    def test_empty_and_other_platform_ids_are_not_bilibili(self):
        for room_id in ("", "twitch:test", "youtube:test", "１２３"):
            self.tile.room["room_id"] = room_id
            self.quality.sync()
        self.assertFalse(self.quality.saved)
        self.assertEqual(self.restarts, [])

    def test_paused_or_offline_does_not_start_playback(self):
        for paused, live in ((True, True), (False, False)):
            self.window._fullscreen_tile = self.tile
            self.tile.paused, self.tile.room["live"] = paused, live
            self.quality.sync()
            self.exit_fullscreen()
        self.assertEqual(self.restarts, [])

    def test_closing_preserves_saved_quality_without_restarting(self):
        self.quality.sync()
        self.window._closing = True
        self.assertEqual(self.quality.original(self.tile), 250)
        self.exit_fullscreen()
        self.assertEqual(len(self.restarts), 1)

    def test_recording_before_fullscreen_keeps_its_lock(self):
        self.tile.quality = 10000
        self.window._capture_quality[self.tile] = ("123", 400)
        self.quality.sync()
        self.exit_fullscreen()
        self.assertEqual(self.window._capture_quality[self.tile], ("123", 400))
        self.assertEqual(self.tile.quality, 10000)

    def test_recording_started_fullscreen_defers_restore_until_recording_ends(self):
        self.quality.sync()
        self.window._capture_quality[self.tile] = ("123", 10000)
        self.exit_fullscreen()
        self.assertEqual(self.window._capture_quality[self.tile], ("123", 250))
        self.assertEqual(self.tile.quality, 10000)
        self.assertFalse(self.quality.saved)

    def test_recording_stopped_fullscreen_keeps_original_until_exit(self):
        self.tile.quality = 10000
        self.window._capture_quality[self.tile] = ("123", 400)
        self.quality.sync()
        room_id, before = self.window._capture_quality.pop(self.tile)
        self.assertEqual(self.quality.capture_released(self.tile, room_id, before), 10000)
        self.assertEqual(self.quality.original(self.tile), 400)
        self.exit_fullscreen()
        self.assertEqual(self.tile.quality, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
