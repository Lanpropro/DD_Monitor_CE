"""离线自检：B站取流按设置的编码要流（H.264 直连 FLV，HEVC/AV1 走 HLS 转封装）。

全部打桩，不联网。
"""
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from ddm import bili, player as player_module  # noqa: E402

AVC_ACCEPT = [10000, 400, 250]
HEVC_ACCEPT = [10000, 400, 250]
#: AV1 实测就是比 H.264 少一档（720P 取不到），档位必须跟编码走。
AV1_ACCEPT = [10000, 400]


def response(data):
    return Mock(json=Mock(return_value=data))


def _stream(protocol: str, codec: str, accepted: list, base_url: str, host: str) -> dict:
    return {"protocol_name": protocol, "format": [{"codec": [{
        "codec_name": codec, "accept_qn": list(accepted), "current_qn": 10000,
        "base_url": base_url, "url_info": [{"host": host, "extra": ""}],
    }]}]}


def app_payload(avc=AVC_ACCEPT, hevc=HEVC_ACCEPT, av1=AV1_ACCEPT) -> dict:
    """H.264 给 FLV + HLS 两条通道，HEVC / AV1 只有 HLS（和真实接口一致）。"""
    streams = [_stream("http_stream", "avc", avc, "/avc.flv", "https://cdn-avc")]
    if hevc:
        streams.append(_stream("http_hls", "hevc", hevc, "/hevc.m3u8", "https://cdn-hevc"))
    if av1:
        streams.append(_stream("http_hls", "av1", av1, "/av1.m3u8", "https://cdn-av1"))
    return {"code": 0, "data": {"playurl_info": {"playurl": {
        "g_qn_desc": [{"qn": 10000, "desc": "原画"}, {"qn": 400, "desc": "蓝光"},
                      {"qn": 250, "desc": "超清"}],
        "stream": streams,
    }}}}


def check_codec_param() -> None:
    """接口的 codec 参数：0/1/2，默认必须是 avc（老调用点行为不变）。"""
    for codec, param in (("avc", 0), ("hevc", 1), ("av1", 2)):
        with patch.object(bili.requests, "get", return_value=response(app_payload())) as get:
            bili._app_play_info("1001", 10000, codec)
        assert get.call_args.kwargs["params"]["codec"] == param, codec
        assert "getRoomPlayInfo" in get.call_args.args[0]
    with patch.object(bili.requests, "get", return_value=response(app_payload())) as get:
        bili._app_play_info("1001", 10000)
    assert get.call_args.kwargs["params"]["codec"] == 0, "默认必须是 H.264"


def check_channel_name() -> None:
    """通道名：H.264 是 app（直连），HEVC / AV1 带 -hls 后缀（要转封装）。"""
    assert bili.relay_required("app") is False
    assert bili.relay_required("web") is False
    for codec in ("hevc", "av1"):
        profile = bili._app_profile(codec)
        assert profile == f"app-hls-{codec}", profile
        assert bili.HLS_SUFFIX in profile and bili.relay_required(profile)
    assert bili._app_profile("avc") == "app"
    # 平台插件的通道名由插件作者定，可能凑巧带 hls —— 不归 B 站这条规则管。
    for profile in ("huya-hls", "my-hls-1", "douyu", "huya"):
        assert bili.relay_required(profile) is False, profile
    for profile in ("app-plugin-hls-hevc", "web-custom-av1", "app-hls-unknown"):
        assert not bili.relay_required(profile) and bili.codec_from_profile(profile) == ""


def check_codec_from_profile() -> None:
    """通道名 -> 编码：录制和播放器都靠它挑容器。"""
    assert bili.codec_from_profile("app-hls-hevc") == "hevc"
    assert bili.codec_from_profile("app-hls-av1") == "av1"
    assert bili.codec_from_profile("app") == "avc"
    assert bili.codec_from_profile("web") == "avc"
    assert bili.codec_from_profile("web-hls") == "", "没写编码的 HLS 通道不猜"
    assert bili.codec_from_profile("huya") == "", "平台插件的通道不是 B 站流"
    for profile in ("huya-av1", "douyu-hevc", "hevc", "av1", "huya-hls-av1"):
        assert bili.codec_from_profile(profile) == "", profile
    assert bili.codec_from_profile("") == ""


