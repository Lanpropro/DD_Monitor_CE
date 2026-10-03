"""离线验收：独立海外插件、链接/元数据/画质、图片、Qt 拖放、暂存和聊天。"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QDropEvent, QIcon, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from streamlink.stream.hls import HLSStream  # noqa: E402
from streamlink.stream.hls.m3u8 import parse_m3u8  # noqa: E402
from ddm import bili, config, global_danmaku as dm, images, plugins  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import AddRoomDialog  # noqa: E402
from ddm.widgets import ROOM_MIME  # noqa: E402
from ddm.auto_quality import AUTO_QUALITY  # noqa: E402
from selfcheck_live_danmaku import FakeClient  # noqa: E402
from selfcheck_live_platforms import response, settle  # noqa: E402

VIDEO = "AbCd_123-45"
CHANNEL = "UC" + "a" * 22
ROOMS = ("twitch:test", "youtube:@测试频道")


def youtube_page(live=True, is_live_content=True, chat=True):
    details = {"videoId": VIDEO, "author": "YouTube 测试", "channelId": CHANNEL,
        "title": "测试直播 }; Unicode 🎃", "isLive": live, "isLiveContent": is_live_content,
        "thumbnail": {"thumbnails": [{"url": "https://i.ytimg.com/cover.jpg", "width": 640}]}}
    data = {"owner": {"videoOwnerRenderer": {"navigationEndpoint": {"browseEndpoint": {"browseId": CHANNEL}},
        "thumbnail": {"thumbnails": [{"url": "https://yt3.ggpht.com/avatar.jpg", "width": 100}]}}}}
    if chat:
        data["liveChatRenderer"] = {"continuations": [{"reloadContinuationData": {"continuation": "watch-seed"}}],
            "header": {"sortFilterSubMenuRenderer": {"subMenuItems": [
                {"continuation": {"reloadContinuationData": {"continuation": "ui-only-token"}}}]}}}
    cfg = {"INNERTUBE_CONTEXT": {"client": {"clientName": "WEB", "clientVersion": "test", "visitorData": "public-visitor"}}}
    return "ytInitialPlayerResponse = " + json.dumps({"videoDetails": details}) + ";" + \
        "ytInitialData = " + json.dumps(data) + ";ytcfg.set(" + json.dumps(cfg) + ");ytcfg.set({x: window.x});"


def check_metadata(manager):
    module = sys.modules[type(manager.platforms["twitch"]).__module__]
    twitch, youtube = manager.platforms["twitch"], manager.platforms["youtube"]
    for link in ("https://www.twitch.tv/Test?foo=1", "https://m.twitch.tv/test/", "twitch:TEST",
                 "https://player.twitch.tv/?channel=Test"):
        assert twitch.normalize(link) == ROOMS[0]
    for link, raw in (("https://youtu.be/" + VIDEO, VIDEO),
            ("https://www.youtube.com/watch?v=" + VIDEO, VIDEO),
            ("https://www.youtube.com/watch?v=eKP_QB_H7F8", "eKP_QB_H7F8"),
            ("https://www.youtube.com/live/" + VIDEO, VIDEO),
            ("https://www.youtube.com/embed/" + VIDEO, VIDEO),
            ("https://www.youtube.com/shorts/" + VIDEO, VIDEO),
            ("https://www.youtube.com/channel/" + CHANNEL + "/live", CHANNEL),
            ("https://www.youtube.com/@测试频道/streams", "@测试频道")):
        assert youtube.normalize(link) == "youtube:" + raw
    invalid = {
        "twitch": ["https://twitch.tv/videos/123", "https://player.twitch.tv/?channel=a&channel=b",
                   "https://twitch.tv/directory", "twitch:../test"],
        "youtube": ["https://youtube.com/watch?v=" + VIDEO + "&v=" + VIDEO,
                    "https://youtube.com/channel/" + VIDEO, "youtube:@bad/name", "youtube:bad"]}
    for kind, platform in manager.platforms.items():
        invalid[kind] += [f"https://{platform.hosts[0]}.evil.test/test", f"https://u:p@{platform.hosts[0]}/test",
                          f"https://{platform.hosts[0]}:444/test", f"ftp://{platform.hosts[0]}/test"]
        for link in invalid[kind]:
            try:
                platform.normalize(link)
            except ValueError:
                pass
            else:
                raise AssertionError(link)
        assert not platform.matches("123")
        icon = QIcon(str(REPO / "assets/platforms" / (kind + ".ico")))
        assert not icon.pixmap(20, 20).isNull()
    assert youtube.room_url(ROOMS[1]).endswith("/live")
    with patch.object(module.requests, "get", side_effect=[module.requests.ConnectionError(), response()]) as get:
        assert module.public_request("get", "https://www.youtube.com", timeout=(4, 8))
        assert get.call_count == 2
    user = {"displayName": "Twitch 测试", "profileImageURL": "https://static-cdn.jtvnw.net/face.jpg",
            "lastBroadcast": {"title": "直播标题"}, "stream": {"type": "live", "previewImageURL": "https://static-cdn.jtvnw.net/cover.jpg"}}
    records = {}
    with patch.object(module.requests, "post", return_value=response({"data": {"user": user}})) as post:
        records["twitch"] = twitch.room_info(ROOMS[0]).as_dict()
        assert "viewersCount" not in post.call_args.kwargs["json"]["query"]
        assert post.call_args.kwargs["timeout"] == (4, 8)
        assert records["twitch"]["live"] and records["twitch"]["face"]
    with patch.object(module.requests, "post", return_value=response({"data": {"user": dict(user, stream=None)}})):
        assert not twitch.room_info(ROOMS[0]).live
    with patch.object(module.requests, "get", return_value=response(text=youtube_page())):
        records["youtube"] = youtube.room_info(ROOMS[1]).as_dict()
        assert records["youtube"]["live"] and records["youtube"]["face"] and records["youtube"]["cover_url"]
    with patch.object(module.requests, "get", return_value=response(text=youtube_page(False))):
        assert not youtube.room_info(ROOMS[1]).live
    # 用户的赛事链接：结束后的 videoDetails 不再带 isLive，仍有直播时间和回放标识。
    ended = dm.page_json(youtube_page(False), "ytInitialPlayerResponse")
    ended["videoDetails"].pop("isLive")
    ended["videoDetails"]["videoId"] = "eKP_QB_H7F8"
    ended["microformat"] = {"playerMicroformatRenderer": {"liveBroadcastDetails": {
        "isLiveNow": False, "startTimestamp": "2026-10-02T08:30:48+00:00",
        "endTimestamp": "2026-10-02T13:45:26+00:00"}}}
    ended_page = "ytInitialPlayerResponse = " + json.dumps(ended) + ";" + youtube_page().split(";", 1)[1]
    with patch.object(module.requests, "get", return_value=response(text=ended_page)):
        info = youtube.room_info("https://www.youtube.com/watch?v=eKP_QB_H7F8")
        assert info.room_id == "youtube:eKP_QB_H7F8" and not info.live and info.cover_url
    now_live = json.loads(json.dumps(ended))
    now_live["videoDetails"].pop("isLiveContent")
    now_live["microformat"]["playerMicroformatRenderer"]["liveBroadcastDetails"]["isLiveNow"] = True
    fallback = "ytInitialPlayerResponse = " + json.dumps(now_live) + ";" + youtube_page().split(";", 1)[1]
    with patch.object(module.requests, "get", return_value=response(text=fallback)):
        assert youtube.room_info("youtube:eKP_QB_H7F8").live
    offline = 'ytInitialData = ' + json.dumps({"channelMetadataRenderer": {"title": "离线频道"}})
    with patch.object(module.requests, "get", return_value=response(text=offline)):
        assert not youtube.room_info(ROOMS[1]).live
    for platform, method, payload in ((twitch, "post", response({"data": {"user": None}})),
            (twitch, "post", response({"errors": [{"message": "failure"}]})),
            (youtube, "get", response(text="captcha")),
            (youtube, "get", response(text=youtube_page(is_live_content=False)))):
        with patch.object(module.requests, method, return_value=payload):
            try:
                platform.rooms_status([ROOMS[0] if platform is twitch else ROOMS[1]])
            except RuntimeError:
                pass
            else:
                raise AssertionError("Invalid metadata/VOD must not become an offline live room")
    assert all(record["viewers"] == "" for record in records.values())
    session = module.Streamlink()
    parser = module.LiveYouTube(session, youtube.room_url(ROOMS[1]))
    with patch.object(module.YouTube, "_get_res", return_value=response(text=youtube_page())):
        assert parser._get_res(parser.url).text
    with patch.object(module.YouTube, "_get_res", return_value=response(text=fallback)):
        assert parser._get_res(parser.url).text
    for page in (youtube_page(False), youtube_page(False, False), "captcha"):
        with patch.object(module.YouTube, "_get_res", return_value=response(text=page)):
            try:
                parser._get_res(parser.url)
            except ValueError:
                pass
            else:
                raise AssertionError("Never relay a VOD/offline/challenge response")
    session.http.close()
    assert not module.image_url("https://ytimg.com.evil.test/a.jpg", youtube.image_hosts)
    assert not module.image_url("file:///avatar.png", youtube.image_hosts)
    print("PASS: independent plugin, strict official links, handles/channel IDs, live/offline, no VOD/audience")
    return records


def check_quality(manager):
    module = sys.modules[type(manager.platforms["twitch"]).__module__]
    session = module.Streamlink()
    playlist = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=4000000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=1080x1920,FRAME-RATE=60
https://cdn.test/high.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=900000,CODECS="avc1.640028,mp4a.40.2",RESOLUTION=360x640,FRAME-RATE=30
https://cdn.test/low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=9000000,CODECS="hvc1.1.6.L120,mp4a.40.2",RESOLUTION=2160x3840
https://cdn.test/hevc.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=100000,CODECS="mp4a.40.2"
https://cdn.test/audio.m3u8
"""
    master = parse_m3u8(playlist, base_uri="https://cdn.test/master.m3u8")
    streams = {key: HLSStream(session, f"https://cdn.test/{key}.m3u8", multivariant=master)
               for key in ("high", "low", "hevc", "audio")}
    streams.update(best=streams["high"], worst=streams["low"])
    for kind, platform in manager.platforms.items():
        rid = ROOMS[0] if kind == "twitch" else ROOMS[1]
        with patch.object(module, "Streamlink", return_value=session), \
                patch.object(platform, "room_info", return_value=plugins.RoomInfo(rid, live=True)), \
                patch.object(platform.parser, "streams", return_value=streams):
            assert platform.play_url(rid)[0].endswith("high.m3u8")
            options = platform.room_quality_options(rid)
            assert len(options) == 3 and options[0]["qn"] == AUTO_QUALITY and options[1]["qn"] == 10000
            assert "1080x1920" in options[1]["desc"] and "60fps" in options[1]["desc"]
            assert options[1]["bandwidth"] == 4000000
            assert platform.play_url(rid, options[2]["qn"])[0].endswith("low.m3u8")
            assert platform.play_url(rid, AUTO_QUALITY)[1] == options[2]["qn"]
            assert platform.preview_url(rid)[1] == options[2]["qn"]
            assert platform.play_url(rid, 80)[1] == 10000
            assert "m3u8" not in json.dumps(platform._qualities)
    session.http.close()
    print("PASS: true portrait sizes/fps, stable native quality IDs, H.264 video only, isolated low preview")


