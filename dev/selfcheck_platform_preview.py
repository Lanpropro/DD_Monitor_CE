"""离线验收：国内三平台低码率预览、请求头、横竖屏位置与取消/关闭清理。"""
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, plugins, preview, widgets  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def settle(app, predicate, seconds=4):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("Preview check timed out")


def response(*, text="", data=None):
    result = Mock(text=text, url="https://cdn.test/live.flv")
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.json.return_value = data
    result.iter_content.side_effect = lambda *_args: iter([b"FLV"])
    return result


class FakePlayer:
    all_players = []

    def __init__(self, target, parent=None, *, silent=False):
        assert silent
        self.target = target
        self.stateChanged = Mock()
        self.plays = []
        self.stops = 0
        self.released = False
        self.all_players.append(self)

    def set_muted(self, value):
        assert value is True

    def set_volume(self, value):
        assert value == 0

    def play(self, url, profile="web", **kwargs):
        assert kwargs["options"] == preview.PREVIEW_MEDIA_OPTIONS
        self.plays.append((url, profile, kwargs.get("headers")))

    def stop(self):
        self.stops += 1

    def release(self):
        self.released = True


def check_rates(manager):
    module = sys.modules[type(manager.platforms["huya"]).__module__]
    huya = manager.platforms["huya"]
    session = module.Streamlink()
    stream_info = {"sHlsUrl": "https://cdn.test", "sStreamName": "live", "sHlsUrlSuffix": "m3u8",
                   "sHlsAntiCode": "fm=test&fs=test", "sCdnType": "AL"}
    data = {"data": [{"gameStreamInfoList": [stream_info]}],
            "vMultiStreamInfo": [{"iBitRate": rate} for rate in (0, 4000, 500, 2000)]}
    page = "var hyPlayerConfig = {stream:" + json.dumps(data) + "};</script>"
    with patch.object(module, "Streamlink", return_value=session), \
            patch.object(session.http, "get", return_value=response(text=page)), \
            patch.object(module.Huya, "_get_stream_params", return_value={"token": "test"}) as params:
        for is_preview, bitrate in ((True, 500), (False, 0)):
            huya._streams("huya:123", 10000, preview=is_preview)
            assert params.call_args.args[-1] == bitrate
        del data["vMultiStreamInfo"]
        with patch.object(session.http, "get", return_value=response(
                text="var hyPlayerConfig = {stream:" + json.dumps(data) + "};</script>")):
            huya._streams("huya:123", 10000, preview=True)
            assert params.call_args.args[-1] == 0
    douyu = manager.platforms["douyu"]
    edge = {"rtmp_url": "https://stream.test.edgesrv.com", "rtmp_live": "source.flv",
            "cdnsWithName": [{"cdn": "hw-h5"}], "multirates": [
                {"bit": 4000, "rate": 2}, {"bit": 800, "rate": 4}, {"bit": 2000, "rate": 3}]}
    low = {"rtmp_url": "https://cdn.test", "rtmp_live": "preview.flv"}
    with patch.object(douyu, "room_info", return_value=plugins.RoomInfo("douyu:123", live=True)), \
            patch.object(douyu, "_request_source", side_effect=[edge, low]) as request:
        assert douyu._streams(session, "douyu:123", 10000, preview=True)["source"].to_url().endswith("preview.flv")
        assert request.call_args.args[1:] == ("123", "hw-h5")
        assert request.call_args.kwargs == {"rate": 4}
    parser = module.Douyu(session, "https://www.douyu.com/123")
    encryption = (123, {"key": "key", "rand_str": "random", "enc_time": 1,
                        "is_special": 0, "enc_data": "data"})
    with patch.object(parser, "_get_encryption", return_value=encryption), \
            patch.object(parser, "_compute_auth", return_value="auth"), \
            patch.object(session.http, "post", return_value=response(data={"error": 0, "data": low})) as post:
        douyu._request_source(parser, "123", "hw-h5", rate=4)
        assert post.call_args.kwargs["data"]["rate"] == "4"
    session.http.close()
    for kind in ("douyu", "douyin"):
        platform = manager.platforms[kind]
        session = SimpleNamespace(http=Mock(headers={"User-Agent": "test"}))
        streams = {key: Mock(to_url=Mock(return_value=f"https://cdn.test/{key}.flv"))
                   for key in ("worst", "best")}
        with patch.object(module, "Streamlink", return_value=session), \
                patch.object(platform, "_streams", return_value=streams) as get_streams, \
                patch.object(session.http, "get", return_value=response()) as get:
            for is_preview, key in ((True, "worst"), (False, "best")):
                platform.play_url(kind + ":123", 10000, preview=is_preview)
                assert get_streams.call_args.kwargs["preview"] == is_preview
                assert streams[key].to_url.called
                if kind == "douyin":
                    assert get.call_args.args[0] == f"https://cdn.test/{key}.flv"
                else:
                    get.assert_not_called()
    print("PASS: preview low bitrates, source fallback, wall source unchanged, Douyu single consumer")


