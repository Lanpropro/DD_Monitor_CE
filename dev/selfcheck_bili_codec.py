"""离线自检：B站取流按设置的编码要流（H.264 直连 FLV，HEVC/AV1 原生 HLS 播放）。

全部打桩，不联网。
"""
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget

from ddm import bili
from ddm import player as player_module

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
    assert bili.is_hls_profile("app") is False
    assert bili.is_hls_profile("web") is False
    for codec in ("hevc", "av1"):
        profile = bili._app_profile(codec)
        assert profile == f"app-hls-{codec}", profile
        assert bili.HLS_SUFFIX in profile and bili.is_hls_profile(profile)
    assert bili._app_profile("avc") == "app"
    # 平台插件的通道名由插件作者定，可能凑巧带 hls —— 不归 B 站这条规则管。
    for profile in ("huya-hls", "my-hls-1", "douyu", "huya"):
        assert bili.is_hls_profile(profile) is False, profile
    for profile in ("app-plugin-hls-hevc", "web-custom-av1", "app-hls-unknown"):
        assert not bili.is_hls_profile(profile) and bili.codec_from_profile(profile) == ""


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
    assert hevc[0] == "https://cdn-hevc/hevc.m3u8" and hevc[2] == "app-hls-hevc"
    assert av1[0] == "https://cdn-av1/av1.m3u8" and av1[2] == "app-hls-av1"
    assert bili.is_hls_profile(hevc[2]) and bili.is_hls_profile(av1[2])
    assert avc[0] == "https://cdn-avc/avc.flv" and avc[2] == "app"
    assert not bili.is_hls_profile(avc[2])

    # 默认值（不传 codec）就是老行为：H.264 的 FLV 通道。
    with patch.object(bili.requests, "get", return_value=payload), \
            patch.object(bili, "_fetchable", return_value=True) as fetch:
        default = bili.play_url("1001", 10000)
        assert fetch.called
    assert default[0] == "https://cdn-avc/avc.flv" and default[2] == "app"
    assert default[3] == bili.STREAM_APP, "FLV 通道的请求头不能变"

def check_codec_fallback() -> None:
    for codec in ("hevc", "av1"):
        with patch.object(bili.requests, "get",
                          return_value=response(app_payload(hevc=[], av1=[]))) as get, \
                patch.object(bili, "_fetchable", return_value=True) as fetch:
            result = bili.play_url("1001", 10000, codec=codec)
        assert result == ("https://cdn-avc/avc.flv", 10000, "app", bili.STREAM_APP)
        assert [call.kwargs["params"]["codec"] for call in get.call_args_list] == [
            bili.CODEC_PARAM[codec], 0]
        assert fetch.call_args.args[1] == bili.STREAM_APP
        assert not bili.is_hls_profile(result[2])

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
    assert result == ("https://web-b/live.flv", 250, "web", bili.STREAM_WEB)
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
        resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
        with patch.object(bili, "play_url", return_value=(
                "http://cdn/x", 10000, profile, bili.STREAM_APP)) as play, \
                patch.object(bili, "room_quality_options",
                             return_value=[{"qn": 10000, "desc": "原画"}]) as options:
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
    resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
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
    """H.264/HEVC/AV1 和国内平台直接交给 libmpv，无 FFmpeg 播放中继。"""
    video = QWidget()
    core = Mock()
    with patch.object(player_module.TilePlayer, "bind"):
        tile_player = player_module.TilePlayer(video)
        tile_player.player = core
        try:
            for profile in ("app", "app-hls-hevc", "app-hls-av1", "web-hls", "huya", "douyu", "douyin"):
                tile_player.play("https://cdn.test/live.m3u8", profile, {"User-Agent": "test"})
                assert tile_player._media == "https://cdn.test/live.m3u8"
                assert tile_player._hls_proxy is None
                core.command.assert_called_with("loadfile", "https://cdn.test/live.m3u8", "replace")
                assert core.http_header_fields == ["User-Agent: test"]
        finally:
            tile_player.release()
            video.close()


def check_app_wiring(application) -> None:
    """主窗口接线：设置里的编码进 StreamResolver，取回后写回格子和播放器。"""
    from PySide6.QtCore import QThread, Signal

    from ddm import app as app_module
    from ddm.app import MainWindow

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
            plugin = Mock(kind="huya")
            with patch.object(window.plugins, "platform_for", return_value=plugin):
                window.start_tile(tile)
            assert seen[-1]["codec"] == "av1", "平台插件也应接收全局偏好并由取流层映射"

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
                dialog.Accepted = dialog.return_value.Accepted = int(RealSettingsDialog.DialogCode.Accepted)
                dialog.return_value.exec.return_value = int(RealSettingsDialog.DialogCode.Accepted)
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


