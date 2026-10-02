"""离线验证：各平台原生画质参数、房间档位菜单、预览隔离和保存/换台。"""
import json
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, config, plugins  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from selfcheck_platform_preview import response  # noqa: E402


def page(room):
    state = {"state": {"roomStore": {"roomInfo": {"room": room}}, "streamStore": {}}}
    return '<script>self.__pace_f.push([1,' + json.dumps("a:" + json.dumps([state])) + '])</script>'


def main():
    app = QApplication([])
    manager = plugins.PluginManager(enabled=["huya_watch"])
    manager.load()
    module = sys.modules[type(manager.platforms["huya"]).__module__]
    session = module.Streamlink()
    huya = manager.platforms["huya"]
    data = {"vMultiStreamInfo": [{"iBitRate": rate, "sDisplayName": name} for rate, name in
             ((0, "蓝光20M"), (8000, "蓝光8M"), (2000, "超清"), (4000, "蓝光4M"))],
            "data": [{"gameStreamInfoList": [{"sHlsUrl": "https://cdn.test", "sStreamName": "live",
                       "sHlsUrlSuffix": "m3u8", "sHlsAntiCode": "fm=x&fs=y", "sCdnType": "AL"}]}]}
    with patch.object(module, "Streamlink", return_value=session), \
            patch.object(session.http, "get", return_value=response(
                text="var hyPlayerConfig = {stream:" + json.dumps(data) + "};</script>")), \
            patch.object(module.Huya, "_get_stream_params", return_value={}) as params:
        for quality, preview, rate in ((10000, False, 0), (1004000, False, 4000),
                                       (80, False, 0), (10000, True, 2000)):
            stream = huya._streams("huya:123", quality, preview=preview)[2]["al_source"]
            assert params.call_args.args[-1] == rate
            assert stream.ddm_quality == (10000 if rate == 0 else 1000000 + rate)
        assert [item["desc"] for item in huya.room_quality_options("huya:123")] == [
            "蓝光20M", "蓝光8M", "蓝光4M", "超清"]
    douyu = manager.platforms["douyu"]
    source = {"rtmp_url": "https://stream.test.edgesrv.com", "rtmp_live": "source.flv", "rate": 0,
              "cdnsWithName": [{"cdn": "hw-h5"}], "multirates": [
                  {"rate": 0, "bit": 12000, "name": "原画1080P60"},
                  {"rate": 2, "bit": 900, "name": "高清"},
                  {"rate": 4, "bit": 4000, "name": "蓝光4M"}]}
    def request(_parser, _raw, cdn="", *, rate=0):
        return dict(source, rtmp_url="https://cdn.test" if cdn else source["rtmp_url"],
                    rtmp_live=f"rate-{rate}.flv", rate=rate)
    with patch.object(douyu, "room_info", return_value=plugins.RoomInfo("douyu:123", live=True)), \
            patch.object(douyu, "_request_source", side_effect=request) as get:
        for quality, preview, rate in ((2000004, False, 4), (80, False, 0), (10000, True, 2)):
            stream = douyu._streams(session, "douyu:123", quality, preview=preview)["source"]
            assert stream.to_url().endswith(f"rate-{rate}.flv")
            assert get.call_args.kwargs["rate"] == rate and get.call_args.args[-1] == "hw-h5"
            assert stream.ddm_quality == (10000 if rate == 0 else 2000000 + rate)
    with patch.object(douyu, "room_info", return_value=plugins.RoomInfo("douyu:123", live=True)), \
            patch.object(douyu, "_request_source", return_value=dict(source,
                rtmp_url="https://cdn.test", rate=4)):
        assert douyu._streams(session, "douyu:123", 10000)["source"].ddm_quality == 2000004
    douyin = manager.platforms["douyin"]
    room = {"status": 2, "id_str": "internal", "stream_url": {
        "flv_pull_url": {key: f"https://cdn.test/{key}.flv" for key in ("SD2", "FULL_HD1", "SD1", "HD1")},
        "live_core_sdk_data": {"pull_data": {"options": {"qualities": [
            {"sdk_key": "ld", "name": "标清", "resolution": "540x960", "fps": 25},
            {"sdk_key": "sd", "name": "高清", "resolution": "720x1280", "fps": 30},
            {"sdk_key": "hd", "name": "超清", "resolution": "720x1280", "fps": 60},
            {"sdk_key": "uhd", "name": "蓝光", "resolution": "1080x1920", "fps": 60}]}}}}}
    with patch.object(session.http, "get", return_value=response(text=page(room))):
        assert douyin._streams(session, "douyin:123")["source"].to_url().endswith("FULL_HD1.flv")
        options = douyin.room_quality_options("douyin:123")
        assert [item["desc"] for item in options] == ["蓝光 · 1080x1920 · 60fps",
            "超清 · 720x1280 · 60fps", "高清 · 720x1280 · 30fps", "标清 · 540x960 · 25fps"]
        for option, key in zip(options, ("FULL_HD1", "HD1", "SD2", "SD1")):
            assert douyin._streams(session, "douyin:123", option["qn"])["source"].to_url().endswith(key + ".flv")
        assert douyin._streams(session, "douyin:123", 80)["source"].to_url().endswith("FULL_HD1.flv")
        assert douyin._streams(session, "douyin:123", preview=True)["source"].to_url().endswith("SD1.flv")
        room["stream_url"]["flv_pull_url"] = {"HD1": "https://cdn.test/HD1.flv"}
        with patch.object(session.http, "get", return_value=response(text=page(room))):
            assert douyin._streams(session, "douyin:123", options[-1]["qn"])["source"].ddm_quality == 10000
            assert len(douyin.room_quality_options("douyin:123")) == 1
    session.http.close()
    print("PASS: Huya ratio, Douyu rate/CDN, Douyin native keys/portrait sizes/fps, missing-tier fallback, preview separate")

    state = {"plugins_enabled": ["huya_watch"], "settings": {"auto_quality": True,
             "recording_enabled": False, "recording_replay_enabled": False}}
    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state=state, layout_id="corner")
    try:
        tile = window.wall.tiles[0]
        for kind in ("huya", "douyu", "douyin"):
            tile.set_room({"room_id": kind + ":123", "live": True, "quality": 250})
            assert not tile._quality_choices() and tile._quality_text() == "获取画质…"
            options = manager.platforms[kind].room_quality_options(kind + ":123")
            tile.set_quality_options(options)
            tile.set_actual_quality(options[-1]["qn"])
            assert tile._quality_text() == options[-1].get("label", options[-1]["desc"])
            tile.quality = options[-1]["qn"]
            tile.room["quality"] = tile.quality
            tile.quality_button.setToolTip("choice")
            assert not window.apply_quality_policy(restart=False)
            assert tile.quality == options[-1]["qn"]
            saved = window.current_state()
            _, wall = config.build_rooms(saved)
            assert wall[0]["quality"] == tile.quality
        window.show()
        window.resize(520, 1000)
        app.processEvents()
        assert window.sidebar.side == "top"
        for preview_tile in window.wall.tiles:
            preview_tile.set_room({"room_id": "douyin:123", "live": True, "quality": 10000})
            preview_tile.set_quality_options([{"qn": 10000, "desc": "蓝光 · 1080x1920 · 60fps", "label": "蓝光"}])
            preview_tile.set_actual_quality(10000)
            assert preview_tile._quality_text() == "蓝光"
            assert "1080x1920" in preview_tile.quality_button.toolTip()
            assert preview_tile._quality_choices() == [("蓝光 · 1080x1920 · 60fps", 10000)]
            if preview_tile.isVisible():
                assert preview_tile.quality_button.geometry().left() >= 0
            preview_tile.set_room(None)
            assert not preview_tile.quality_options and preview_tile.actual_quality == 0
        tile.set_room({"room_id": "123", "live": True, "quality": 250})
        assert not tile.quality_options and tile._quality_text() == "超清 720P"
        assert tile._quality_choices()
        assert window.apply_quality_policy(restart=False) and tile.quality == 10000
        tile.set_room({"room_id": "douyu:123", "live": True, "quality": 10000})
        window.players[tile] = Mock()
        window._play_on(tile, "https://cdn.test/live.flv", 2000004, "douyu",
                        manager.platforms["douyu"].room_quality_options("douyu:123"),
                        headers={"Referer": "https://www.douyu.com/"}, requested_quality=10000)
        assert tile.quality == tile.actual_quality == 2000004
        assert tile._quality_text() == "蓝光4M"
        assert tile.quality_button.toolTip() == "请求 原画1080P60，平台实际返回 蓝光4M"
        platform = manager.platforms["huya"]
        resolved = []
        resolver = bili.StreamResolver("huya:123", 80, platform=platform, preview=True)
        resolver.resolved.connect(lambda *args: resolved.append(args))
        with patch.object(platform, "preview_url", return_value=("https://cdn.test/low.flv", 1002000, "huya", {})) as get, \
                patch.object(platform, "play_url", side_effect=AssertionError("Wrong preview route")):
            resolver.run()
            get.assert_called_once_with("huya:123")
            assert resolved[0][2] == 1002000 and not resolved[0][-1]
    finally:
        window.close()
        app.processEvents()
    print("PASS: platform menus, no Bili placeholders, native ID persistence, cross-platform reset, Bili auto policy retained")


if __name__ == "__main__":
    main()