def main():
    app = QApplication([])
    state = {"plugins_enabled": ["domestic_live"], "settings": {"preview_on_hover": True,
             "recording_enabled": False, "recording_replay_enabled": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(preview, "TilePlayer", FakePlayer), \
            patch.object(widgets, "TilePlayer", FakePlayer), \
            patch.object(bili, "play_url", side_effect=AssertionError("Plugin preview must not call Bili")):
        window = MainWindow([], [], state=state, layout_id="2x2")
        check_rates(window.plugins)
        window.resize(1200, 720)
        window.show()
        hp = window.hover_preview
        try:
            for kind in ("huya", "douyu", "douyin"):
                platform = window.plugins.platforms[kind]
                room = plugins.RoomInfo(kind + ":123", uname=kind, live=True, platform=kind).as_dict()
                window.sidebar.add_room(room)
            for width, height in ((1200, 720), (560, 1000)):
                window.resize(width, height)
                settle(app, lambda: window.sidebar.side == ("top" if height > width else "left"))
                for card_mode, collapsed in ((True, False), (False, False), (True, True)):
                    hp.cancel()
                    window.sidebar.set_card_mode(card_mode)
                    window.sidebar.set_collapsed(collapsed, animate=False)
                    app.processEvents()
                    for item in window.sidebar.items():
                        kind = item.room["platform"]
                        platform = window.plugins.platforms[kind]
                        headers = {"Referer": platform.room_url(item.room["room_id"]), "User-Agent": "preview-test"}
                        with patch.object(platform, "preview_url", return_value=("https://cdn.test/live.flv", 10000, kind, headers)) as get:
                            if window.sidebar.side == "top" and collapsed:
                                window.sidebar._head_strip._set_hover_room(item.room["room_id"])
                            hp.on_hover(item.room)
                            hp._delay.stop()
                            hp._show_now()
                            settle(app, lambda: hp._resolver is None and not hp._resolvers_running)
                            get.assert_called_once_with(item.room["room_id"])
                            player = hp._popup_player if collapsed or not card_mode else item.thumb._player
                            assert player.plays[-1][1:] == (kind, headers)
                            hp.on_hover(item.room)
                            assert not hp._delay.isActive(), "Repeated enter must not restart preview"
                            if collapsed or not card_mode:
                                assert hp._popup.isVisible() and hp._popup.parentWidget() is window
                                assert window.rect().contains(hp._popup.geometry())
                                if window.sidebar.side == "top":
                                    anchor = hp._anchor_of(item)
                                    origin = anchor.mapTo(window, QPoint(0, 0))
                                    assert hp._popup.y() == origin.y() + anchor.height() + preview.PREVIEW_GAP
                                    expected = origin.x() + (anchor.width() - hp._popup.width()) // 2
                                    assert hp._popup.x() == max(0, min(expected, window.width() - hp._popup.width()))
                                    if collapsed:
                                        avatar = anchor
                                        item.room["title"] = "Updated title from status poll"
                                        window.sidebar.resort(animate=False)
                                        app.processEvents()
                                        assert hp._anchor_of(item) is avatar
                                        assert not hp._grace.isActive() and hp._popup.isVisible()
                            before = player.stops
                            hp.on_unhover(item.room)
                            settle(app, lambda: hp._item is None)
                            assert player.stops > before and not hp._popup.isVisible()
                print(f"PASS: {window.sidebar.side}, 3 platforms, inline/list/avatar previews, headers, muted, leave cleanup")
            item = window.sidebar.items()[0]
            platform = window.plugins.platforms[item.room["platform"]]
            room = dict(item.room)
            with patch.object(platform, "play_url", return_value=("https://cdn.test/live.flv", 80, platform.kind, {})):
                hp.on_hover(item.room)
                hp._delay.stop()
                hp._show_now()
                settle(app, lambda: hp._resolver is None)
                window._on_status_updated({item.room["room_id"]: {
                    "live": False, "viewers": "", "title": "", "uname": ""}})
                assert hp._item is None and not hp._popup.isVisible()
                item.set_live(True)
                hp.on_hover(item.room)
                hp._delay.stop()
                hp._show_now()
                settle(app, lambda: hp._resolver is None)
                window.remove_room(item.room)
                assert hp._item is None and not hp._popup.isVisible()
                assert item.thumb._player is None
            window.sidebar.add_room(room)
            item = window.sidebar.items()[0]
            platform = window.plugins.platforms[item.room["platform"]]
            with patch.object(platform, "play_url", return_value=("https://cdn.test/live.flv", 80, platform.kind, {})):
                hp.on_hover(item.room)
                hp._delay.stop()
                hp._show_now()
                settle(app, lambda: hp._resolver is None)
                before = hp._popup_player.stops
                window.plugins.enabled = set()
                window._sync_platform_rooms()
                assert not window.sidebar.rooms() and not hp._popup.isVisible()
                assert hp._popup_player.stops > before
            window.plugins.enabled = {"domestic_live"}
            window._sync_platform_rooms()
            for item in window.sidebar.items():
                item.room["live"] = True
            print("PASS: deleting focus releases inline player; disabling plugin stops popup and suspends all cards")
            item = window.sidebar.items()[0]
            platform = window.plugins.platforms[item.room["platform"]]
            def slow(*_args, **_kwargs):
                time.sleep(.3)
                return "https://cdn.test/late.flv", 80, platform.kind, {}
            with patch.object(platform, "play_url", side_effect=slow):
                hp.on_hover(item.room)
                hp._delay.stop()
                hp._show_now()
                resolver = hp._resolver
                window.resize(1200, 720)
                app.processEvents()
                assert hp._item is None and resolver._cancelled
                settle(app, lambda: not hp._resolvers_running)
                assert not hp._popup.isVisible()
                hp.on_hover(item.room)
                hp._delay.stop()
                hp._show_now()
                resolver = hp._resolver
                time.sleep(.05)
                hp.cancel()
                assert resolver in hp._resolvers_running
                window.close()
                assert not resolver.isRunning(), "Closing must wait for cancelled platform requests"
            assert all(player.released for player in FakePlayer.all_players)
            print("PASS: orientation cancels pending preview, stale results discarded, close waits without terminating")
        finally:
            window.close()
            app.processEvents()


if __name__ == "__main__":
    main()
