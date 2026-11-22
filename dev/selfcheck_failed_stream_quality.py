"""Failed plugin playback must leave a usable quality menu; synthetic data only."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from ddm.bili import StreamResolver
from ddm.auto_quality import AUTO_QUALITY
from ddm.capture_control import CaptureControl
from ddm.fullscreen_control import FullscreenControl
from ddm.player import TilePlayer
from ddm.stream_playback import StreamPlayback
from ddm.widgets import Tile

app = QApplication.instance() or QApplication([])
for menu in ([{"qn": 1014100, "desc": "2K HDR"}], RuntimeError("menu unavailable")):
    platform = Mock()
    platform.play_url.side_effect = RuntimeError("fixture HTTP 403")
    if isinstance(menu, Exception):
        platform.room_quality_options.side_effect = menu
    else:
        platform.room_quality_options.return_value = menu
    resolver = StreamResolver("huya:fixture", 1014100, platform=platform)
    errors = []
    resolver.failed.connect(lambda rid, reason: errors.append(reason))
    resolver.run()
    assert errors == ["fixture HTTP 403"], errors
    assert resolver.failure_quality_options[0]["qn"] == 10000
    tile = Tile({"room_id": "huya:fixture", "live": True, "quality": 1014100})
    tile.set_quality_options(resolver.failure_quality_options)
    assert ("最高可用", 10000) in tile._quality_choices()
    changed = []
    tile.qualityChanged.connect(lambda room, qn: changed.append(qn))
    tile.set_quality(10000)
    assert changed == [10000]
    assert "获取画质" not in tile.quality_button.text()
    tile.close()
platform = Mock()
resolver = StreamResolver("huya:fixture", platform=platform)
resolver.cancel()
resolver.run()
platform.room_quality_options.assert_not_called()
assert resolver.failure_quality_options == []

source_quality = [{"qn": 0, "desc": "源自适应"}]
platform = Mock()
platform.room_quality_options.return_value = source_quality
platform.play_url.return_value = ('https://example.invalid/live.m3u8', 0, 'm3u', {})
room_id = 'm3u:preset:cctv5plus'
tile = Tile({'room_id': room_id, 'live': True, 'quality': 250})
resolver = StreamResolver(room_id, tile.quality, platform=platform)
resolver.resolved.connect(lambda _rid, _url, _qn, _profile, options: tile.set_quality_options(options))
resolver.run()
assert tile.quality_button.text() == '源自适应', tile.quality_button.text()
assert not tile.quality_button.isEnabled() and not tile._quality_choices()
menu = tile.build_menu()
quality_action = next(action for action in menu.actions() if action.data() == 'quality')
assert quality_action.text() == '画质 · 源自适应' and not quality_action.isEnabled()
menu.deleteLater()
assert not FullscreenControl(SimpleNamespace(_capture_quality={})).upgrade_fullscreen_quality(tile)

player = TilePlayer(tile.video, tile)
player._media = 'fixture'
player.report_video_resolution = True
properties = {'time-pos': 1, 'vo-configured': True, 'video-params': {'w': 1920, 'h': 1080}}
player._prop = lambda name, default=None: properties.get(name, default)
player._recover_decoder = lambda: False
playback = StreamPlayback(SimpleNamespace(_tile_of_player=lambda _: tile, _closing=False, wall=SimpleNamespace()))
reported = []
player.videoResolutionChanged.connect(reported.append)
player.videoResolutionChanged.connect(lambda resolution: playback.on_video_resolution(player, resolution))
player._check()
assert tile.quality_button.text() == '1920×1080' and not tile.quality_button.isEnabled()
tile.quality_locked = True
CaptureControl(SimpleNamespace(_capture_quality={tile: (room_id, tile.quality)})).restore_capture_quality(tile)
assert not tile.quality_locked and not tile.quality_button.isEnabled()
properties['time-pos'] = 2
player._check()
assert reported == ['1920×1080']
properties.update({'time-pos': 3, 'video-params': {'w': 1280, 'h': 720}})
player._check()
assert reported == ['1920×1080', '1280×720'] and tile.quality_button.text() == '1280×720'

StreamPlayback._refreshing(tile, True)
assert tile.quality_button.text() == '源自适应' and '获取画质' not in tile.reload_button.toolTip()
StreamPlayback._refreshing(tile, False)
assert tile.quality_button.text() == '源自适应'

platform.play_url.side_effect = RuntimeError('fixture connection failure')
resolver = StreamResolver(room_id, tile.quality, platform=platform)
resolver.run()
assert resolver.failure_quality_options == source_quality
tile.set_quality_options(resolver.failure_quality_options)
assert not tile._quality_choices()
tile.quality = AUTO_QUALITY
assert tile._quality_text() == '源自适应'
tile.set_room({'room_id': '1001', 'live': True, 'quality': 250})
playback.on_video_resolution(player, '1920×1080')
assert tile.quality_button.isEnabled() and tile._quality_choices()
assert tile.quality_button.text() != '1920×1080'
tile.close()
print("PASS: selectable quality survives stream errors; source-controlled quality remains read-only")
