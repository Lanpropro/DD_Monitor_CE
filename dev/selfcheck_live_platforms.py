"""离线自检：单插件三平台，房间信息/取流/图片/拖放/保存及统一禁用恢复。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili, config, images, plugins  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import AddRoomDialog  # noqa: E402
from ddm.widgets import ROOM_MIME  # noqa: E402

DOUYIN_CATEGORY_URL = (
    "https://live.douyin.com/categorynew/4_103?anchor_id=970201166524967&is_vs=0"
    "&live_web_rid=557481980778&vs_ep_group_id=&vs_episode_id=&vs_episode_stage=&vs_season_id="
)


def response(data=None, text="", content=b"FLV", url="https://cdn.test/live.flv"):
    result = Mock(text=text, url=url)
    result.json.return_value = data
    result.iter_content.return_value = iter([content])
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def dy_page(status=2, owner=True):
    anchor = {"nickname": "抖音测试", "avatar_thumb": {"url_list": ["https://p3.douyinpic.com/avatar.jpg"]}}
    room = {"status": status, "id_str": "internal-123", "title": "抖音标题",
            "cover": {"url_list": ["https://p11.douyinpic.com/cover.jpg"]}, "user_count_str": "99999",
            "stream_url": {"flv_pull_url": {"FULL_HD1": "https://cdn.test/source.flv"}}}
    if owner:
        room["owner"] = anchor
    state = {"state": {"roomStore": {"roomInfo": {"room": room, "anchor": anchor}}, "streamStore": {}}}
    return '<script>self.__pace_f.push([1,' + json.dumps("a:" + json.dumps([state])) + '])</script>'


def settle(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "后台线程未完成"


def main():
    app = QApplication.instance() or QApplication([])
    manager = plugins.PluginManager(enabled=["huya_watch"])
    manager.load()
    assert set(manager.platforms) == {"huya", "douyu", "douyin"}
    assert set(manager._platform_owner.values()) == {"huya_watch"}
    assert len(manager.plugins) == 1 and manager.plugins[0].name == "国内直播平台"
    module = sys.modules[type(manager.platforms["douyu"]).__module__]
    records = {}
    for kind in ("douyu", "douyin"):
        platform = manager.platforms[kind]
        urls = [f"{kind}:123", platform.room_url(f"{kind}:123") + "?from=share#test"]
        urls += [f"https://{host}/123/" for host in platform.hosts]
        for url in urls:
            assert platform.matches(url) and platform.normalize(url) == f"{kind}:123"
        assert not platform.matches("123")
        for url in (f"{kind}:", f"{kind}:../secret", f"{kind}:a/b", f"{kind}:１２３",
                    f"https://{platform.hosts[0]}.evil.test/123", f"https://user:pw@{platform.hosts[0]}/123",
                    f"https://{platform.hosts[0]}:1234/123", f"https://{platform.hosts[0]}/user/123"):
            try:
                platform.normalize(url)
            except ValueError:
                pass
            else:
                raise AssertionError(url)
        icon = QIcon(str(REPO / "assets" / "platforms" / (kind + ".ico")))
        assert not icon.isNull() and not icon.pixmap(20, 20).isNull()
        assert not platform._image_url("https://douyinpic.com.evil.test/evil.jpg")
        assert not platform._image_url("file:///avatar.jpg")
        assert not platform._image_url("https://user:pw@p3.douyinpic.com/avatar.jpg")
    douyu = manager.platforms["douyu"]
    room = {"room_id": 123, "show_status": 1, "videoLoop": 0, "nickname": "斗鱼测试", "room_name": "斗鱼标题",
            "owner_avatar": "//apic.douyucdn.cn/avatar.jpg", "room_pic": "https://rpic.douyucdn.cn/cover.avif/dy4",
            "online": 999999}
    with patch.object(module.requests, "get", return_value=response({"room": room})) as get, \
            patch.object(douyu, "_streams", side_effect=AssertionError("状态不能取流")):
        records["douyu"] = douyu.room_info("douyu:123").as_dict()
        assert records["douyu"]["live"] and records["douyu"]["uname"] == "斗鱼测试"
        assert records["douyu"]["face"] == "https://apic.douyucdn.cn/avatar.jpg"
        assert records["douyu"]["viewers"] == "" and "online" not in records["douyu"]
        assert get.call_args.kwargs["timeout"] == (4, 8)
        for update in ({"show_status": 2}, {"videoLoop": 1}):
            with patch.object(module.requests, "get", return_value=response({"room": dict(room, **update)})):
                assert not douyu.room_info("douyu:123").live
    douyin = manager.platforms["douyin"]
    assert manager.platform_for(DOUYIN_CATEGORY_URL) is douyin
    assert douyin.normalize(DOUYIN_CATEGORY_URL) == "douyin:557481980778"
    assert douyin.room_url(DOUYIN_CATEGORY_URL) == "https://live.douyin.com/557481980778"
    category_url = DOUYIN_CATEGORY_URL.replace("557481980778", "123")
    for url in (category_url, category_url.replace("live_web_rid=123", "live_web_rid=%31%32%33"),
                "https://live.douyin.com/123?live_web_rid=456"):
        assert douyin.normalize(url) == "douyin:123"
    invalid_links = ["https://live.douyin.com/categorynew/4_103?" + query for query in (
        "anchor_id=123", "live_web_rid=", "live_web_rid=abc", "live_web_rid=１２３",
        "live_web_rid=" + "1" * 21, "live_web_rid=123&live_web_rid=456",
        "live_web_rid=123&live_web_rid=")]
    invalid_links += [category_url.replace("live.douyin.com", host) for host in (
        "live.douyin.com.evil.test", "user:pw@live.douyin.com", "live.douyin.com:1234")]
    invalid_links += [category_url.replace("https:", "ftp:"),
                      category_url.replace("categorynew/4_103", "user/123")]
    for url in invalid_links:
        try:
            douyin.normalize(url)
        except ValueError:
            pass
        else:
            raise AssertionError(url)
    try:
        douyu.normalize("https://www.douyu.com/categorynew/4_103?live_web_rid=123")
    except ValueError:
        pass
    else:
        raise AssertionError("抖音分类页规则不能应用到斗鱼")
    with patch.object(module.requests, "get", return_value=response(text=dy_page())) as get, \
            patch.object(douyin, "_streams", side_effect=AssertionError("状态不能取流")):
        records["douyin"] = douyin.room_info(category_url).as_dict()
        assert records["douyin"]["room_id"] == "douyin:123"
        assert get.call_args.args[0] == "https://live.douyin.com/123"
        assert records["douyin"]["live"] and records["douyin"]["uname"] == "抖音测试"
        assert records["douyin"]["cover_url"] == "https://p11.douyinpic.com/cover.jpg"
        assert records["douyin"]["viewers"] == ""
        assert set(get.call_args.kwargs["cookies"]) == {"__ac_nonce"}
        assert get.call_args.kwargs["timeout"] == (4, 8)
    with patch.object(module.requests, "get", return_value=response(text=dy_page(4, False))):
        info = douyin.room_info("douyin:123")
        assert not info.live and info.uname == "抖音测试" and info.face
    for platform, result in ((douyu, response({"room": dict(room, show_status=None)})),
                             (douyin, response(text=dy_page(None))), (douyin, response(text="captcha"))):
        with patch.object(module.requests, "get", return_value=result):
            try:
                platform.rooms_status([platform.kind + ":123"])
            except RuntimeError:
                pass
            else:
                raise AssertionError("网络错误或坏数据不能误报下播")
    print("PASS: one plugin, official links/icons, live/offline metadata, avatars/covers, no audience counts")

    for kind in ("douyu", "douyin"):
        platform = manager.platforms[kind]
        session = SimpleNamespace(http=Mock(headers={"User-Agent": "test-agent"}))
        stream = Mock(to_url=Mock(return_value="https://cdn.test/live.flv"))
        with patch.object(module, "Streamlink", return_value=session), \
                patch.object(platform, "_streams", return_value={"best": stream}), \
                patch.object(session.http, "get", return_value=response()) as get:
            url, qn, profile, headers = platform.play_url(kind + ":123")
            assert (qn, profile) == (10000, kind) and headers["Referer"] == f"https://{platform.hosts[0]}/"
            if kind == "douyu":
                get.assert_not_called()         # 签名地址仅交给播放器一个消费者
            else:
                assert "cookies" not in get.call_args.kwargs
            session.http.close.assert_called_once()
        for streams, content in (({}, b"FLV"), ({"source": stream}, b"<ht")):
            if kind == "douyu" and streams:
                continue
            with patch.object(module, "Streamlink", return_value=session), \
                    patch.object(platform, "_streams", return_value=streams), \
                    patch.object(session.http, "get", return_value=response(content=content)):
                try:
                    platform.play_url(kind + ":123")
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("无流/无效媒体不可播放")
    session = module.Streamlink()
    with patch.object(douyu, "room_info", return_value=plugins.RoomInfo("douyu:123", live=True)), \
            patch.object(douyu, "_request_source", return_value={"rtmp_url": "https://cdn.test",
                "rtmp_live": "source.flv"}) as request:
        assert douyu._streams(session, "douyu:123")["source"].to_url() == "https://cdn.test/source.flv"
        assert request.call_args.args[1] == "123" and request.call_count == 1
    edge = {"rtmp_url": "https://stream.example.edgesrv.com", "rtmp_live": "source.flv",
            "cdnsWithName": [{"cdn": "scdn-test"}, {"cdn": "hw-h5"}]}
    backup = {"rtmp_url": "https://cdn.test", "rtmp_live": "stable.flv"}
    with patch.object(douyu, "room_info", return_value=plugins.RoomInfo("douyu:123", live=True)), \
            patch.object(douyu, "_request_source", side_effect=[edge, backup]) as request:
        assert douyu._streams(session, "douyu:123")["source"].to_url() == "https://cdn.test/stable.flv"
        assert request.call_args.args[1:] == ("123", "hw-h5") and request.call_count == 2
    parser = module.Douyu(session, "https://www.douyu.com/123")
    encryption = (12345, {"key": "key", "rand_str": "random", "enc_time": 1, "is_special": 0, "enc_data": "data"})
    with patch.object(parser, "_get_encryption", return_value=encryption), \
            patch.object(parser, "_compute_auth", return_value="auth"), \
            patch.object(session.http, "post", return_value=response({"error": 0, "data": backup})) as post:
        assert douyu._request_source(parser, "123", "hw-h5") == backup
        data = post.call_args.kwargs["data"]
        assert data["cdn"] == "hw-h5" and data["rate"] == "0" and data["hevc"] == "0"
    with patch.object(session.http, "get", return_value=response(text=dy_page())) as get:
        assert douyin._streams(session, category_url)["source"].to_url() == "https://cdn.test/source.flv"
        assert get.call_args.args[0] == "https://live.douyin.com/123"
    session.http.close()
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.red)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    with tempfile.TemporaryDirectory() as root, patch.object(images, "REPO", root), \
            patch.object(images.requests, "get", return_value=SimpleNamespace(status_code=200, content=bytes(buffer.data()))) as get:
        for kind, record in records.items():
            for key, folder in (("face", "avatars"), ("cover_url", "covers")):
                assert images.load_pixmap(record[key], folder) is not None
                assert get.call_args.kwargs["headers"]["Referer"] == f"https://{manager.platforms[kind].hosts[0]}/"
    print("PASS: source-only Douyu request, Streamlink Douyin, media validation, timeouts, headers and image cache")

    state = {"plugins_enabled": ["huya_watch"], "settings": {"recording_enabled": False,
             "recording_replay_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(bili, "room_info", side_effect=AssertionError("误用 B 站")), \
            patch.object(bili, "play_url", side_effect=AssertionError("误用 B 站")), \
            patch.object(images, "load_pixmap", return_value=pixmap), patch("ddm.app.webbrowser.open") as browser:
        window = MainWindow([], [], state=state, layout_id="2x2")
        try:
            played = []
            def capture(tile, address, _qn, profile, *_args, **kwargs):
                played.append((tile, profile, kwargs["headers"]))
                tile.set_live(True)
            with patch.object(window, "_play_on", side_effect=capture), \
                    patch.object(window, "refresh_status"), patch.object(window, "refresh_stats"):
                for kind in ("douyu", "douyin"):
                    platform = window.plugins.platforms[kind]
                    headers = {"Referer": f"https://{platform.hosts[0]}/"}
                    with patch.object(platform, "room_info", return_value=plugins.RoomInfo(**{
                            key: value for key, value in records[kind].items() if key not in ("playback_mode", "live_known")},
                            extra={"playback_mode": "stream", "live_known": True})), \
                            patch.object(platform, "play_url", return_value=("https://cdn.test/live.flv", 10000, kind, headers)):
                        def accept(dialog):
                            dialog.edit.setText(category_url if kind == "douyin" else platform.room_url(kind + ":123"))
                            dialog.accept()
                            return dialog.result()
                        with patch.object(AddRoomDialog, "exec", accept):
                            window.open_add_room()
                        settle(app, lambda: any(profile == kind for _, profile, _ in played))
                        item = next(item for item in window.sidebar.items() if item.room["room_id"] == kind + ":123")
                        assert item.badge.text() == "直播中"
                        target = window.wall.tiles[2]
                        mime = QMimeData()
                        mime.setData(ROOM_MIME, (kind + ":123").encode())
                        event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                        before = len(played)
                        target.dropEvent(event)
                        settle(app, lambda: len(played) > before)
                        assert event.isAccepted() and played[-1] == (target, kind, headers)
                assert all(not item.platform_badge.isHidden() for item in window.sidebar.items())
                window.sidebar.apply_pins(["douyin:123"])
                saved = window.current_state()
                with patch("ddm.app.StatsPoller") as stats:
                    MainWindow.refresh_stats(window)
                    stats.assert_not_called()
                browser.assert_not_called()
            window.plugins.enabled = set()
            window._sync_platform_rooms()
            hidden = window.current_state()
            assert not window.sidebar.rooms() and all(not tile.room.get("room_id") for tile in window.wall.tiles)
            assert set(hidden["suspended_platform_rooms"]) == {"douyu", "douyin"}
            hidden["plugins_enabled"] = ["huya_watch"]
            rooms, wall = config.build_rooms(hidden)
            restored = MainWindow(rooms, wall, state=hidden, layout_id="2x2")
            try:
                recovered = restored.current_state()
                for key in ("rooms", "wall", "pinned", "platform_rooms"):
                    assert recovered[key] == saved[key], (key, recovered[key], saved[key])
                assert not recovered["suspended_platform_rooms"]
            finally:
                restored.close()
        finally:
            window.close()
    app.processEvents()
    print("PASS: real add dialog/Qt drop into empty and occupied tiles, no browser/Bili, mixed icons, unified disable/restore")


if __name__ == "__main__":
    main()