def check_app_urls() -> None:
    """取地址：avc 挑 FLV，hevc / av1 挑 HLS，绝不串味。"""
    payload = response(app_payload())
    with patch.object(bili.requests, "get", return_value=payload):
        assert bili._app_play_urls("1001", 10000, "avc") == (["https://cdn-avc/avc.flv"], 10000)
        assert bili._app_play_urls("1001", 10000, "hevc") == (["https://cdn-hevc/hevc.m3u8"], 10000)
        assert bili._app_play_urls("1001", 10000, "av1") == (["https://cdn-av1/av1.m3u8"], 10000)
    mismatched = _stream("http_stream", "hevc", HEVC_ACCEPT, "/hevc.flv", "https://cdn-hevc")
    assert bili._app_codec_entry(mismatched, "avc") is None
    legacy = _stream("http_stream", "avc", AVC_ACCEPT, "/avc.flv", "https://cdn-avc")
    del legacy["format"][0]["codec"][0]["codec_name"]
    entry = bili._app_codec_entry(legacy, "avc")
    assert entry is not None and entry["base_url"] == "/avc.flv"
    # 底层严格选编码，由 play_url 负责回退并标记实际通道。
    with patch.object(bili.requests, "get", return_value=response(app_payload(hevc=[], av1=[]))):
        try:
            bili._app_play_urls("1001", 10000, "hevc")
        except bili.CodecUnavailable as error:
            assert "hevc" in str(error)
        else:
            raise AssertionError("没有 HEVC 通道时必须报错")


def check_play_url() -> None:
    """支持所选编码时保留原通道和请求头。"""
    payload = response(app_payload())
    no_web = patch.object(bili, "_web_play_urls",
                          side_effect=AssertionError("HEVC/AV1 不得退回 web 接口"))
    with patch.object(bili.requests, "get", return_value=payload), \
            patch.object(bili, "_fetchable", return_value=True), no_web:
        hevc = bili.play_url("1001", 10000, codec="hevc")
        av1 = bili.play_url("1001", 10000, codec="av1")
        avc = bili.play_url("1001", 10000, codec="avc")
    assert hevc[0] == "http://cdn-hevc/hevc.m3u8" and hevc[2] == "app-hls-hevc"
    assert av1[0] == "http://cdn-av1/av1.m3u8" and av1[2] == "app-hls-av1"
    assert bili.relay_required(hevc[2]) and bili.relay_required(av1[2])
    assert avc[0] == "http://cdn-avc/avc.flv" and avc[2] == "app"
    assert not bili.relay_required(avc[2])

    # 默认值（不传 codec）就是老行为：H.264 的 FLV 通道。
    with patch.object(bili.requests, "get", return_value=payload), \
            patch.object(bili, "_fetchable", return_value=True) as fetch:
        default = bili.play_url("1001", 10000)
        assert fetch.called
    assert default[0] == "http://cdn-avc/avc.flv" and default[2] == "app"
    assert default[3] == bili.STREAM_APP, "FLV 通道的请求头不能变"

