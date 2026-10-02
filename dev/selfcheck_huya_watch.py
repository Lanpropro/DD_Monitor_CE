"""虎牙离线自检：取流适配、真实拖入格子链路、持久化与旧卡片迁移。"""
import os
import base64
import json
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtCore import QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, config, images, plugins  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import AddRoomDialog  # noqa: E402
from ddm.widgets import ROOM_MIME, NavItem, Tile, WATCHING_TEXT  # noqa: E402


def settle(app, condition):
    deadline = time.monotonic() + 4
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition(), "后台任务未按预期完成"


def main():
    app = QApplication.instance() or QApplication([])
    manager = plugins.PluginManager(enabled=["huya_watch"])
    manager.load()
    platform = manager.platforms["huya"]
    module = sys.modules[type(platform).__module__]
    for raw in ("huya:660000", "https://www.huya.com/660000",
                "https://m.huya.com/660000/?from=share", "http://huya.com/660000#share"):
        assert platform.matches(raw)
        assert platform.normalize(raw) == "huya:660000", raw
    assert platform.normalize("huya:godv") == "huya:godv"
    assert not platform.matches("660000"), "纯数字仍属于 B 站"
    for raw in ("huya:", "huya:../secret", "huya:a/b", "https://www.huya.com/%2Fsecret",
                "https://www.huya.com.evil.test/660000", "https://evil.test/660000",
                "https://user:pass@www.huya.com/660000", "https://www.huya.com:1234/660000"):
        try:
            platform.normalize(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(raw)
    print("PASS: canonical IDs and official URL validation")

    session = SimpleNamespace(http=Mock(headers={"User-Agent": "test-agent"}))
    parser = SimpleNamespace(author="测试虎牙主播", title="测试直播")
    def page_response(live=True, screenshot="//live-cover.msstatic.com/room.jpg", avatar="https://huyaimg.msstatic.com/avatar.jpg"):
        response = Mock()
        response.text = ("var TT_ROOM_DATA = " + json.dumps({"isOn": live,
            "introduction": parser.title, "screenshot": screenshot, "totalCount": 999999}) +
            "; var TT_PROFILE_INFO = " + json.dumps({"nick": parser.author, "avatar": avatar}) + ";")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response
    with patch.object(module.requests, "get", return_value=page_response()) as get, \
            patch.object(type(platform), "_streams", side_effect=AssertionError("状态查询不应取流")):
        info = platform.room_info("huya:660000").as_dict()
        assert info["live"] and info["uname"] == parser.author
        assert info["face"] == "https://huyaimg.msstatic.com/avatar.jpg"
        assert info["cover_url"] == "https://live-cover.msstatic.com/room.jpg"
        assert info["viewers"] == "" and "totalCount" not in info
        assert get.call_count == 1 and "cookies" not in get.call_args.kwargs
    with patch.object(module.requests, "get", return_value=page_response(False)):
        assert not platform.room_info("huya:660000").live
    with patch.object(module.requests, "get", return_value=page_response(
            screenshot="https://msstatic.com.evil.test/a.jpg", avatar="file:///avatar.jpg")):
        unsafe = platform.room_info("huya:660000")
        assert not unsafe.face and not unsafe.cover_url
    for live in (None, 1):
        with patch.object(module.requests, "get", return_value=page_response(live)):
            try:
                platform.room_info("huya:660000")
            except RuntimeError:
                pass
            else:
                raise AssertionError("损坏的直播状态不能误报下播")
    streams = {"al_source": Mock(to_url=Mock(return_value="https://cdn.test/live.m3u8?token=test")),
               "hs_source": Mock(to_url=Mock(return_value="https://backup.test/live.m3u8"))}
    response = Mock(url="https://backup.test/live.m3u8")
    response.iter_content.return_value = iter([b"#EXTM3U"])
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    with patch.object(type(platform), "_streams", return_value=(session, parser, streams)):
        with patch.object(module.requests, "get", side_effect=[
                module.requests.ConnectionError("first CDN failed"), response]) as get:
            url, qn, profile, headers = platform.play_url("huya:660000")
            assert (url, qn, profile) == (response.url, 10000, "huya")
            assert headers["Referer"] == "https://www.huya.com/"
            assert get.call_count == 2 and "cookies" not in get.call_args.kwargs
    with patch.object(type(platform), "_streams", return_value=(session, parser, {})):
        try:
            platform.play_url("huya:660000")
        except RuntimeError:
            pass
        else:
            raise AssertionError("未开播不能生成播放地址")
    session.http.close.assert_called()
    stream_data = {"data": [{"gameStreamInfoList": [{"sHlsUrl": "https://cdn.test/hls",
        "sStreamName": "stream", "sHlsUrlSuffix": "m3u8", "sHlsAntiCode": "fm=test&fs=test",
        "sCdnType": "AL", "sFlvUrl": "https://wrong.test/flv"}]}]}
    encoded = base64.b64encode(json.dumps(stream_data).encode()).decode()
    hls_session = module.Streamlink()
    for data in (json.dumps(encoded), json.dumps(stream_data)):
        with patch.object(hls_session.http, "get", return_value=SimpleNamespace(
                text="<script>var hyPlayerConfig = {stream: " + data + "};</script>")), \
                patch.object(module, "Streamlink", return_value=hls_session), \
                patch.object(module.Huya, "_get_stream_params", return_value={"token": "test"}):
            _session, _parser, parsed = platform._streams("huya:660000")
            assert parsed["al_source"].to_url() == "https://cdn.test/hls/stream.m3u8?token=test"
    hls_session.http.close()
    with tempfile.TemporaryDirectory() as root, patch.object(images, "REPO", root):
        from PySide6.QtCore import QBuffer, QIODevice
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.red)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        with patch.object(images.requests, "get", return_value=SimpleNamespace(
                status_code=200, content=bytes(buffer.data()))) as get:
            assert not images.load_pixmap(info["face"]).isNull()
            assert get.call_args.kwargs["headers"]["Referer"] == "https://www.huya.com/"
            assert not images.load_pixmap(info["cover_url"], "covers").isNull()
            images.remember_room_avatar(info["room_id"], info["face"])
            images.remember_room_cover(info["room_id"], info["cover_url"])
            assert not images.load_room_avatar(info["room_id"]).isNull()
            assert not images.load_room_cover(info["room_id"]).isNull()
    for rid, label in (("huya:660000", "虎牙"), ("9001", "B站"), ("douyin:123", "抖音")):
        room = {"room_id": rid, "live": True, "online": "999", "viewers": "888"}
        item = NavItem(room, 0)
        assert item.platform_badge.text() == "" and item.platform_badge.toolTip() == label
        assert not item.platform_badge.pixmap().isNull()
        if rid.startswith("huya:") or rid.isdigit():
            name = "huya.png" if rid.startswith("huya:") else "bilibili.ico"
            expected = QIcon(os.path.join(REPO, "assets", "platforms", name))
            assert not expected.isNull()
            assert item.platform_badge.pixmap().toImage() == expected.pixmap(20, 20).toImage()
        item.resize(240, 128)
        item.show()
        app.processEvents()
        assert item.platform_badge.isVisible()
        item.set_compact(True)
        assert item.platform_badge.isVisible() and item.platform_badge.parentWidget() is item.thumb.face
        item.set_compact(False)
        item.set_card_mode(False)
        item.thumb._layout_overlay()
        assert item.platform_badge.parentWidget() is item.thumb
        assert item.name_label.geometry().right() < item.platform_badge.x()
        item.set_portrait_strip(True)
        app.processEvents()
        assert item.platform_badge.isVisible() and item.badge.isHidden()
        tile = Tile(dict(room))
        tile._refresh_badge()
        if ":" in rid:
            assert not tile.stream_badge.viewers
            assert "人数" not in tile.stream_badge.toolTip()
        else:
            assert tile.stream_badge.viewers == "999"
        item.close()
        tile.close()
    print("PASS: official HLS fields, avatar/cover cache, platform labels, no other-platform counts")
    resolver = bili.StreamResolver("huya:660000", platform=platform)
    resolved = []
    resolver.resolved.connect(lambda *args: resolved.append(args))
    with patch.object(platform, "play_url", return_value=(url, qn, profile, headers)), \
            patch.object(bili, "play_url", side_effect=AssertionError("误用 B 站")):
        resolver.run()
        assert resolved[0][1] == url and resolver.headers == headers
        resolved.clear()
        resolver.cancel()
        resolver.run()
        assert not resolved
    poller = bili.StatusPoller(["9001", "huya:660000"], platforms={"huya": platform})
    status = []
    poller.updated.connect(status.append)
    with patch.object(bili, "rooms_status", return_value={"9001": {}}) as bili_status, \
            patch.object(platform, "rooms_status", return_value={"huya:660000": info}):
        poller.run()
        bili_status.assert_called_once_with(["9001"])
        assert status[0]["huya:660000"]["live"]
    with patch.object(platform, "rooms_status", side_effect=RuntimeError("network")), \
            patch.object(bili, "rooms_status", return_value={"9001": {}}):
        status.clear()
        poller.run()
        assert "huya:660000" not in status[0], "网络错误不能标记下播"
    print("PASS: stream/CDN fallback, offline state, headers, cancellation, platform polling")

    state = {"plugins_enabled": ["huya_watch"], "settings": {
        "recording_enabled": False, "recording_replay_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), \
            patch.object(bili, "room_info", side_effect=AssertionError("误用 B 站")), \
            patch.object(bili, "play_url", side_effect=AssertionError("误用 B 站")), \
            patch("ddm.app.webbrowser.open") as browser:
        window = MainWindow([], [], state=state, layout_id="1x2")
        hp = window.plugins.platforms["huya"]
        played = []
        def capture(tile, address, *_args, **kwargs):
            played.append((tile, address, kwargs["headers"]))
            tile.set_live(True)
        try:
            record = plugins.RoomInfo(room_id="huya:660000", uname=parser.author,
                title=parser.title, live=True, platform="huya",
                extra={"playback_mode": "stream", "live_known": True})
            with patch.object(hp, "room_info", return_value=record), \
                    patch.object(hp, "play_url", return_value=(url, qn, profile, headers)), \
                    patch.object(window, "_play_on", side_effect=capture), \
                    patch.object(window, "refresh_status"), patch.object(window, "refresh_stats"):
                def accept_huya(dialog):
                    dialog.edit.setText("https://www.huya.com/660000")
                    dialog.accept()
                    return dialog.result()
                with patch.object(AddRoomDialog, "exec", accept_huya):
                    window.open_add_room()
                settle(app, lambda: bool(played))
                window._add_room_id("huya:660000")
                assert len(window.sidebar.rooms()) == 1
                item = window.sidebar.items()[0]
                assert item.badge.text() == "直播中"
                assert "加入画面墙" in [a.text() for a in item._context_menu().actions()]
                item.clicked.emit(item.room)
                target = next(t for t in window.wall.tiles if not t.room.get("room_id"))
                before = len(played)
                mime = QMimeData()
                mime.setData(ROOM_MIME, b"huya:660000")
                event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                target.dropEvent(event)
                settle(app, lambda: len(played) > before)
                assert event.isAccepted() and played[-1][0] is target
                assert played[-1][1:] == (url, headers)
                browser.assert_not_called()
                client = hp.danmaku_client("huya:660000", window)
                with patch.object(hp, "danmaku_client", return_value=client), patch.object(client, "start") as start:
                    window.start_danmaku("huya:660000")
                    assert window._danmaku is client and window._danmaku_room == "huya:660000"
                    start.assert_called_once()
                    window.stop_danmaku()
                    assert client._stopped.is_set() and window._danmaku is None
                window.hover_preview.on_hover(item.room)
                assert window.hover_preview._resolver is None
                saved_state = window.current_state()
            with patch("ddm.stream_relay.ffmpeg_path", return_value=""):
                window._play_on(target, url, qn, profile, headers=headers)
                assert "FFmpeg" in target.status_label.text(), "依赖缺失应在格子中提示"
                assert window.players[target]._relay is None
            with patch("ddm.app.StatsPoller") as stats_poller:
                window.refresh_stats()
                stats_poller.assert_not_called()
            with tempfile.TemporaryDirectory() as root, \
                    patch.object(config, "CONFIG_PATH", os.path.join(root, "config.json")), \
                    patch.dict(os.environ):
                os.environ.pop("DDM_NO_SAVE", None)
                config.save(saved_state)
                saved = config.load()
            sidebar, wall = config.build_rooms(saved)
            assert sidebar[0]["uname"] == parser.author
            assert sidebar[0]["playback_mode"] == "stream" and not sidebar[0]["live_known"]
            assert any(r.get("room_id") == "huya:660000" for r in wall)
            old = {"rooms": ["huya:660000"], "browser_rooms": {"huya:660000": {
                "platform": "huya", "playback_mode": "browser", "uname": "虎牙 · 660000"}}}
            assert config.build_rooms(old)[0][0]["playback_mode"] == "stream"
            saved["plugins_enabled"] = []
            disabled = MainWindow(sidebar, wall, state=saved)
            try:
                assert not disabled.sidebar.rooms()
                assert all(not tile.room.get("room_id") for tile in disabled.wall.tiles)
                assert not disabled._resolvers_running
                assert disabled.current_state()["platform_rooms"] == {}
                assert disabled.current_state()["suspended_platform_rooms"]["huya"]["rooms"]
            finally:
                disabled.close()
            print("PASS: dialog/drop-to-tile flow, no browser/Bili, save/restart, migration, disable")
        finally:
            window.close()
    app.processEvents()
    print("Huya tile playback selfcheck passed")


if __name__ == "__main__":
    main()
