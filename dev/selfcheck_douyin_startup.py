"""Verify Douyin startup input grace without changing post-start recovery."""
import os
import sys
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parents[1]
RUNTIME = next((path for path in (REPO, *REPO.parents)
                if (path / "libmpv-2.dll").is_file()), REPO)
os.environ["PATH"] = str(RUNTIME) + os.pathsep + os.environ.get("PATH", "")
sys.path.insert(0, str(REPO))

from ddm.player import TilePlayer  # noqa: E402


def fake_player(profile="douyin"):
    player = TilePlayer.__new__(TilePlayer)
    player.paused = False
    player._released = False
    player._media = "fixture"
    player._hls_proxy = None
    player.stream_profile = profile
    player.state = "connecting"
    player._buffer_limit = 6
    player._startup_buffering = True
    player._stall_ticks = 0
    player._last_time = None
    player._decoder_error = False
    player.source_failure = ""
    player._recover_decoder = Mock(return_value=False)
    values = {"time-pos": None, "eof-reached": False, "idle-active": False,
              "paused-for-cache": False, "vo-configured": True}
    player._prop = lambda name, default=None: values.get(name, default)
    player._set_state = Mock()
    return player, values


def main():
    player, values = fake_player()
    for _ in range(TilePlayer.DOUYIN_STARTUP_BUFFER_TICKS - 1):
        player._check()
    assert player._stall_ticks == TilePlayer.DOUYIN_STARTUP_BUFFER_TICKS - 1
    assert all(call.args != ("error",) for call in player._set_state.call_args_list)
    player._check()
    assert player._set_state.call_args.args == ("error",)

    player, values = fake_player()
    values["time-pos"] = 1.0
    player._check()
    assert not player._startup_buffering
    player._set_state.reset_mock()
    values["time-pos"] = None
    for _ in range(player._buffer_limit - 1):
        player._check()
    assert all(call.args != ("error",) for call in player._set_state.call_args_list)
    player._check()
    assert player._set_state.call_args.args == ("error",)

    player, values = fake_player(profile="huya")
    for _ in range(player._buffer_limit - 1):
        player._check()
    assert all(call.args != ("error",) for call in player._set_state.call_args_list)
    player._check()
    assert player._set_state.call_args.args == ("error",)
    print("PASS: Douyin startup grace; post-start and other-platform recovery unchanged")


if __name__ == "__main__":
    main()