async def check_protocol(platform):
    kind = platform.kind
    client = platform.danmaku_client(ROOMS[0] if kind == "twitch" else ROOMS[1])
    events, statuses, commands = [], [], []
    client.message.connect(events.append)
    client.status.connect(statuses.append)
    done, closed = asyncio.Event(), asyncio.Event()
    count = 0
    async def socket(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            async for packet in ws:
                commands.append(packet.data)
                if packet.data.startswith("NICK "):
                    await ws.send_str(":server 001 justinfan :Welcome\r\n")
                elif packet.data.startswith("JOIN #test"):
                    await ws.send_str(":server 366 justinfan #test :joined\r\nPING :server\r\n")
                    message = "@id=abc;display-name=Test\\sName :test!test@host PRIVMSG #test :你好 Kappa 🎃\r\n"
                    await ws.send_str(message[:20])
                    await ws.send_str(message[20:] + message + ":wrong!x@x PRIVMSG #other :ignore\r\n")
                elif packet.data.startswith("PONG :server"):
                    done.set()
        finally:
            closed.set()
        return ws
    async def page(request):
        return web.Response(text=youtube_page())
    async def poll(request):
        nonlocal count
        body = await request.json()
        assert body["context"]["client"]["visitorData"] == "public-visitor"
        assert request.headers["X-Goog-Visitor-Id"] == "public-visitor"
        assert body["continuation"] == ("watch-seed" if count == 0 else "all-chat" if count == 1 else "next-token")
        count += 1
        item = {"id": "message-id", "authorName": {"simpleText": "YT User"},
                "message": {"runs": [{"text": "你好 "}, {"emoji": {"shortcuts": [":smile:"]}}]}}
        data = {"actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": item}}}],
                "continuations": [{"timedContinuationData": {"continuation": "next-token", "timeoutMs": 500}}]}
        if count == 1:
            data["header"] = {"sortFilterSubMenuRenderer": {"subMenuItems": [{}, {
                "continuation": {"reloadContinuationData": {"continuation": "all-chat"}}}]}}
        if count >= 2:
            done.set()
        return web.json_response({"continuationContents": {"liveChatContinuation": data}})
    application = web.Application()
    application.router.add_get("/ws", socket)
    application.router.add_get("/page", page)
    application.router.add_post("/poll", poll)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    try:
        async with aiohttp.ClientSession() as session:
            get, post, connect = session.get, session.post, session.ws_connect
            def redirect_get(url, **kwargs):
                return get(base + "/page", **kwargs)
            def redirect_post(url, **kwargs):
                return post(base + "/poll", **kwargs)
            def redirect_ws(url, **kwargs):
                return connect(base.replace("http:", "ws:") + "/ws", **kwargs)
            with patch.object(dm, "request_proxy", return_value=None), patch.object(session, "get", redirect_get), \
                    patch.object(session, "post", redirect_post), patch.object(session, "ws_connect", redirect_ws):
                task = asyncio.create_task(client._websocket(session, 0))
                try:
                    await asyncio.wait_for(done.wait(), 3)
                    await asyncio.sleep(.03)
                    assert statuses == ["已连接"] and len(events) == 1, (statuses, events)
                    assert events[0]["text"] == ("你好 Kappa 🎃" if kind == "twitch" else "你好 :smile:")
                    if kind == "twitch":
                        assert events[0]["uname"] == "Test Name"
                        assert not any(command.startswith("PRIVMSG") for command in commands)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if kind == "twitch":
                    await asyncio.wait_for(closed.wait(), 1)
    finally:
        await runner.cleanup()
    print(f"PASS: {kind} local network protocol, Unicode/emotes, duplicate IDs, readiness and cancellation")


