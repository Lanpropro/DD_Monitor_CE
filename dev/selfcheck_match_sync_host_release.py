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
# A protected recording may resolve again while the hidden wall is suspended.
# Its new player must be muted before play(), not on a later suppression tick.
host._closing = False
host.settings = {}
host.media_options = lambda: ()
host._emit_stream_resolved = Mock()
host._sync_replay_scope = Mock()
host.recorder.on_resolved = Mock()
recording = tiles[3]
recording.volume, recording.audio_channel, recording.muted = 80, 0, False
recording.quality = 10000
player = Mock()
host.players[recording] = player
host._match_sync_active = True
MainWindow._play_on(host, recording, "https://example.invalid/live", profile="web")
player.set_muted.assert_called_once_with(True)
player.play.assert_called_once()
host._match_sync_active = False
MainWindow._play_on(host, recording, "https://example.invalid/live", profile="web")
assert player.set_muted.call_args.args == (False,)
print("PASS: hidden playback released once, recording protected, room identity/paused state preserved, closing skips resume")