def check_codec_fallback() -> None:
    for codec in ("hevc", "av1"):
        with patch.object(bili.requests, "get",
                          return_value=response(app_payload(hevc=[], av1=[]))) as get, \
                patch.object(bili, "_fetchable", return_value=True) as fetch:
            result = bili.play_url("1001", 10000, codec=codec)
        assert result == ("http://cdn-avc/avc.flv", 10000, "app", bili.STREAM_APP)
        assert [call.kwargs["params"]["codec"] for call in get.call_args_list] == [
            bili.CODEC_PARAM[codec], 0]
        assert fetch.call_args.args[1] == bili.STREAM_APP
        assert not bili.relay_required(result[2])

    # 同时测试空流响应，以及另一个支持 AV1 的房间不受回退影响。
    with patch.object(bili.requests, "get", side_effect=[
            response({"code": 0, "data": {}}), response(app_payload()),
            response(app_payload())]) as get, \
            patch.object(bili, "_fetchable", return_value=True):
        missing = bili.play_url("1001", 10000, codec="av1")
        supported = bili.play_url("1002", 10000, codec="av1")
    assert missing[2] == "app" and supported[2] == "app-hls-av1"
    assert [call.kwargs["params"]["codec"] for call in get.call_args_list] == [2, 0, 2]

    # H.264 的 app 接口也不可用时，仍可走原有 web 备用通道与对应请求头。
    with patch.object(bili, "_app_play_info", return_value={}), \
            patch.object(bili, "_web_play_urls", return_value=(
                ["https://web-a/live.flv", "https://web-b/live.flv"], 250)) as web, \
            patch.object(bili, "_fetchable", return_value=True) as fetch:
        result = bili.play_url("1001", 400, codec="av1", source_offset=1)
    assert result == ("http://web-b/live.flv", 250, "web", bili.STREAM_WEB)
    assert web.call_args.args == ("1001", 400, "avc")
    assert fetch.call_args.args[1] == bili.STREAM_WEB

    for failure in (bili.requests.Timeout("timeout"),
                    response({"code": -400, "message": "bad request"})):
        with patch.object(bili.requests, "get", side_effect=[failure]) as get, \
                patch.object(bili, "_fetchable") as fetch:
            try:
                bili.play_url("1001", 10000, codec="av1")
            except RuntimeError as error:
                assert "AV1" in str(error)
            else:
                raise AssertionError("网络或 API 错误应保留原重连处理")
        assert get.call_count == 1
        fetch.assert_not_called()

    with patch.object(bili.requests, "get", return_value=response(app_payload())) as get, \
            patch.object(bili, "_fetchable", return_value=False):
        try:
            bili.play_url("1001", 10000, codec="av1")
        except RuntimeError as error:
            assert "CDN" in str(error)
        else:
            raise AssertionError("CDN 错误不能改变编码")
    assert get.call_count == 1

    with patch.object(bili, "_app_play_info", return_value={}) as app, \
            patch.object(bili, "_web_play_urls", autospec=True,
                         side_effect=RuntimeError("offline")) as web:
        try:
            bili.play_url("1001", 10000, codec="av1")
        except RuntimeError:
            pass
        else:
            raise AssertionError("所有通道都不可用时应报错收尾")
    assert app.call_count == 2 and web.call_count == 1, "回退必须有限，不循环请求"

    cancelled = Mock(side_effect=[False, True])
    with patch.object(bili, "_app_play_info", return_value={}) as app:
        try:
            bili.play_url("1001", 10000, codec="av1", cancelled=cancelled)
        except bili.Cancelled:
            pass
        else:
            raise AssertionError("取消后不能启动回退请求")
    assert app.call_count == 1


def check_quality_options() -> None:
    """档位必须跟同一个编码走，且 HEVC/AV1 不许拿 web 接口（只有 H.264）的档位。"""
    payload = response(app_payload())
    with patch.object(bili.requests, "get", return_value=payload) as get:
        avc = bili.room_quality_options("1001", "avc")
        hevc = bili.room_quality_options("1001", "hevc")
        av1 = bili.room_quality_options("1001", "av1")
    assert [item["qn"] for item in avc] == [10000, 400, 250]
    assert [item["qn"] for item in hevc] == HEVC_ACCEPT
    assert [item["qn"] for item in av1] == AV1_ACCEPT, "AV1 只能列出自己的档位"
    assert 250 not in [item["qn"] for item in av1], "AV1 没有 720P"
    assert get.call_count == 3
    assert all("getRoomPlayInfo" in call.args[0] for call in get.call_args_list), \
        "HEVC/AV1 不能回退到 web 老接口"
    assert [call.kwargs["params"]["codec"] for call in get.call_args_list] == [0, 1, 2]

    # 房间完全没有 AV1 时返回空表（不回退），默认仍是 H.264 的老行为。
    with patch.object(bili.requests, "get",
                      return_value=response(app_payload(av1=[]))) as get:
        assert bili.room_quality_options("1001", "av1") == []
    assert get.call_count == 1 and "getRoomPlayInfo" in get.call_args.args[0]
    with patch.object(bili.requests, "get", return_value=response(app_payload())) as get:
        assert [item["qn"] for item in bili.room_quality_options("1001")] == [10000, 400, 250]
    assert get.call_args.kwargs["params"]["codec"] == 0