def check_strict_codec() -> None:
    with patch.object(bili, "_app_play_info", return_value=app_payload(hevc=[], av1=[])) as info, \
            patch.object(bili, "_web_play_urls") as web, patch.object(bili, "_fetchable") as fetch:
        try:
            bili.play_url("1001", codec="av1", allow_codec_fallback=False)
        except bili.CodecUnavailable:
            pass
        else:
            raise AssertionError("严格探测不得用 H.264 替换缺失的 AV1")
        assert info.call_count == 1
        web.assert_not_called()
        fetch.assert_not_called()
    resolver = bili.StreamResolver("1001", codec="av1", strict_codec=True)
    failed, resolved = [], []
    resolver.failed.connect(lambda *args: failed.append(args))
    resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
    with patch.object(bili, "play_url", side_effect=bili.CodecUnavailable("missing")) as play:
        resolver.run()
    assert play.call_args.kwargs["allow_codec_fallback"] is False
    assert resolver.codec_unavailable and failed and not resolved


def check_original_quality_gate() -> None:
    for codec, profile in (("avc", "app"), ("hevc", "app-hls-hevc"), ("av1", "app-hls-av1")):
        for options in ([{"qn": 400, "desc": "蓝光"}], []):
            resolver = bili.StreamResolver("1001", 400, codec=codec, strict_codec=True)
            resolved, failed = [], []
            resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
            resolver.failed.connect(lambda *args, errors=failed: errors.append(args))
            with patch.object(bili, "play_url", return_value=("http://cdn/x", 400, profile, {})) as play, \
                    patch.object(bili, "room_quality_options", return_value=options):
                resolver.run()
            assert failed and not resolved and not resolver.codec_unavailable
            assert "原画" in resolver.original_quality_note
            assert ("未提供" if options else "未能验证") in resolver.original_quality_note
            assert play.call_count == 1

        resolver = bili.StreamResolver("1001", 400, codec=codec, strict_codec=True)
        resolved = []
        resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
        with patch.object(bili, "play_url", return_value=("http://cdn/x", 400, profile, {})), \
                patch.object(bili, "room_quality_options", return_value=[{"qn": 10000, "desc": "原画"}]):
            resolver.run()
        assert resolved and resolved[0][2] == 400 and not resolver.original_quality_note

    for codec in ("hevc", "av1"):
        resolver = bili.StreamResolver("1001", codec=codec)
        resolved = []
        resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
        with patch.object(bili, "play_url", side_effect=[
                ("http://cdn/preferred", 400, bili._app_profile(codec), {}),
                ("http://cdn/default", 250, "app", bili.STREAM_APP)]) as play, \
                patch.object(bili, "room_quality_options", side_effect=[
                    [{"qn": 400, "desc": "蓝光"}], [{"qn": 10000, "desc": "原画"}]]):
            resolver.run()
        assert resolved and resolved[0][3] == "app" and resolved[0][4][0]["qn"] == 10000
        assert [call.kwargs["codec"] for call in play.call_args_list] == [codec, "avc"]
        assert resolver.headers == bili.STREAM_APP and "未提供原画" in resolver.original_quality_note

    resolver = bili.StreamResolver("1001", codec="av1")
    resolved, failed = [], []
    resolver.resolved.connect(lambda *args, results=resolved: results.append(args))
    resolver.failed.connect(lambda *args, errors=failed: errors.append(args))

    def cancelled_options(*args):
        resolver.cancel()
        return [{"qn": 400, "desc": "蓝光"}]

    with patch.object(bili, "play_url", return_value=("http://cdn/x", 400, "app-hls-av1", {})) as play, \
            patch.object(bili, "room_quality_options", side_effect=cancelled_options):
        resolver.run()
    assert not resolved and not failed and play.call_count == 1


