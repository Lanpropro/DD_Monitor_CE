"""全屏声音插件的离线回归测试，无需 Qt、直播网络或 VLC。"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import plugins as api


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

    def test_exit_preserves_audio_and_forwards_layout_arguments(self):
        target = self.tiles[1]
        self.wall.set_fullscreen_tile(target)
        self.events.clear()
        self.wall.set_fullscreen_tile(None, stagger=True, first=target)
        self.assertEqual(self.events, [])
        self.assertEqual(self.wall.calls[-1], (None, True, target))
        self.assertEqual([t.muted for t in self.tiles], [True, False, True, True])

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