def check_resolver() -> None:
    """取流线程要把 codec 透传给取流和档位两处。"""
    for codec, profile in (("avc", "app"), ("hevc", "app-hls-hevc"), ("av1", "app-hls-av1")):
        resolved = []
        resolver = bili.StreamResolver("1001", 10000, codec=codec)
        resolver.resolved.connect(lambda *args: resolved.append(args))
        with patch.object(bili, "play_url", return_value=(
                "http://cdn/x", 10000, profile, bili.STREAM_APP)) as play, \
                patch.object(bili, "room_quality_options", return_value=[]) as options:
            resolver.run()
        assert play.call_args.kwargs["codec"] == codec
        assert options.call_args.args[1] == codec
        assert resolved[0][3] == profile, "通道名要带出去（信号参数个数不变）"
        assert len(resolved[0]) == 5
    assert bili.StreamResolver("1001").codec == "avc", "默认必须是 avc"
    assert bili.StreamResolver("1001", codec="garbage").codec == "avc"

    resolver = bili.StreamResolver("1001", 10000, codec="av1")
    resolved = []
    failed = []
    resolver.resolved.connect(lambda *args: resolved.append(args))
    resolver.failed.connect(lambda *args: failed.append(args))
    with patch.object(bili.requests, "get",
                      return_value=response(app_payload(hevc=[], av1=[]))), \
            patch.object(bili, "_fetchable", return_value=True):
        resolver.run()
    assert not failed and len(resolved) == 1, "缺少 AV1 必须直接成功，不能触发失败重连"
    assert resolved[0][3] == "app" and resolver.headers == bili.STREAM_APP
    assert [option["qn"] for option in resolved[0][4]] == AVC_ACCEPT, "档位必须跟实际 H.264 走"
    assert resolver.codec == "av1", "回退不能改写用户的首选编码"

    preview = bili.StreamResolver("1001", 10000, codec="av1", preview=True)
    with patch.object(bili.requests, "get",
                      return_value=response(app_payload(hevc=[], av1=[]))), \
            patch.object(bili, "_fetchable", return_value=True), \
            patch.object(bili, "room_quality_options") as options:
        preview.run()
    options.assert_not_called()


