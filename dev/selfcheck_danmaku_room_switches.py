"""Real drop/button regression: per-room switches, swaps, duplicate tiles and restore."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
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
from ddm.widgets import ROOM_MIME, Tile
from dev.selfcheck_video_danmaku import Client, Snapshot

APP = QApplication.instance() or QApplication([])


class RoomSwitchTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("ddm.app.DanmakuClient", Client))
        self.stack.enter_context(patch("ddm.app.SuperChatSnapshot", Snapshot))
        for method in ("start_tile", "refresh_status", "refresh_stats"):
            self.stack.enter_context(patch.object(MainWindow, method))
        rooms = [dict(room_id=str(rid), uname=str(rid), live=True) for rid in (1001, 1002, 1003)]
        self.window = MainWindow(rooms, [dict(room) for room in rooms[:2]], layout_id="1x2",
                                 state={"plugins_enabled": []})
        self.addCleanup(self.window.close)
        self.window.resize(1200, 760)
        self.window.show()
        APP.processEvents()
        self.first, self.second = self.window.wall.tiles
        for tile in self.window.wall.tiles:
            tile.set_video_active(True)

    def drop(self, tile, rid):
        mime = QMimeData()
        mime.setData(ROOM_MIME, rid.encode())
        event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        tile.dropEvent(event)
        self.assertTrue(event.isAccepted())

    def test_new_drop_does_not_inherit_enabled_switch(self):
        self.first.danmaku_button.click()
        self.second.danmaku_button.click()
        old = self.window._danmaku_clients["1001"]
        other = self.window._danmaku_clients["1002"]
        self.drop(self.first, "1003")
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.assertNotIn("1003", self.window._danmaku_clients)
        self.assertTrue(old.stopped)
        self.assertIs(self.window._danmaku_clients["1002"], other)
        self.assertFalse(other.stopped)
        old.message.emit({"text": "queued old room message"})
        self.assertFalse(self.first.video_danmaku.comments)

    def test_clear_then_refill_defaults_off(self):
        self.first.danmaku_button.click()
        self.window._clear_tile_room(self.first)
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.drop(self.first, "1003")
        self.assertFalse(self.first.danmaku_button.isChecked())
        self.assertFalse(self.window._danmaku_clients)

    def test_sidebar_drop_of_existing_room_preserves_switch_during_fallback_swap(self):
        self.second.danmaku_button.click()
        with patch.object(self.window, "_hot_swap", return_value=False):
            self.drop(self.first, "1002")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertFalse(self.second.danmaku_button.isChecked())
        self.assertEqual(set(self.window._danmaku_clients), {"1002"})

    def test_drop_on_same_room_keeps_switch_and_connection(self):
        self.first.danmaku_button.click()
        client = self.window._danmaku_clients["1001"]
        self.drop(self.first, "1001")
        self.assertTrue(self.first.danmaku_button.isChecked())
        self.assertIs(self.window._danmaku_clients["1001"], client)
        self.assertFalse(client.stopped)

    def test_switch_does_not_leak_into_sidebar_or_duplicate(self):
        shared = dict(room_id="1001", live=True)
        first, duplicate = Tile(shared), Tile(shared)
        try:
            first.danmaku_button.click()
            self.assertTrue(first.room.get("video_danmaku_enabled"))
            self.assertNotIn("video_danmaku_enabled", shared)
            self.assertFalse(duplicate.danmaku_button.isChecked())
        finally:
            first.close()
            duplicate.close()

    def test_swap_and_restart_preserve_room_switches(self):
        self.second.danmaku_button.click()
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


if __name__ == "__main__":
    unittest.main()
