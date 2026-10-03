"""离线验收自动画质策略、实际 Qt 取流接线、手动/预览隔离和保存恢复。"""
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import config  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.auto_quality import AUTO_QUALITY, AutoQuality  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402
from selfcheck_live_platforms import settle  # noqa: E402

OPTIONS = [{"qn": AUTO_QUALITY, "desc": "自动", "label": "自动"}] + [
    {"qn": qn, "desc": label, "label": label, "bandwidth": rate} for qn, label, rate in
    ((10000, "1080p60", 6000000), (5000001, "720p", 3000000), (5000002, "360p", 900000))]


def check_policy():
    auto = AutoQuality("youtube:test", 0)
    assert auto.choose(OPTIONS, 5000002, (12000000, 6), "playing", 1) is None
    assert auto.choose(OPTIONS, 5000002, (12000000, 6), "playing", 29) is None
    assert auto.choose(OPTIONS, 5000002, (12000000, 6), "playing", 30) == 10000
    assert auto.choose(OPTIONS, 10000, (1000000, 3), "playing", 40) is None  # 冷却
    assert auto.choose(OPTIONS, 10000, (3500000, 3), "playing", 46) == 5000002  # 余量不足，直接降到承载档
    assert auto.choose(OPTIONS, 5000002, (6000000, 1), "playing", 47) is None
    assert auto.choose(OPTIONS, 5000002, (12000000, 1), "playing", 77) is None  # 样本不足
    assert auto.choose(OPTIONS, 5000002, (6000000, 6), "playing", 78) == 5000001  # 能流畅承载的最高档
    assert auto.choose(OPTIONS, 5000001, (7000000, 6), "playing", 79) is None
    assert auto.choose(OPTIONS, 5000001, (7000000, 6), "playing", 110) is None  # 禁止边缘带宽来回切
    assert auto.choose(OPTIONS, 5000001, (9500000, 6), "playing", 111) == 10000
    assert auto.choose(OPTIONS, 10000, (0, 0), "buffering", 130) is None
    assert auto.choose(OPTIONS, 10000, (0, 0), "buffering", 136) == 5000001  # 网络中断无完整样本也能降
    assert auto.choose(OPTIONS, 5000002, (0, 0), "buffering", 160) is None  # 最低档不重复刷新
    assert auto.choose(OPTIONS, 123, (12000000, 6), "playing", 200) is None
    assert auto.choose([{"qn": 10000}], 10000, (12000000, 6), "playing", 230) is None
    startup = AutoQuality("twitch:test", 0)
    assert startup.choose(OPTIONS, 10000, (0, 0), "buffering", 3) is None
    assert startup.choose(OPTIONS, 10000, (0, 0), "buffering", 16) is None
    assert startup.choose(OPTIONS, 10000, (0, 0), "buffering", 25) == 5000001
    print("PASS: startup, throughput headroom, highest sustainable tier, fast downshift, buffering and hysteresis")


