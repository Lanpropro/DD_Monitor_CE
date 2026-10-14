"""Check suspension ownership, recording protection and resume without VLC."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DDM_NO_SAVE", "1")
from ddm.app import MainWindow


class Tile:
    def __init__(self, key, paused=False):
        self.room = {"room_id": key, "live": True}
        self.paused = paused
        self.visible = True

    def isVisible(self):
        return self.visible


tiles = [Tile(str(i), i == 1) for i in range(5)]
host = SimpleNamespace(players={t: object() for t in tiles}, _resolvers={}, _retry_timers={},
                       _pending_capture={tiles[4]: object()}, recorder=SimpleNamespace(sessions={tiles[3]: object()}),
                       _closing=False, start_tile=Mock(), _stop_tile=Mock())
host._match_sync_holds = lambda tile: MainWindow._match_sync_holds(host, tile)
MainWindow.set_match_sync_playback(host, True)
assert host._stop_tile.call_count == 3
assert all(call.args[0] not in tiles[3:] for call in host._stop_tile.call_args_list)
MainWindow.set_match_sync_playback(host, True)
assert host._stop_tile.call_count == 3
assert host._match_sync_holds(tiles[0]) and not host._match_sync_holds(tiles[3])
tiles[2].room["room_id"] = "changed"
MainWindow.set_match_sync_playback(host, False)
assert {c.args[0] for c in host.start_tile.call_args_list} == set(tiles[:2])
assert host._match_sync_resume_pause == {tiles[1]: "1"}
MainWindow.set_match_sync_playback(host, False)
assert host.start_tile.call_count == 2
host._closing = True
MainWindow.set_match_sync_playback(host, True)
MainWindow.set_match_sync_playback(host, False)
assert host.start_tile.call_count == 2
print("PASS: hidden playback released once, recording protected, room identity/paused state preserved, closing skips resume")
