"""Synthetic live EOF: drain buffered frames, then recover without 60-second backoff."""
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from ddm.player import TilePlayer
from ddm.app import MainWindow
from ddm import app as app_module

ended = threading.Event()
ended.set()
props = {"time-pos": 2, "vo-configured": True}
player = SimpleNamespace(paused=False, _released=False, _media="fixture", state="playing",
    _hls_proxy=SimpleNamespace(refresh_required=threading.Event(),live_ended=ended),
    _recover_decoder=lambda:False, _prop=lambda key, default=None:props.get(key,default),
    _last_time=1, _stall_ticks=0, _buffer_limit=6, _set_state=Mock())
TilePlayer._check(player)
player._set_state.assert_called_once_with("playing")
player._set_state.reset_mock()
TilePlayer._check(player)
player._set_state.assert_called_once_with("error")

class Tile:
    room={"room_id":"huya:fixture"}
    def set_status(self, text):self.status=text

tile=Tile()
window=SimpleNamespace(_resolvers={},_retry_timers={},_retry_count={tile:9},
    players={tile:SimpleNamespace(source_failure="LIVE_EOF")},_retry_now=Mock())
timer=Mock()
with patch.object(app_module,"QTimer",return_value=timer):
    MainWindow._schedule_retry(window,tile)
    timer.start.assert_called_with(5000)
    assert "5 秒后重连" in tile.status
window._retry_timers.clear()
window.players[tile].source_failure="HTTP_403"
with patch.object(app_module,"QTimer",return_value=timer):
    MainWindow._schedule_retry(window,tile)
    timer.start.assert_called_with(60000)
print("PASS: buffered frames preserved, EOF triggers error, live EOF retry bounded to 5s, HTTP backoff preserved")