def check_player_container(application) -> None:
    """播放器：B 站 HLS 通道走转封装，容器跟编码走；H.264 直连不转封装。"""
    from ddm import stream_relay
    fake_instance = Mock()
    video = QWidget()
    with patch.object(player_module.PlayerPool, "instance", return_value=fake_instance):
        tile_player = player_module.TilePlayer(video)
    assert tile_player.stream_codec == ""
    try:
        with patch.object(stream_relay, "StreamRelay") as relay:
            relay.return_value.url = "http://127.0.0.1:1/relay.mkv"
            tile_player.play("http://cdn/hevc.m3u8", "app-hls-hevc", {"User-Agent": "x"})
            assert relay.call_count == 1
            assert relay.call_args.kwargs["container"] == "matroska", "HEVC 要装 matroska"
            assert tile_player._relay is relay.return_value
            assert tile_player._buffer_limit == 6, "转封装沿用平台那一档缓冲"
            assert tile_player._picture_limit == 8
        with patch.object(stream_relay, "StreamRelay") as relay:
            relay.return_value.url = "http://127.0.0.1:1/relay.mkv"
            tile_player.play("http://cdn/av1.m3u8", "app-hls-av1", {})
            assert relay.call_args.kwargs["container"] == "matroska", "AV1 要装 matroska"
        with patch.object(stream_relay, "StreamRelay") as relay:
            tile_player.play("http://cdn/live.flv", "app", bili.STREAM_APP)
            relay.assert_not_called()
            assert tile_player._relay is None, "H.264 的 FLV 仍然直连"
            assert tile_player._picture_limit == player_module.TilePlayer.FROZEN_TICKS
        # 带编码后缀的通道名不能把默认请求头查找弄崩（实际头由 _play_on 传进来）。
        for profile in ("app-hls-hevc", "app-hls-av1", "web-hls", "app", "web", "huya"):
            headers = tile_player.PROFILE_HEADERS.get(profile, tile_player.PROFILE_HEADERS["web"])
            assert headers, profile
            with patch.object(stream_relay, "StreamRelay") as relay:
                relay.return_value.url = "http://127.0.0.1:1/relay"
                tile_player.play("http://cdn/x", profile)
        # 平台插件的通道名没有编码，容器保持原来的 FLV。
        with patch.object(stream_relay, "StreamRelay") as relay:
            relay.return_value.url = "http://127.0.0.1:1/relay.flv"
            tile_player.play("http://cdn/huya.m3u8", "huya", {})
            assert relay.call_args.kwargs["container"] == "flv"
            assert "av1" not in relay.call_args.kwargs
    finally:
        tile_player.release()
        video.close()
        application.processEvents()


def check_relay_without_proxy() -> None:
    """B 站这条转封装没有 HLS 转发层（_hls_proxy 是 None）。

    ``_check()`` / ``_check_auto_quality()`` 每次 tick 都会碰它，必须是「安静地
    什么也不做」，不能抛异常。
    """
    from types import SimpleNamespace
    states = []
    relay = SimpleNamespace(_hls_proxy=None, needs_restart=lambda: False)
    player = SimpleNamespace(paused=False, _relay=relay, auto_quality=Mock(),
                             _auto_options=[], _frozen_ticks=0, state="playing",
                             actual_quality=10000, autoQualityRequested=Mock(),
                             _set_state=states.append)
    # _check_auto_quality 先看 auto_quality / paused / _relay，再看 _hls_proxy
    assert player_module.TilePlayer._check_auto_quality(player) is None
    assert states == [] and not player.autoQualityRequested.called
    # _check 里 needs_restart() 是 False，走到后面的画面判断也不该崩。
    player._ensure_audio_settings = lambda: None
    player._recover_decoder = lambda _state: False
    player.player = Mock()
    player.player.get_state.return_value = player_module.vlc.State.Opening
    player.player.video_get_size.return_value = (0, 0)
    player.player.get_time.return_value = 0
    player._last_time = None
    player._picture_signature = lambda: None
    player._stall_ticks = 0
    player._buffer_limit = 6
    player_module.TilePlayer._check(player)
    assert player._stall_ticks == 1, "没有 HLS 转发层也要照常走缓冲检测"