def check_window(app):
    state = {"plugins_enabled": ["global_live"], "settings": {"recording_enabled": False,
        "recording_replay_enabled": False, "preview_on_hover": False, "danmaku_enabled": False}}
    with patch("ddm.app.QTimer.singleShot"), patch("ddm.app.MainWindow.sync_danmaku"), \
            patch("ddm.app.MainWindow.refresh_status"), patch("ddm.app.MainWindow.refresh_stats"), \
            patch.object(TilePlayer, "play"):
        window = MainWindow([], [], state=state, layout_id="dm_pair")
        try:
            for kind in ("youtube", "twitch"):
                platform = window.plugins.platforms[kind]
                rid = kind + (":AbCd_123-45" if kind == "youtube" else ":test")
                tile = window.wall.tiles[0]
                window._stop_tile(tile)
                tile.set_room({"room_id": rid, "platform": kind, "live": True, "uname": kind})
                assert tile.quality == AUTO_QUALITY
                def source(_rid, qn):
                    return "https://cdn.test/live.m3u8", 5000002 if qn == AUTO_QUALITY else qn, kind, {}
                with patch.object(platform, "play_url", side_effect=source) as get, \
                        patch.object(platform, "room_quality_options", return_value=OPTIONS):
                    window.start_tile(tile)
                    settle(app, lambda: tile not in window._resolvers and tile in window.players)
                    player = window.players[tile]
                    assert tile.quality == AUTO_QUALITY and tile.actual_quality == 5000002
                    assert get.call_args.args[-1] == AUTO_QUALITY
                    assert tile._quality_text() == "自动 · 360p"
                    assert tile._quality_choices()[0][1] == AUTO_QUALITY
                    assert "自动画质" in tile.quality_button.toolTip()
                    controller = player.auto_quality
                    player._relay = Mock(_hls_proxy=Mock(network_speed=Mock(return_value=(12000000, 6))))
                    player.state = "playing"
                    controller.last_switch = 0
                    controller.stable_since = 0
                    with patch("ddm.player.time.monotonic", return_value=40):
                        player._check_auto_quality()
                    settle(app, lambda: tile not in window._resolvers and tile.actual_quality == 10000)
                    assert get.call_args.args[-1] == 10000 and tile.quality == AUTO_QUALITY
                    assert player.auto_quality is controller  # 切档冷却沿播放器保留
                    assert tile._quality_text() == "自动 · 1080p60"
                    saved = window.current_state()
                    _, slots = config.build_rooms(saved)
                    assert slots[0]["quality"] == AUTO_QUALITY
                    calls = get.call_count
                    tile.set_paused(True)
                    player.autoQualityRequested.emit(5000002)
                    assert get.call_count == calls
                    tile.set_paused(False)
                    tile.set_quality(5000001)
                    settle(app, lambda: tile not in window._resolvers and tile.actual_quality == 5000001)
                    assert player.auto_quality is None and tile.quality == 5000001
                    calls = get.call_count
                    player.autoQualityRequested.emit(10000)
                    player._check_auto_quality()
                    assert get.call_count == calls
                    window.apply_quality_policy(restart=False)
                    assert tile.quality == 5000001
                    # 自动请求回来前用户改手动，旧回调不能改实际档或画质意图。
                    window._play_on(tile, "https://cdn.test/late.m3u8", 10000, kind, OPTIONS,
                                    room_id=rid, requested_quality=AUTO_QUALITY)
                    assert tile.quality == 5000001 and tile.actual_quality == 5000001
                    # 播放中切自动/锁定当前档只更新策略，不能中断媒体或重取最低档。
                    player._media = Mock()
                    player.state = "playing"
                    media, relay = player._media, player._relay
                    calls = get.call_count
                    tile.set_quality(AUTO_QUALITY)
                    assert tile.actual_quality == 5000001 and player.auto_quality is not None
                    assert get.call_count == calls and tile not in window._resolvers
                    assert player._media is media and player._relay is relay
                    assert tile._quality_text() == "自动 · 720p"
                    tile.set_paused(True)
                    player.set_paused(True)
                    tile.set_quality(5000001)
                    assert player.auto_quality is None and tile.paused and player.paused
                    assert get.call_count == calls and player._media is media
                    tile.set_quality(AUTO_QUALITY)
                    assert player.auto_quality is not None and tile.paused
                    tile.set_paused(False)
                    player.set_paused(False)
                    # 未完成的其他手选请求要作废，并保留线程直到 finished。
                    pending = Mock()
                    window._resolvers[tile] = pending
                    tile.set_quality(AUTO_QUALITY)
                    pending.cancel.assert_called_once()
                    assert tile not in window._resolvers
                    assert get.call_count == calls
                    # 断流时选择自动仍需重新取流恢复。
                    player.state = "error"
                    tile.set_quality(AUTO_QUALITY)
                    settle(app, lambda: tile not in window._resolvers and tile.actual_quality == 5000002)
                    player.auto_quality.room_id = "youtube:other"
                    calls = get.call_count
                    player.autoQualityRequested.emit(10000)
                    assert get.call_count == calls
                    player.stop()
                    assert player.auto_quality is None
                    preview = TilePlayer(tile.video, silent=True)
                    try:
                        preview.configure_auto_quality(rid, OPTIONS)
                        assert preview.auto_quality is None
                    finally:
                        preview.release()
            window.plugins.enabled = set()
            window._sync_platform_rooms()
            hidden = window.current_state()
            assert hidden["suspended_platform_rooms"]["twitch"]["wall"][0]["slot"]["quality"] == AUTO_QUALITY
            hidden["plugins_enabled"] = ["global_live"]
            rooms, slots = config.build_rooms(hidden)
            restored = MainWindow(rooms, slots, state=hidden, layout_id="dm_pair")
            try:
                assert restored.wall.tiles[0].quality == AUTO_QUALITY
            finally:
                restored.close()
        finally:
            window.close()
    print("PASS: real Qt resolver/signal, automatic intent/current tier, cooldown, stale requests, manual/pause/preview isolation and persistence")


if __name__ == "__main__":
    check_policy()
    app = QApplication([])
    check_window(app)
