"""Check suspension ownership, recording protection and resume without VLC."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DDM_NO_SAVE", "1")
from ddm.app import MainWindow
from ddm.stream_playback import StreamPlayback
from ddm.codec_control import CodecControl


class Tile:
    def __init__(self, key, paused=False, muted=False):
        self.room = {"room_id": key, "live": True}
        self.paused = paused
        self.muted = muted
        self.quality_options = []
        self.visible = True

    def isVisible(self):
        return self.visible

    def property(self, _name):
        return None


tiles = [Tile(str(i), paused=i == 1, muted=i == 4) for i in range(5)]
players = {tile: Mock() for tile in tiles}
host = SimpleNamespace(players=players.copy(), _resolvers={}, _retry_timers={},
                       _pending_capture={tiles[4]: object()}, recorder=SimpleNamespace(sessions={tiles[3]: object()}),
                       _closing=False, start_tile=Mock())
host._stop_tile = Mock(side_effect=host.players.pop)
host.stream_playback = StreamPlayback(host)
host.codec_control = CodecControl(host)
host._match_sync_holds = lambda tile: MainWindow._match_sync_holds(host, tile)
MainWindow.set_match_sync_playback(host, True)
assert host._stop_tile.call_count == 3
assert all(call.args[0] not in tiles[3:] for call in host._stop_tile.call_args_list)
for tile in tiles[3:]:
    players[tile].set_muted.assert_called_once_with(True)
MainWindow.set_match_sync_playback(host, True)
assert host._stop_tile.call_count == 3
assert host._match_sync_holds(tiles[0]) and not host._match_sync_holds(tiles[3])
tiles[2].room["room_id"] = "changed"
MainWindow.set_match_sync_playback(host, False)
assert {c.args[0] for c in host.start_tile.call_args_list} == set(tiles[:2])
assert host._match_sync_resume_pause == {tiles[1]: "1"}
for tile in tiles[3:]:
    assert players[tile].set_muted.call_args.args == (tile.muted,)
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
host.media_options = lambda tile=None: ()
host.plugins = SimpleNamespace(platform_for=lambda room_id: None)
host._is_bili_tile = lambda tile: MainWindow._is_bili_tile(host, tile)
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
host.wall = SimpleNamespace(tiles=[recording])
host.stream_playback.audit_audio()
player.sync_audio.assert_called_once_with(80, True, 0)
host._match_sync_active = False
MainWindow._play_on(host, recording, "https://example.invalid/live", profile="web")
assert player.set_muted.call_args.args == (False,)
host.stream_playback.audit_audio()
assert player.sync_audio.call_args.args == (80, False, 0)
print("PASS: hidden playback released once, recording protected, room identity/paused state preserved, closing skips resume")