def check_codec_preflight(application) -> None:
    from ddm import app as app_module
    from ddm.app import MainWindow
    from ddm.dialogs import SettingsDialog
    from ddm.player import TilePlayer

    rooms = [{"room_id": str(1001 + i), "uname": f"探测{i}", "live": True, "quality": 250}
             for i in range(2)]
    state = {"plugins_enabled": [], "settings": {"bili_codec": "avc", "decode_mode": "auto",
             "recording_enabled": False, "recording_replay_enabled": False,
             "preview_on_hover": False, "auto_quality": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(bili.StreamResolver, "start"), patch.object(TilePlayer, "_play_media"), \
            patch.object(bili, "room_quality_options",
                         return_value=[{"qn": 10000, "desc": "原画"}]):
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="1x2", state=state)
        window.show()
        application.processEvents()
        first, other = window.wall.tiles[:2]
        window._set_tile_codecs(first, {"bili_codec": "av1"})
        initial = window._resolvers[first]
        with patch.object(bili, "play_url", side_effect=[
                ("http://initial/av1", 400, "app-hls-av1", bili.STREAM_APP),
                ("http://initial/avc", 250, "app", bili.STREAM_APP)]), \
                patch.object(bili, "room_quality_options", side_effect=[
                    [{"qn": 400, "desc": "蓝光"}],
                    [{"qn": qn, "desc": str(qn)} for qn in (10000, 400, 250)]]):
            initial.run()
        window._on_resolver_finished(first, initial)
        assert first.stream_codec == "avc"
        assert "未提供原画" in first.codec_probe_note and "默认 H.264" in window._codec_status(first)
        assert window._codec_settings(first)["bili_codec"] == "avc"
        assert [option["qn"] for option in first.quality_options] == [10000, 400, 250]
        first.codec_overrides = {"bili_codec": "hevc"}
        first.codec_probe_note = ""
        window._play_on(first, "http://old/hevc", 250, "app-hls-hevc")
        window._play_on(other, "http://old/avc", 250, "app")
        player = window.players[first]
        window._open_tile_codecs(first)
        dialog = window._codec_dialogs[first]

        def complete(tile, *, profile=None, error=None):
            resolver = window._resolvers[tile]
            result = ("http://new/stream", 250, profile, bili.STREAM_APP)
            with patch.object(bili, "play_url", return_value=result, side_effect=error):
                resolver.run()
            window._on_resolver_finished(tile, resolver)
            return resolver

        try:
            with patch.object(player, "play") as play, patch.object(window, "_schedule_retry") as retry:
                window._set_tile_codecs(first, {"bili_codec": "av1"})
                assert window._resolvers[first].strict_codec
                assert "正在探测 AV1" in window._codec_status(first)
                assert first.stream_url == "http://old/hevc"
                play.assert_not_called()
                complete(first, error=bili.CodecUnavailable("missing"))
                play.assert_not_called()
                retry.assert_not_called()
                assert window._codec_settings(first)["bili_codec"] == "hevc"
                assert "未提供 AV1" in window._codec_status(first)
                assert "继续使用 HEVC" in window._codec_status(first)
                assert dialog.controls.bili_codec.currentData() == "hevc"
                assert not player._decoder_error and other.stream_url == "http://old/avc"

                for options in ([{"qn": 400, "desc": "蓝光"}], []):
                    window._set_tile_codecs(first, {"bili_codec": "av1"})
                    with patch.object(bili, "room_quality_options", return_value=options):
                        complete(first, profile="app-hls-av1")
                    play.assert_not_called()
                    retry.assert_not_called()
                    assert first.stream_codec == "hevc" and first.stream_url == "http://old/hevc"
                    assert "原画" in first.codec_probe_note and "未切换" in window._codec_status(first)
                    assert ("未提供原画" if options else "未能验证") in first.codec_probe_note
                    assert not player._decoder_error and other.stream_url == "http://old/avc"
                    assert dialog.controls.bili_codec.currentData() == "hevc"

                window._set_tile_codecs(first, {"bili_codec": "av1"})
                complete(first, error=RuntimeError("network unavailable"))
                play.assert_not_called()
                assert "未能验证" in first.codec_probe_note and "未提供" not in first.codec_probe_note

                window._set_tile_codecs(first, {"bili_codec": "av1"})
                complete(first, profile="app-hls-av1")
                assert play.call_count == 1 and first.stream_codec == "av1"
                assert not first.codec_probe_note
                play.reset_mock()

                window._set_tile_codecs(first, {"bili_codec": "hevc"})
                complete(first, profile="app")
                play.assert_not_called()
                assert first.stream_codec == "av1" and "未提供 HEVC" in first.codec_probe_note

                window._set_tile_codecs(first, {"bili_codec": "hevc"})
                stale = window._resolvers[first]
                window._set_tile_codecs(first, {"bili_codec": "av1"})
                stale.failed.emit("1001", "cancelled probe")
                complete(first, profile="app-hls-av1")
                assert not first.codec_probe_note and play.call_count == 1
                play.reset_mock()

                window._set_tile_codecs(first, {"bili_codec": "hevc"})
                stale = window._resolvers[first]
                window._set_tile_codecs(first, {"bili_codec": "avc"})
                stale.resolved.emit("1001", "http://stale", 250, "app-hls-hevc", [])
                play.assert_not_called()
                complete(first, profile="app")
                assert play.call_count == 1 and first.stream_codec == "avc"
                play.reset_mock()

                window._set_tile_codecs(first, {"bili_codec": "av1"})
                stale = window._resolvers[first]
                window._on_pause_toggled(first.room)
                assert first.paused and first.codec_reconnect_pending and stale.is_cancelled()
                stale.resolved.emit("1001", "http://paused", 250, "app-hls-av1", [])
                play.assert_not_called()
                window._on_pause_toggled(first.room)
                complete(first, profile="app-hls-av1")
                assert play.call_count == 1 and not first.paused
                play.reset_mock()

                window._set_tile_codecs(first, {"bili_codec": "hevc", "decode_mode": "none"})
                complete(first, error=bili.CodecUnavailable("missing"))
                assert first.stream_codec == "av1"
                assert play.call_count == 1 and play.call_args.kwargs["options"] == ("hwdec=no",)
                assert window._codec_settings(first)["bili_codec"] == "av1"

            first.codec_overrides = {}
            other.codec_overrides = {}
            window.settings.update(bili_codec="hevc", decode_mode="auto")
            window._play_on(first, "http://retained/hevc", 250, "app-hls-hevc")
            window._play_on(other, "http://retained/avc", 250, "app")
            with patch.object(app_module, "SettingsDialog") as settings:
                settings.Accepted = int(SettingsDialog.DialogCode.Accepted)
                settings.return_value.exec.return_value = int(SettingsDialog.DialogCode.Accepted)
                settings.return_value.settings.return_value = {"bili_codec": "av1"}
                settings.return_value.shortcuts.return_value = {}
                settings.return_value.enabled_plugins.return_value = []
                settings.return_value.restart_requested = False
                settings.return_value.update_page.install_requested = False
                window.open_settings()
            assert window._resolvers[first].strict_codec and window._resolvers[other].strict_codec
            complete(first, error=bili.CodecUnavailable("missing"))
            complete(other, profile="app-hls-av1")
            assert window.settings["bili_codec"] == "av1"
            assert window._codec_settings(first)["bili_codec"] == "hevc"
            assert other.stream_codec == "av1"

            with patch.object(player, "play") as play:
                window._set_tile_codecs(first, {"bili_codec": "avc"})
                stale = window._resolvers[first]
                first.set_room({"room_id": "2001", "live": True})
                stale.resolved.emit("1001", "http://old-room", 250, "app", [])
                stale.failed.emit("1001", "old error")
                play.assert_not_called()
                assert not first.codec_probe_note and not first.stream_url
                window.close()
                stale.resolved.emit("1001", "http://closed", 250, "app", [])
                play.assert_not_called()
        finally:
            window.close()
            application.processEvents()


def check_platform_codec_resolver() -> None:
    from types import SimpleNamespace

    from ddm.plugins import LoginRequiredError, StreamCodecUnavailable

    success = ("http://fixture/source", 1002000, "huya", {"X-Selected": "yes"}, "avc")
    for error, note in ((StreamCodecUnavailable("missing"), "HEVC 直播源不可用"),
                        (RuntimeError("CDN failed"), "HEVC 取流失败")):
        platform = SimpleNamespace(play_url_for_codec=Mock(side_effect=[error, success]),
                                   room_quality_options=Mock(return_value=None))
        resolver = bili.StreamResolver("huya:1", 1002000, platform=platform, codec="av1")
        results, failures = [], []
        resolver.resolved.connect(lambda *args, output=results: output.append(args))
        resolver.failed.connect(lambda *args, output=failures: output.append(args))
        resolver.run()
        assert results and not failures and results[0][-1] == []
        assert [call.kwargs["codec"] for call in platform.play_url_for_codec.call_args_list] == ["hevc", "avc"]
        assert resolver.source_codec == "avc" and note in resolver.codec_probe_note
        assert resolver.headers == success[3]

    for errors, login, unavailable in (([RuntimeError("network"), StreamCodecUnavailable("missing")], False, False),
                                       ([StreamCodecUnavailable("missing")] * 2, False, True),
                                       ([LoginRequiredError("login expired")], True, False)):
        platform = SimpleNamespace(play_url_for_codec=Mock(side_effect=errors),
                                   room_quality_options=Mock(return_value=[]))
        resolver = bili.StreamResolver("huya:1", platform=platform, codec="av1")
        results, failures = [], []
        resolver.resolved.connect(lambda *args, output=results: output.append(args))
        resolver.failed.connect(lambda *args, output=failures: output.append(args))
        resolver.run()
        assert not results and len(failures) == 1
        assert resolver.login_required == login and resolver.codec_unavailable == unavailable
        assert platform.play_url_for_codec.call_count == len(errors)

    for options in ([{"qn": 1002000}], "bad options"):
        platform = SimpleNamespace(play_url_for_codec=Mock(return_value=success),
                                   room_quality_options=Mock(return_value=options))
        resolver = bili.StreamResolver("huya:1", platform=platform)
        failures = []
        resolver.failed.connect(lambda *args, output=failures: output.append(args))
        resolver.run()
        assert len(failures) == 1

    platform = Mock()
    platform.play_url.return_value = success[:4]
    platform.room_quality_options.return_value = []
    resolver = bili.StreamResolver("huya:1", platform=platform, codec="av1")
    resolver.run()
    platform.play_url.assert_called_once_with("huya:1", 250)
    assert not resolver.source_codec and "旧版插件" in resolver.codec_probe_note

    wrong_codec = (*success[:4], "av1")
    platform = SimpleNamespace(play_url_for_codec=Mock(side_effect=[wrong_codec, success]),
                               room_quality_options=Mock(return_value=[]))
    resolver = bili.StreamResolver("huya:1", platform=platform, codec="av1")
    resolver.run()
    assert resolver.source_codec == "avc" and platform.play_url_for_codec.call_count == 2

    def cancel_request(*args, **kwargs):
        resolver.cancel()
        raise RuntimeError("cancel during request")

    platform.play_url_for_codec = Mock(side_effect=cancel_request)
    resolver = bili.StreamResolver("huya:1", platform=platform, codec="av1")
    results, failures = [], []
    resolver.resolved.connect(lambda *args: results.append(args))
    resolver.failed.connect(lambda *args: failures.append(args))
    resolver.run()
    assert not results and not failures and platform.play_url_for_codec.call_count == 1


def check_platform_codec_wiring(application) -> None:
    from ddm.app import MainWindow
    from ddm.plugins import Platform, StreamCodecUnavailable

    class CodecPlatform(Platform):
        kind = "huya"

        def __init__(self):
            self.calls = []
            self.available = {"avc", "hevc"}

        def play_url_for_codec(self, room_id, quality=250, *, codec="avc"):
            self.calls.append((room_id, quality, codec))
            if codec not in self.available:
                raise StreamCodecUnavailable(f"missing {codec}")
            return f"http://fixture/{codec}", quality, self.kind, {"X-Codec": codec}, codec

        def room_quality_options(self, room_id):
            return [{"qn": 1002000, "desc": "平台高清"}]

    class LegacyPlatform(Platform):
        kind = "huya"

        def play_url(self, room_id, quality=250):
            return "http://fixture/legacy", quality, "app", {"X-Legacy": "1"}

    rooms = [{"room_id": f"huya:{i}", "uname": f"平台{i}", "live": True, "quality": 1002000}
             for i in range(2)]
    state = {"plugins_enabled": [], "settings": {"bili_codec": "av1", "auto_quality": False,
             "recording_enabled": False, "recording_replay_enabled": False,
             "preview_on_hover": False, "danmaku_enabled": False}}
    platform = CodecPlatform()
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(bili.StreamResolver, "start"), patch.object(player_module.TilePlayer, "_play_media"):
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="1x2", state=state)
        window.show()
        application.processEvents()
        first, other = window.wall.tiles[:2]

        first.set_room(dict(rooms[0]))
        other.set_room(dict(rooms[1]))

        def complete(tile):
            resolver = window._resolvers[tile]
            resolver.run()
            window._on_resolver_finished(tile, resolver)
            assert tile not in window._resolvers
            assert "等待新流" not in window._codec_status(tile)
            return resolver

        with patch.object(window.plugins, "platform_for", return_value=platform), \
                patch.object(window.recorder, "on_resolved") as record, \
                patch.object(window, "_schedule_retry"), \
                patch.object(bili, "room_quality_options", side_effect=AssertionError("Bili quality gate")):
            try:
                window.start_tile(first)
                assert window._resolvers[first].codec == "av1"
                complete(first)
                assert [call[2] for call in platform.calls] == ["hevc"]
                assert first.stream_codec == window.players[first].stream_codec == "hevc"
                assert first.stream_profile == "huya" and first.stream_headers == {"X-Codec": "hevc"}
                assert first.quality == 1002000 and record.call_args.args == (first,)
                assert "HEVC" in window._codec_status(first) and "AV1" in first.codec_probe_note
                assert window.settings["bili_codec"] == "av1" and first.codec_overrides == {}

                platform.calls.clear()
                platform.available = {"avc"}
                window.start_tile(other)
                complete(other)
                assert [call[2] for call in platform.calls] == ["hevc", "avc"]
                assert other.stream_codec == "avc" and "回退 H.264" in other.codec_probe_note
                assert first.stream_codec == "hevc"

                platform.calls.clear()
                window._set_tile_codecs(first, {"bili_codec": "avc"})
                complete(first)
                assert [call[2] for call in platform.calls] == ["avc"]
                assert window.settings["bili_codec"] == "av1"

                platform.available = set()
                platform.calls.clear()
                record.reset_mock()
                window.start_tile(other)
                complete(other)
                record.assert_not_called()
                assert [call[2] for call in platform.calls] == ["hevc", "avc"]
                assert "取流失败" in other.codec_probe_note
                assert not other._buffering

                platform.available = {"hevc", "avc"}
                window._set_tile_codecs(first, {"bili_codec": "hevc"})
                stale = window._resolvers[first]
                window._set_tile_codecs(first, {"bili_codec": "avc"})
                assert stale.is_cancelled()
                stale.source_codec = "hevc"
                stale.resolved.emit("huya:0", "http://stale", 1002000, "huya", [])
                assert first.stream_codec == "avc"
                complete(first)

                window._set_tile_codecs(first, {"bili_codec": "av1"})
                stale = window._resolvers[first]
                window._on_pause_toggled(first.room)
                assert first.paused and stale.is_cancelled() and first.codec_reconnect_pending
                stale.resolved.emit("huya:0", "http://paused", 1002000, "huya", [])
                assert first.stream_codec == "avc"
                window._on_pause_toggled(first.room)
                complete(first)
                assert not first.paused and first.stream_codec == "hevc"

                window.start_tile(first)
                with patch.object(platform, "room_quality_options", side_effect=RuntimeError("quality network failure")):
                    complete(first)
                assert "quality network failure" in first.codec_probe_note

                window.start_tile(first)
                with patch.object(window.players[first], "play", side_effect=RuntimeError("play failed")):
                    complete(first)
                assert "播放失败" in window._codec_status(first) and not first._buffering

                with patch.object(window.plugins, "platform_for", return_value=LegacyPlatform()):
                    window.start_tile(first)
                    complete(first)
                assert first.stream_profile == "app" and first.stream_codec == ""
                assert window.players[first].stream_codec == ""
                assert "旧版插件" in first.codec_probe_note

                window.start_tile(first)
                stale = window._resolvers[first]
                first.set_room({"room_id": "huya:changed", "live": True})
                stale.resolved.emit("huya:0", "http://old-room", 1002000, "huya", [])
                assert not first.stream_url
                window.close()
                stale.failed.emit("huya:0", "closed")
                assert not first.codec_probe_note
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
                        ("取流线程", check_resolver),
                        ("严格编码探测", check_strict_codec),
                        ("原画档位切换条件与初始回退", check_original_quality_gate)):
        check()
        print(f"  通过：{name}")
    check_player_container(application)
    print("  通过：播放器原生 FLV/HLS")
    print("  通过：没有 HLS 转发层时状态检测不崩")
    check_app_wiring(application)
    print("  通过：主窗口接线（编码传到取流、写回格子/播放器、改设置重取流）")
    check_codec_preflight(application)
    print("  通过：编码切换探测、原流保留、状态回写、全局隔离及迟到结果保护")
    check_platform_codec_wiring(application)
    print("  通过：平台编码映射、真实编码/通道、回退、兼容、暂停取消及终态")
    check_platform_codec_resolver()
    print("  通过：平台网络回退、登录、错误编码、兼容 Mock、空/异常画质及取消")
    print("PASS: Bili codec selection (avc=FLV direct, hevc/av1=native HLS), "
          "per-room H.264 fallback, actual-codec tiers, channels and containers")


if __name__ == "__main__":
    main()
