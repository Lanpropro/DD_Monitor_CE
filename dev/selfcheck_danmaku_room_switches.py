"""Real drop/button regression: per-room switches, swaps, duplicate tiles and restore."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
from ddm import config
from ddm.app import MainWindow
from ddm.plugins import Platform, PluginManager
from ddm.widgets import ROOM_MIME
from dev.selfcheck_video_danmaku import Client, Snapshot, wait_comment_raster

APP = QApplication.instance() or QApplication([])


class OfflinePlatform(Platform):
    kind = "test"

    def matches(self, room_id):
        return room_id.startswith("test:")

    def danmaku_client(self, room_id, parent=None):
        return Client(room_id, parent)


class RoomSwitchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("ddm.app.DanmakuClient", Client))
        self.stack.enter_context(patch("ddm.app.SuperChatSnapshot", Snapshot))
        self.stack.enter_context(patch.object(PluginManager, "load", lambda manager:
                                              manager.register_platform("fixture", OfflinePlatform())))
        for method in ("start_tile", "refresh_status", "refresh_stats", "refresh_account",
                       "load_cached_covers", "load_cached_avatars", "load_room_avatars", "_check_startup_update"):
            self.stack.enter_context(patch.object(MainWindow, method))
        rooms = [dict(room_id=rid, uname=rid, live=True) for rid in ("1001", "1002", "1003", "test:1001")]
        self.window = MainWindow(rooms, [dict(room) for room in rooms[:2]], layout_id="1x2",
                                 state={"plugins_enabled": ["fixture"], "settings": {"close_behavior": "exit"}})
        self.addCleanup(self.window.close)
        self.window.resize(1200, 760)
        self.window.show()
        APP.processEvents()
        self.first, self.second = self.window.wall.tiles
        for tile in self.window.wall.tiles:
            tile.set_video_active(True)
        self.window.sync_danmaku()

    def drop(self, tile, rid):
        mime = QMimeData()
        mime.setData(ROOM_MIME, rid.encode())
        event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        tile.dropEvent(event)
        self.assertTrue(event.isAccepted())

    def test_new_room_subscribes_and_ignores_late_messages_from_old_room(self):
        self.assertTrue(self.first.danmaku_button.isChecked())
        old = self.window._danmaku_clients["1001"]
        other = self.window._danmaku_clients["1002"]
        self.drop(self.first, "1003")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertIn("1003", self.window._danmaku_clients)
        self.assertTrue(old.stopped)
        self.assertIs(self.window._danmaku_clients["1002"], other)
        self.assertFalse(other.stopped)
        self.first.set_video_active(True)
        old.message.emit({"text": "queued old room message"})
        wait_comment_raster(APP, self.first.video_danmaku)
        self.assertFalse(self.first.video_danmaku.comments)

    def test_disabled_room_is_remembered_after_clear_and_refill(self):
        self.first.danmaku_button.click()
        self.window._clear_tile_room(self.first)
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.drop(self.first, "1003")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.drop(self.first, "1001")
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.assertEqual(set(self.window._danmaku_clients), {"1002"})
        self.first.danmaku_button.click()
        self.drop(self.first, "1003")
        self.drop(self.first, "1001")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertNotIn("", self.window.current_state()["room_danmaku_switches"])

    def test_sidebar_drop_of_existing_room_preserves_switch_during_fallback_swap(self):
        self.first.danmaku_button.click()
        with patch.object(self.window, "_hot_swap", return_value=False):
            self.drop(self.first, "1002")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertFalse(self.second.danmaku_button.isChecked())
        self.assertEqual(set(self.window._danmaku_clients), {"1002"})

    def test_drop_on_same_room_keeps_switch_and_connection(self):
        client = self.window._danmaku_clients["1001"]
        self.drop(self.first, "1001")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertIs(self.window._danmaku_clients["1001"], client)
        self.assertFalse(client.stopped)

    def test_duplicate_tiles_share_room_preference_and_connection(self):
        self.second.set_room(dict(self.first.room))
        self.window.sync_danmaku()
        self.second.danmaku_button.click()
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.assertFalse(self.window._danmaku_clients)
        self.first.danmaku_button.click()
        self.assertTrue(self.second.danmaku_button.isChecked())
        self.assertEqual(set(self.window._danmaku_clients), {"1001"})
        self.assertNotIn("video_danmaku_enabled", self.window.sidebar.rooms()[0])

    def test_swap_and_restart_preserve_room_switches(self):
        self.first.danmaku_button.click()
        with patch.object(self.window, "_hot_swap", return_value=False):
            self.window._on_tile_swapped("1002", self.first)
        self.assertEqual(self.first.room["room_id"], "1002")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertFalse(self.second.danmaku_button.isChecked())
        self.assertEqual(set(self.window._danmaku_clients), {"1002"})
        with patch.dict(self.window.players, {self.first: Mock(), self.second: Mock()}):
            self.assertTrue(self.window._hot_swap(self.first, self.second))
        saved = self.window.current_state()
        _, restored = config.build_rooms(saved)
        self.assertEqual([r["video_danmaku_enabled"] for r in restored], [False, True])
        reopened = MainWindow([], restored, layout_id="1x2", state=saved)
        try:
            self.assertEqual([t.danmaku_button.isChecked() for t in reopened.wall.tiles], [False, True])
        finally:
            reopened.close()

    def test_off_wall_room_and_platform_with_same_number_survive_disk_reload(self):
        self.first.danmaku_button.click()
        self.drop(self.first, "test:1001")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertEqual(set(self.window._danmaku_clients), {"1002", "test:1001"})
        self.first.danmaku_button.click()
        self.drop(self.first, "1001")
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.first.danmaku_button.click()
        self.drop(self.first, "1003")

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config, "CONFIG_PATH", str(Path(directory) / "config.json")):
            with patch.dict(os.environ, DDM_NO_SAVE=""):
                self.window.close()
            saved = config.load()
        self.assertIs(saved["room_danmaku_switches"]["1001"], True)
        self.assertIs(saved["room_danmaku_switches"]["test:1001"], False)
        reopened = MainWindow(*config.build_rooms(saved), layout_id="1x2", state=saved)
        self.addCleanup(reopened.close)
        tile = reopened.wall.tiles[0]
        self.assertEqual(tile.room["room_id"], "1003")
        self.drop(tile, "test:1001")
        self.assertFalse(tile.danmaku_button.isChecked())
        self.drop(tile, "1001")
        self.assertTrue(tile.danmaku_button.isChecked())


class RoomSwitchMigrationTests(unittest.TestCase):
    def test_migration_keeps_explicit_legacy_values_and_defaults_missing_rooms_on(self):
        state = {"wall": [
            {"room_id": "1001", "video_danmaku_enabled": False},
            {"room_id": "1001", "video_danmaku_enabled": True},
            {"room_id": "1002", "video_danmaku_enabled": True},
            {"room_id": "1003"}, {"room_id": "", "video_danmaku_enabled": True}],
            "suspended_platform_rooms": {"test": {"wall": [
                {"index": 4, "slot": {"room_id": "test:1001", "video_danmaku_enabled": False}}]}}}
        migrated = config.room_danmaku_switches(state)
        self.assertEqual(migrated, {"1001": False, "1002": True, "test:1001": False})
        restored = config.sync_platform_rooms(state, {"test"})
        _, wall = config.build_rooms(restored)
        self.assertEqual([r["video_danmaku_enabled"] for r in wall], [False, False, True, True, False])
        state["room_danmaku_switches"] = {**migrated, "1001": True}
        _, wall = config.build_rooms(state)
        self.assertEqual([r["video_danmaku_enabled"] for r in wall], [True, True, True, True, False])


if __name__ == "__main__":
    unittest.main()
