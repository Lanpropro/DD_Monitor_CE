"""全屏声音插件的离线回归测试，无需 Qt、直播网络或 VLC。"""
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import plugins as api
import ddm


class FakeTile:
    def __init__(self, name, muted=False, volume=35, events=None):
        self.room = {"room_id": name, "muted": muted, "volume": volume}
        self.muted = muted
        self.volume = volume
        self.events = events if events is not None else []

    def set_muted(self, value):
        self.muted = value
        self.room["muted"] = value
        self.events.append((self.room["room_id"], "mute", value))

    def set_volume(self, value):
        self.volume = value
        self.room["volume"] = value
        self.events.append((self.room["room_id"], "volume", value))


class FakeWall:
    def __init__(self, tiles):
        self.tiles = tiles
        self.fullscreen_tile = None
        self.calls = []

    def set_fullscreen_tile(self, tile, *, stagger=False, first=None):
        self.fullscreen_tile = tile
        self.calls.append((tile, stagger, first))
        return "switched"


class FullscreenAudioTest(unittest.TestCase):
    def setUp(self):
        self.settings_page = SimpleNamespace(ITEMS=[("default_muted", "静音")])
        dialogs = SimpleNamespace(GeneralSettingsPage=self.settings_page)
        self.dialog_patch = patch.object(ddm, "dialogs", dialogs, create=True)
        self.dialog_patch.start()
        self.addCleanup(self.dialog_patch.stop)
        self.events = []
        self.tiles = [FakeTile(str(i), muted=(i == 1), events=self.events)
                      for i in range(4)]
        self.wall = FakeWall(self.tiles)
        self.window = SimpleNamespace(wall=self.wall, settings={})
        self.manager = api.PluginManager(
            window=self.window, plugins_dir=str(ROOT / "plugins_user"),
            enabled=["fullscreen_audio"])
        self.original = self.wall.set_fullscreen_tile
        self.manager.load()
        self.assertNotIn("fullscreen_audio", [name for name, _ in self.manager.skipped])
        self.assertEqual(len(self.manager.plugins), 1)

    def tearDown(self):
        self.manager.unload()

    def test_enter_mutes_every_other_tile_and_preserves_volume(self):
        target = self.tiles[1]
        self.assertEqual(self.wall.set_fullscreen_tile(target), "switched")
        self.assertEqual([t.muted for t in self.tiles], [True, False, True, True])
        self.assertEqual(target.volume, 35)
        self.assertEqual(self.events[-1], ("1", "mute", False))
        self.assertTrue(all(t.room["muted"] == t.muted for t in self.tiles))

    def test_exit_restores_audio_and_forwards_layout_arguments(self):
        target = self.tiles[1]
        self.wall.set_fullscreen_tile(target)
        self.events.clear()
        self.wall.set_fullscreen_tile(None, stagger=True, first=target)
        self.assertEqual(self.wall.calls[-1], (None, True, target))
        self.assertEqual([t.muted for t in self.tiles], [False, True, False, False])
        self.assertEqual([t.volume for t in self.tiles], [35] * 4)

    def test_disabled_setting_leaves_audio_untouched(self):
        self.window.settings["fullscreen_audio_focus"] = False
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.wall.set_fullscreen_tile(None)
        self.assertEqual(self.events, [])

    def test_general_setting_registered_with_default_and_removed_on_unload(self):
        from ddm import config
        self.assertEqual([key for key, _ in self.settings_page.ITEMS],
                         ["default_muted", "fullscreen_audio_focus"])
        self.assertTrue(config.DEFAULT_SETTINGS["fullscreen_audio_focus"])
        self.manager.unload()
        self.assertEqual(self.settings_page.ITEMS, [("default_muted", "静音")])

    def test_setting_survives_config_save_and_reload(self):
        from ddm import config
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(config, "CONFIG_PATH", str(Path(folder) / "config.json")), \
                patch.dict(os.environ):
            os.environ.pop("DDM_NO_SAVE", None)
            for enabled in (False, True):
                config.save({"version": config.STATE_VERSION,
                             "settings": {"fullscreen_audio_focus": enabled}})
                self.assertIs(config.load()["settings"]["fullscreen_audio_focus"], enabled)

    def test_restore_manual_volume_changes_and_original_zero(self):
        self.tiles[1].volume = 0
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.tiles[1].set_volume(80)
        self.tiles[2].set_volume(12)
        self.tiles[3].set_muted(False)
        self.wall.set_fullscreen_tile(None)
        self.assertEqual([t.volume for t in self.tiles], [35, 0, 35, 35])
        self.assertEqual([t.muted for t in self.tiles], [False, True, False, False])

    def test_disable_during_fullscreen_still_restores_on_exit(self):
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.window.settings["fullscreen_audio_focus"] = False
        self.wall.set_fullscreen_tile(None)
        self.assertEqual([t.muted for t in self.tiles], [False, True, False, False])
        self.events.clear()
        self.wall.set_fullscreen_tile(self.tiles[2])
        self.assertEqual(self.events, [])

    def test_switch_fullscreen_target_preserves_original_snapshot(self):
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.wall.set_fullscreen_tile(self.tiles[2])
        self.wall.set_fullscreen_tile(None)
        self.assertEqual([t.muted for t in self.tiles], [False, True, False, False])

    def test_removed_tiles_are_skipped_and_new_tiles_are_untouched(self):
        self.wall.set_fullscreen_tile(self.tiles[1])
        removed = self.tiles.pop()
        new = FakeTile("new", muted=False, volume=12)
        self.tiles.append(new)
        self.events.clear()
        self.wall.set_fullscreen_tile(None)
        self.assertFalse(new.muted)
        self.assertEqual(new.volume, 12)
        self.assertFalse(any(event[0] == removed.room["room_id"] for event in self.events))

    def test_unload_during_fullscreen_restores_before_save(self):
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.manager.unload()
        self.assertEqual([t.muted for t in self.tiles], [False, True, False, False])

    def test_reenter_other_tile_moves_audio_focus(self):
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.wall.set_fullscreen_tile(None)
        self.wall.set_fullscreen_tile(self.tiles[2])
        self.assertEqual([t.muted for t in self.tiles], [True, True, False, True])

    def test_zero_volume_uses_default(self):
        self.window.settings["default_volume"] = 63
        self.tiles[1].volume = 0
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.assertEqual(self.tiles[1].volume, 63)
        self.assertFalse(self.tiles[1].muted)

    def test_zero_or_invalid_default_still_produces_audible_volume(self):
        for value, expected in [(0, 50), (-5, 50), (None, 50),
                                ("bad", 50), ("42", 42), (200, 100)]:
            with self.subTest(value=value):
                self.wall.set_fullscreen_tile(None)
                self.window.settings["default_volume"] = value
                self.tiles[1].volume = 0
                self.wall.set_fullscreen_tile(self.tiles[1])
                self.assertEqual(self.tiles[1].volume, expected)

    def test_empty_or_unknown_tile_does_not_change_audio(self):
        self.wall.set_fullscreen_tile(FakeTile("outside"))
        self.tiles[1].room = {}
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.assertEqual(self.events, [])

    def test_relayout_same_fullscreen_tile_respects_manual_mute(self):
        target = self.tiles[1]
        self.wall.set_fullscreen_tile(target)
        target.set_muted(True)
        self.events.clear()
        self.wall.set_fullscreen_tile(target)
        self.assertTrue(target.muted)
        self.assertEqual(self.events, [])

    def test_audio_failure_does_not_break_fullscreen(self):
        def broken(value):
            raise RuntimeError("simulated audio failure")
        self.tiles[0].set_muted = broken
        self.assertEqual(self.wall.set_fullscreen_tile(self.tiles[1]), "switched")
        self.assertIs(self.wall.fullscreen_tile, self.tiles[1])

    def test_unload_restores_original_entry(self):
        self.manager.unload()
        self.assertEqual(self.wall.set_fullscreen_tile, self.original)
        self.wall.set_fullscreen_tile(self.tiles[1])
        self.assertEqual(self.events, [])

    def test_unload_does_not_overwrite_a_later_hook(self):
        later_hook = lambda tile: None
        self.wall.set_fullscreen_tile = later_hook
        self.manager.unload()
        self.assertIs(self.wall.set_fullscreen_tile, later_hook)


if __name__ == "__main__":
    unittest.main(verbosity=2)