def check_window(app, records):
    state = {"plugins_enabled": ["global_live"], "settings": {"recording_enabled": False,
        "recording_replay_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(bili, "play_url", side_effect=AssertionError("Bili called")), \
            patch("ddm.app.webbrowser.open", side_effect=AssertionError("Browser shortcut")):
        window = MainWindow([], [], state=state, layout_id="dm_pair")
        clients = []
        try:
            played = []
            def capture(tile, address, qn, profile, *args, **kwargs):
                played.append((tile, profile))
                tile.set_quality_options(window.plugins.platforms[profile].room_quality_options(tile.room["room_id"]))
            with patch.object(window, "_play_on", side_effect=capture), patch.object(window, "refresh_status"), \
                    patch.object(window, "refresh_stats"):
                for kind, record in records.items():
                    rid = record["room_id"]
                    platform = window.plugins.platforms[kind]
                    client = FakeClient(rid, window)
                    clients.append(client)
                    info = plugins.RoomInfo(**{key: value for key, value in record.items() if key not in ("playback_mode", "live_known")},
                                            extra={"playback_mode": "stream", "live_known": True})
                    with patch.object(platform, "room_info", return_value=info), \
                            patch.object(platform, "play_url", return_value=("https://cdn.test/live.m3u8", 10000, kind, {})), \
                            patch.object(platform, "danmaku_client", return_value=client):
                        def accept(dialog):
                            dialog.edit.setText(platform.room_url(rid))
                            dialog.accept()
                            return dialog.result()
                        with patch.object(AddRoomDialog, "exec", accept):
                            window.open_add_room()
                        settle(app, lambda: any(profile == kind for _, profile in played))
                        item = next(item for item in window.sidebar.items() if item.room["room_id"] == rid)
                        assert item.badge.text() == "直播中" and not item.platform_badge.text()
                        if kind == "twitch":
                            assert item.platform_badge.isHidden()
                        target = window.wall.tiles[0]
                        mime = QMimeData()
                        mime.setData(ROOM_MIME, rid.encode())
                        drop = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
                        before = len(played)
                        target.dropEvent(drop)
                        settle(app, lambda: len(played) > before)
                        assert drop.isAccepted() and played[-1] == (target, kind)
                        window.sync_danmaku()
                        window.settings["danmaku_block_words"] = ["广告"]
                        client.message.emit({"kind": "danmaku", "uname": "User", "text": "直播聊天"})
                        client.message.emit({"kind": "danmaku", "uname": "User", "text": "广告"})
                        assert "直播聊天" in window.wall.danmaku.body.toPlainText()
                        assert "广告" not in window.wall.danmaku.body.toPlainText()
                assert clients[0].stopped
                assert all(not item.platform_badge.isHidden() for item in window.sidebar.items())
                window.show()
                window.resize(520, 900)
                app.processEvents()
                assert window.sidebar.side == "top"
                window.sidebar.apply_pins([ROOMS[1]])
                saved = window.current_state()
                with patch("ddm.app.StatsPoller") as stats:
                    MainWindow.refresh_stats(window)
                    stats.assert_not_called()
            window.plugins.enabled = set()
            window._sync_platform_rooms()
            hidden = window.current_state()
            assert not window.sidebar.rooms() and all(not tile.room.get("room_id") for tile in window.wall.tiles)
            assert window._danmaku is None and clients[-1].stopped
            assert set(hidden["suspended_platform_rooms"]) == {"twitch", "youtube"}
            hidden["plugins_enabled"] = ["global_live"]
            rooms, wall = config.build_rooms(hidden)
            with patch("ddm.app.MainWindow.sync_danmaku"):
                restored = MainWindow(rooms, wall, state=hidden, layout_id="dm_pair")
            try:
                recovered = restored.current_state()
                for key in ("rooms", "wall", "pinned", "platform_rooms"):
                    assert recovered[key] == saved[key], (key, recovered[key], saved[key])
                assert not recovered["suspended_platform_rooms"]
            finally:
                restored.close()
        finally:
            window.close()
    print("PASS: real Qt add/drop, icon-only badges, portrait, chat/block words, no audience/browser, suspend/restore")


def main():
    app = QApplication([])
    manager = plugins.PluginManager(enabled=["global_live"])
    manager.load()
    assert set(manager.platforms) == {"twitch", "youtube"}
    assert set(manager._platform_owner.values()) == {"global_live"} and len(manager.plugins) == 1
    records = check_metadata(manager)
    check_quality(manager)
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.red)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    with tempfile.TemporaryDirectory() as root, patch.object(images, "REPO", root), \
            patch.object(images.requests, "get", return_value=Mock(status_code=200, content=bytes(buffer.data()))) as get:
        for record in records.values():
            for key, directory in (("face", "avatars"), ("cover_url", "covers")):
                assert not images._load_one(record[key], directory).isNull()
                assert get.call_args.kwargs["headers"]["Referer"] == manager.platforms[record["platform"]].origin
    for platform in manager.platforms.values():
        asyncio.run(check_protocol(platform))
        for mode in ("setup", "reconnect"):
            client = platform.danmaku_client(ROOMS[0] if platform.kind == "twitch" else ROOMS[1])
            entered = threading.Event()
            async def blocked(session, retries):
                entered.set()
                if mode == "reconnect":
                    raise OSError("Disconnected")
                await asyncio.Event().wait()
            with patch.object(client, "_websocket", blocked):
                client.start()
                assert entered.wait(1)
                time.sleep(.02)
                client.stop()
                assert client.wait(500) and client._task is None and client._loop is None
    check_window(app, records)
    app.processEvents()
    print("PASS: overseas plugin checks complete")


if __name__ == "__main__":
    main()