def check_app_wiring(application) -> None:
    """主窗口接线：设置里的编码进 StreamResolver，取回后写回格子和播放器。"""
    from ddm.app import MainWindow
    from ddm import app as app_module
    from PySide6.QtCore import QThread, Signal

    seen = []

    class Resolver(QThread):
        resolved = Signal(str, str, int, str, list)
        failed = Signal(str, str)

        def __init__(self, room_id, quality, parent=None, **kwargs):
            super().__init__(parent)
            seen.append(kwargs)
            self.headers = {}

        def is_cancelled(self):
            return True              # 不真的启动线程

        def cancel(self):
            pass

        def start(self):
            pass

    room = {"room_id": "1001", "uname": "测试", "title": "", "live": True, "quality": 10000}
    state = {"plugins_enabled": [], "settings": {"bili_codec": "av1",
             "recording_enabled": False, "recording_replay_enabled": False,
             "preview_on_hover": False, "danmaku_enabled": False, "auto_quality": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(app_module, "StreamResolver", Resolver):
        window = MainWindow([dict(room)], [dict(room)], layout_id="1x1", state=state)
        window.show()
        application.processEvents()
        try:
            tile = window.wall.tiles[0]
            window.start_tile(tile)
            assert seen and seen[-1]["codec"] == "av1", "内置取流要带上设置里的编码"
            # 平台插件那条路不能传编码（plugins.py 的接口不接受这个参数）。
            plugin = Mock(kind="huya")
            with patch.object(window.plugins, "platform_for", return_value=plugin):
                window.start_tile(tile)
            assert seen[-1]["codec"] == "", "平台插件那条路不传 B 站编码"

            # 取流回来：格子和播放器都要记下这一路的编码（录像靠它挑容器）。
            with patch.object(player_module.TilePlayer, "play"), \
                    patch.object(MainWindow, "_sync_replay_scope"), \
                    patch.object(window.recorder, "on_resolved"):
                window._play_on(tile, "http://127.0.0.1:9/hevc.m3u8", 10000, "app-hls-hevc",
                                [], headers=bili.STREAM_APP, room_id="1001",
                                requested_quality=10000)
            assert tile.stream_codec == "hevc" and window.players[tile].stream_codec == "hevc"
            assert tile.stream_profile == "app-hls-hevc"
            assert window.current_state() is not None
        finally:
            window.close()
            application.processEvents()

    # 设置里改了编码要重新取流（改的是流的编码，不重取不生效）。
    from ddm.dialogs import SettingsDialog as RealSettingsDialog
    restarted = []
    state = dict(state)
    state["settings"] = {"bili_codec": "avc"}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([dict(room)], [dict(room)], layout_id="1x1", state=state)
        try:
            window.plugins.enabled = set()
            with patch.object(window, "start_tile", side_effect=restarted.append), \
                    patch.object(app_module, "SettingsDialog") as dialog:
                # 假对话框的 Accepted 要跟真的一样是 1，open_settings 拿它比对 exec()
                dialog.Accepted = dialog.return_value.Accepted = int(RealSettingsDialog.Accepted)
                dialog.return_value.exec.return_value = int(RealSettingsDialog.Accepted)
                dialog.return_value.settings.return_value = {"bili_codec": "hevc"}
                dialog.return_value.shortcuts.return_value = {}
                dialog.return_value.enabled_plugins.return_value = []
                dialog.return_value.restart_requested = False
                dialog.return_value.update_page.install_requested = False
                with patch.object(app_module.config_module, "save"):
                    window.open_settings()
            assert window.settings["bili_codec"] == "hevc"
            assert restarted == [window.wall.tiles[0]], "编码改了要重新取流"
        finally:
            window.close()
            application.processEvents()


def main() -> None:
    application = QApplication([])
    for name, check in (("codec 参数", check_codec_param),
                        ("通道名", check_channel_name),
                        ("通道名 -> 编码", check_codec_from_profile),
                        ("app-room 地址", check_app_urls),
                        ("play_url", check_play_url),
                        ("缺失编码回退及房间隔离", check_codec_fallback),
                        ("画质档位", check_quality_options),
                        ("取流线程", check_resolver)):
        check()
        print(f"  通过：{name}")
    check_player_container(application)
    print("  通过：播放器转封装容器")
    check_relay_without_proxy()
    print("  通过：没有 HLS 转发层时状态检测不崩")
    check_app_wiring(application)
    print("  通过：主窗口接线（编码传到取流、写回格子/播放器、改设置重取流）")
    print("PASS: Bili codec selection (avc=FLV direct, hevc/av1=HLS remux), "
          "per-room H.264 fallback, actual-codec tiers, channels and containers")


if __name__ == "__main__":
    main()
