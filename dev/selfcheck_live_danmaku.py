"""离线验收：三平台协议、Qt 面板接入、取消/重连、换台与插件禁用。"""
import asyncio
import gzip
import json
import os
from pathlib import Path
import struct
import sys
import threading
import time
from unittest.mock import patch

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm import live_danmaku as dm, plugins  # noqa: E402


def tars_string(tag, value):
    data = value.encode()
    if len(data) < 256:
        return bytes([tag << 4 | 6, len(data)]) + data
    return bytes([tag << 4 | 7]) + struct.pack(">I", len(data)) + data


def huya_fixture(text="直播测试", name="测试用户"):
    sender = b"\x0a" + dm.tars_int(0, 1234567890123) + tars_string(2, name) + b"\x0b"
    notice = sender + dm.tars_int(1, 55) + dm.tars_int(2, 99) + tars_string(3, text)
    push = dm.tars_int(0, 0) + dm.tars_int(1, 1400) + dm.tars_bytes(2, notice)
    return dm.tars_int(0, 7) + dm.tars_bytes(1, push)


def douyin_fixture(method="WebcastChatMessage", text="直播测试", name="测试用户", compressed=True):
    user = dm.proto_field(3, name)
    chat = dm.proto_field(2, user) + dm.proto_field(5 if method == "WebcastEmojiChatMessage" else 3, text)
    message = dm.proto_field(1, method) + dm.proto_field(2, chat)
    response = dm.proto_field(1, message) + dm.proto_field(5, "seq:42") + dm.proto_field(9, 1)
    return dm.proto_field(2, 999) + dm.proto_field(8, gzip.compress(response) if compressed else response)


def check_protocols():
    assert dm.douyu_packet("type@=mrkl/").hex() == "1400000014000000b102000074797065403d6d726b6c2f00"
    packets = dm.douyu_packet("type@=chatmsg/nn@=甲@A乙/txt@=路径@S测试@A值/") * 2
    buffer = bytearray(packets[:9])
    assert dm.douyu_messages(buffer) == [] and len(buffer) == 9
    buffer.extend(packets[9:])
    messages = dm.douyu_messages(buffer)
    assert not buffer and len(messages) == 2
    assert messages[0]["nn"] == "甲@乙" and messages[0]["txt"] == "路径/测试@值"
    assert dm.tars_int(0, 0) == b"\x0c" and dm.tars_int(1, 256) == b"\x11\x01\x00"
    for value in (0, -1, 127, 128, -32769, 2 ** 40):
        assert dm.tars_fields(dm.tars_int(0, value))[0] == value
    assert dm.tars_fields(tars_string(3, "长文本" * 100))[3] == "长文本" * 100
    assert dm.huya_events(huya_fixture()) == (7, [{"kind": "danmaku", "uname": "测试用户", "text": "直播测试"}])
    assert dm.huya_events(dm.tars_int(0, 2) + dm.tars_bytes(1, b"\x0c")) == (2, [])
    assert dm.huya_events(dm.tars_int(0, 6)) == (6, [])
    # 未知 TARS 列表/字典、扩展标签仍能跳过，不能把频道号当昵称。
    assert dm.tars_fields(bytes.fromhex("0900020001000218000106036b6579160376616cf01003")) == {
        0: [1, 2], 1: ["key", "val"], 16: 3}
    for method in ("WebcastChatMessage", "WebcastEmojiChatMessage"):
        for compressed in (True, False):
            ready, events, ack = dm.douyin_events(douyin_fixture(method, compressed=compressed))
            assert ready and events == [{"kind": "danmaku", "uname": "测试用户", "text": "直播测试"}]
            assert ack == bytes.fromhex("10e7073a0361636b42067365713a3432")
    assert dm.douyin_events(douyin_fixture("WebcastRoomUserSeqMessage"))[1] == []
    assert dm.douyin_events(dm.proto_field(7, "hb")) == (False, [], None)
    assert dm.proto_fields(bytes.fromhex("08011201611201621901000000000000002d01000000")) == {
        1: [1], 2: [b"a", b"b"], 3: [b"\x01" + b"\0" * 7], 5: [b"\x01\0\0\0"]}
    malformed = [(dm.douyu_messages, bytearray(bytes.fromhex("0800000008000000b1020000"))),
                 (dm.tars_fields, b"\x0d\0\x00\x05x"), (dm.tars_fields, b"\x0a\x0c"),
                 (dm.proto_fields, b"\x08\x80"), (dm.proto_fields, b"\x12\x05x"),
                 (dm.proto_fields, b"\x00"), (dm.proto_fields, b"\x08" + b"\x80" * 11),
                 (dm.huya_events, dm.tars_int(0, 2) + dm.tars_bytes(1, b"\x00\x01")),
                 (dm.douyin_events, dm.proto_field(8, gzip.compress(b"x" * (dm.MAX_PACKET + 1))))]
    for decode, data in malformed:
        try:
            decode(data)
        except ValueError:
            pass
        else:
            raise AssertionError((decode.__name__, data[:12]))
    with patch.object(dm.random, "randrange", side_effect=[7, 12]):
        signature = dm.douyin_signature({"room_id": "123", "live_id": "1"})
    assert len(signature) == 16 and "=" not in signature
    print("PASS: STT fragmentation/escaping, nested TARS, Protobuf/gzip/ACK, emoji text, unknown events and malformed frames")


async def check_tcp(platform):
    received, statuses, sent = [], [], []
    done, closed = asyncio.Event(), asyncio.Event()
    client = platform.danmaku_client("douyu:123")
    client.message.connect(lambda e: (received.append(e), done.set()))
    client.status.connect(statuses.append)
    async def serve(reader, writer):
        buffer = bytearray()
        try:
            while chunk := await reader.read(4096):
                buffer.extend(chunk)
                for message in dm.douyu_messages(buffer):
                    sent.append(message)
                    if message["type"] == "loginreq":
                        assert statuses == []
                        packet = dm.douyu_packet("type@=loginres/error@=0/")
                        writer.write(packet[:5])
                        await writer.drain()
                        await asyncio.sleep(.01)
                        writer.write(packet[5:])
                    elif message["type"] == "joingroup":
                        writer.write(dm.douyu_packet("type@=chatmsg/nn@=用户/txt@=真实 TCP 分片测试/"))
                    await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    connect = asyncio.open_connection
    async def redirect(_host, _port):
        return await connect("127.0.0.1", server.sockets[0].getsockname()[1])
    try:
        with patch.object(dm.asyncio, "open_connection", redirect), \
                patch.object(platform, "room_info", return_value=plugins.RoomInfo("douyu:456")):
            task = asyncio.create_task(client._douyu())
            try:
                await asyncio.wait_for(done.wait(), 2)
                assert statuses == ["已连接"] and received[0]["text"] == "真实 TCP 分片测试"
                assert [x["type"] for x in sent] == ["loginreq", "mrkl", "joingroup"]
                assert sent[0]["roomid"] == "456" and sent[-1]["rid"] == "456" and sent[-1]["gid"] == "-9999"
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await asyncio.wait_for(closed.wait(), 1)
    finally:
        server.close()
        await server.wait_closed()
    print("PASS: real local TCP login/join/heartbeat, authenticated status, fragmented receive and cancel cleanup")


async def check_douyu_recovery(platform):
    sent, closed = [], asyncio.Event()
    rejected = False
    client = platform.danmaku_client("douyu:123")
    async def silent(reader, writer):
        buffer = bytearray()
        try:
            while chunk := await reader.read(4096):
                buffer.extend(chunk)
                for message in dm.douyu_messages(buffer):
                    sent.append(message["type"])
                    if message["type"] == "loginreq":
                        writer.write(dm.douyu_packet("type@=loginres/error@=0/"))
                        await writer.drain()
                    elif message["type"] == "joingroup" and rejected:
                        writer.write(dm.douyu_packet("type@=error/code@=1/"))
                        await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            closed.set()
    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    connect = asyncio.open_connection
    async def redirect(_host, _port):
        return await connect("127.0.0.1", server.sockets[0].getsockname()[1])
    try:
        with patch.object(dm.asyncio, "open_connection", redirect), \
                patch.object(platform, "room_info", return_value=plugins.RoomInfo("douyu:123")), \
                patch.object(dm, "DOUYU_HEARTBEAT", .04), \
                patch.object(dm, "DOUYU_RECEIVE_TIMEOUT", .18):
            try:
                await asyncio.wait_for(client._douyu(), .8)
            except ValueError as error:
                assert str(error) == "Douyu response timeout"
            else:
                raise AssertionError("Silent authenticated socket must reconnect")
            await asyncio.wait_for(closed.wait(), .5)
        assert sent.count("mrkl") >= 4 and "joingroup" in sent, sent
        rejected = True
        closed.clear()
        with patch.object(dm.asyncio, "open_connection", redirect), \
                patch.object(platform, "room_info", return_value=plugins.RoomInfo("douyu:123")):
            try:
                await asyncio.wait_for(client._douyu(), .8)
            except ValueError as error:
                assert str(error) == "Douyu server rejected subscription"
            else:
                raise AssertionError("Rejected subscription must reconnect without waiting for silence timeout")
            await asyncio.wait_for(closed.wait(), .5)
    finally:
        server.close()
        await server.wait_closed()

    client = platform.danmaku_client("douyu:123")
    attempts, waits = [], []
    async def disconnect(retries):
        attempts.append(retries)
        client._connected = True
        if len(attempts) == 4:
            client._stopped.set()
        raise OSError("Remote closed after successful subscription")
    async def sleep(delay):
        waits.append(delay)
    with patch.object(client, "_douyu", disconnect), patch.object(dm.asyncio, "sleep", sleep):
        await client._main()
    assert attempts == [0, 1, 2, 3] and waits == [1, 1, 1], (attempts, waits)
    print("PASS: Douyu heartbeat deadline, silent/rejected socket recovery, reset backoff after successful subscriptions")


async def check_websocket(platform, *, mapped=False):
    kind = platform.kind
    client = platform.danmaku_client(kind + ":123")
    received, statuses, sent = [], [], []
    if mapped:
        platform.restore_follow_rooms([{"room_id": "douyin:123", "anchor_uid": "101"}])
    done, ack_done, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    client.message.connect(lambda event: (received.append(event), done.set()))
    client.status.connect(statuses.append)
    async def room_page(_request):
        assert not mapped, "Mapped anchor fell back to captcha page"
        if kind == "huya":
            page = 'var TT_ROOM_DATA = {"id":1234567890123};'
        else:
            state = {"state": {"roomStore": {"roomInfo": {"room": {"status": 2,
                "id_str": "987654321"}}}, "streamStore": {}}}
            page = '<script>self.__pace_f.push([1,' + json.dumps("a:" + json.dumps([state])) + '])</script>'
        response = web.Response(text=page)
        response.set_cookie("ttwid", "fixture-visitor")
        return response
    async def lookup(_request):
        return web.json_response({"status_code": 0, "data": {"id_str": "987654321", "owner_user_id": 101}})
    async def share(_request):
        room = {"idStr": "987654321", "status": 2, "owner": {"idStr": "101", "webRid": "123"}}
        chunk = "5:" + json.dumps(["$", "$L7", None, {"data": {"room": room}}])
        response = web.Response(text='<script>self.__rsc_f.push([1,' + json.dumps(chunk) + '])</script>')
        response.set_cookie("ttwid", "fixture-visitor")
        return response
    async def socket(request):
        assert request.headers["Origin"] == ("https://www.huya.com" if kind == "huya" else "https://live.douyin.com")
        assert request.headers["Referer"] == platform.room_url(client.room_id)
        if kind == "douyin":
            assert request.cookies["ttwid"] == "fixture-visitor"
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            assert statuses == [], "WebSocket 握手不等于订阅成功"
            if kind == "huya":
                registration = dm.tars_fields((await ws.receive()).data)
                assert registration[0] == 1
                user = dm.tars_fields(registration[1])
                assert user[0] == user[6] == 1234567890123 and user[7] == 3
                await ws.send_bytes(dm.tars_int(0, 2) + dm.tars_bytes(1, b"\x0c"))
                await ws.send_bytes(huya_fixture())
            else:
                await ws.send_bytes(douyin_fixture())
            async for packet in ws:
                if packet.type == aiohttp.WSMsgType.BINARY:
                    sent.append(packet.data)
                    if kind == "douyin" and dm.proto_first(dm.proto_fields(packet.data), 7) == b"ack":
                        ack_done.set()
        finally:
            closed.set()
        return ws
    application = web.Application()
    application.router.add_get("/room", room_page)
    application.router.add_get("/lookup", lookup)
    application.router.add_get("/share", share)
    application.router.add_get("/ws", socket)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    try:
        async with aiohttp.ClientSession() as session:
            get, connect = session.get, session.ws_connect
            def redirect_page(url, **kwargs):
                if mapped:
                    if url.endswith("/webcast/room/info_by_user/"):
                        assert kwargs["params"]["user_id"] == "101"
                        return get(base + "/lookup", **kwargs)
                    assert url == "https://webcast.amemv.com/webcast/reflow/987654321"
                    return get(base + "/share", **kwargs)
                assert url == platform.room_url(client.room_id)
                if kind == "douyin":
                    assert set(kwargs["cookies"]) == {"__ac_nonce"}
                return get(base + "/room", **kwargs)
            def redirect_ws(url, **kwargs):
                if kind == "douyin":
                    from urllib.parse import parse_qs, urlsplit
                    query = parse_qs(urlsplit(url).query)
                    assert query["room_id"] == ["987654321"] and query["signature"]
                    assert query["enter_from"] == ["web_live"]
                return connect(base.replace("http:", "ws:") + "/ws", **kwargs)
            with patch.object(session, "get", redirect_page), patch.object(session, "ws_connect", redirect_ws):
                task = asyncio.create_task(client._websocket(session, 0))
                try:
                    await asyncio.wait_for(done.wait(), 2)
                    assert statuses == ["已连接"] and received[0]["text"] == "直播测试"
                    if kind == "douyin":
                        await asyncio.wait_for(ack_done.wait(), 1)
                        assert dm.proto_field(7, "hb") in sent
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                await asyncio.wait_for(closed.wait(), 1)
    finally:
        await runner.cleanup()
    print(f"PASS: {kind} real local WebSocket, official headers/room IDs, subscription/ACK, heartbeat and cancellation")


class FakeClient(QThread):
    message = Signal(dict)
    status = Signal(str)
    def __init__(self, room_id, parent=None):
        super().__init__(parent)
        self.room_id, self.stopped = room_id, False
    def start(self):
        self.status.emit("已连接")
    def stop(self):
        self.stopped = True


def check_window(app):
    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state={"plugins_enabled": ["domestic_live"], "settings": {
            "recording_enabled": False, "recording_replay_enabled": False}}, layout_id="dm_pair")
    clients = []
    try:
        panel, tile = window.wall.danmaku, window.wall.tiles[0]
        for kind in ("huya", "douyu", "douyin"):
            previous = window._danmaku
            platform = window.plugins.platforms[kind]
            client = FakeClient(kind + ":123", window)
            clients.append(client)
            with patch.object(platform, "danmaku_client", return_value=client) as factory:
                tile.set_room({"room_id": kind + ":123", "uname": kind, "platform": kind, "live": True})
                window.sync_danmaku()
                window.sync_danmaku()
                factory.assert_called_once_with(kind + ":123", window)
            assert window._danmaku is client and panel.count.text() == "已连接"
            if previous:
                assert previous.stopped
                previous.message.emit({"text": "旧直播间消息", "uname": "旧用户"})
                previous.status.emit("旧连接状态")
                assert "旧直播间消息" not in panel.body.toPlainText() and panel.count.text() == "已连接"
            window.settings["danmaku_block_words"] = ["广告"]
            client.message.emit({"kind": "danmaku", "uname": "平台用户", "text": kind + " 正常消息"})
            client.message.emit({"kind": "danmaku", "uname": "平台用户", "text": "广告"})
            assert kind + " 正常消息" in panel.body.toPlainText() and "广告" not in panel.body.toPlainText()
        window.show()
        window.resize(520, 1000)
        app.processEvents()
        assert window.sidebar.side == "top" and window._danmaku is clients[-1]
        clients[-1].message.emit({"kind": "danmaku", "uname": "竖屏", "text": "竖屏弹幕"})
        assert "竖屏弹幕" in panel.body.toPlainText()
        window.plugins.enabled = set()
        window._sync_platform_rooms()
        assert clients[-1].stopped and window._danmaku is None
        window.wall.set_layout("2x2")
        window.sync_danmaku()
        assert window._danmaku is None
        window.plugins.enabled = {"domestic_live"}
        window._sync_platform_rooms()
        assert window._danmaku is None
        # 第三方平台未实现可选接口时，继续显示原来的暂不支持提示。
        assert plugins.Platform().danmaku_client("unknown:1") is None
        window.start_danmaku("unknown:1")
        assert panel.count.text() == "暂不支持" and window._danmaku is None
        with patch("ddm.app.DanmakuClient", return_value=FakeClient("123", window)) as bili_factory:
            window.start_danmaku("123")
            bili_factory.assert_called_once_with("123", window)
        window.stop_danmaku()
    finally:
        window.close()
    print("PASS: Qt three-platform panel, block words, portrait layout, old-signal isolation, disable, Bili compatibility")


def check_cancel(app, manager):
    platform = manager.platforms["douyin"]
    # HTTP 准备、长连接、重连等待都必须能从 UI 线程及时取消。
    for mode in ("setup", "connected", "reconnect"):
        client = platform.danmaku_client("douyin:123")
        entered = threading.Event()
        async def blocked(_session, _retries):
            entered.set()
            if mode == "reconnect":
                raise OSError("Disconnected")
            await asyncio.Event().wait()
        statuses = []
        client.status.connect(statuses.append)
        with patch.object(client, "_websocket", blocked):
            client.start()
            assert entered.wait(1)
            time.sleep(.03)
            client.stop()
            assert client.wait(500) and client._loop is None and client._task is None
        app.processEvents()
        assert not any("出错" in status for status in statuses)
    # 分享资料尚未响应时，直接取消 HTTP，不等待网络超时。
    client = platform.danmaku_client("douyin:123")
    entered = threading.Event()
    class PendingResponse:
        async def __aenter__(self):
            entered.set()
            await asyncio.Event().wait()
        async def __aexit__(self, *_args):
            return False
    with patch.object(aiohttp.ClientSession, "get", return_value=PendingResponse()):
        client.start()
        assert entered.wait(1)
        client.stop()
        assert client.wait(500) and client._loop is None and client._task is None
    client = platform.danmaku_client("douyin:123")
    client.stop()
    with patch.object(client, "_websocket", side_effect=AssertionError("停止后不能启动网络")):
        client.start()
        assert client.wait(500)
    print("PASS: cancel during setup/receive/retry and before thread start; no surviving async tasks")


def check_window_cleanup():
    for action in ("close", "disable", "layout"):
        with patch("ddm.app.QTimer.singleShot"):
            window = MainWindow([], [], state={"plugins_enabled": ["domestic_live"], "settings": {
                "recording_enabled": False, "recording_replay_enabled": False}}, layout_id="dm_pair")
        entered = threading.Event()
        async def blocked(_client, _session, _retries):
            entered.set()
            await asyncio.Event().wait()
        try:
            with patch.object(dm.LiveDanmakuClient, "_websocket", blocked):
                window.wall.tiles[0].set_room({"room_id": "douyin:123", "platform": "douyin", "live": True})
                window.sync_danmaku()
                client = window._danmaku
                assert entered.wait(1) and client.isRunning()
                if action == "close":
                    window.close()
                elif action == "disable":
                    window.plugins.enabled = set()
                    window._sync_platform_rooms()
                else:
                    window.wall.set_layout("2x2")
                    window.sync_danmaku()
                assert window._danmaku is None and client.wait(500)
                assert client._stopped.is_set() and client._task is None and client._loop is None
        finally:
            window.close()
    print("PASS: real QThread cleanup through window close, plugin disable and ordinary layout")


def main():
    app = QApplication([])
    manager = plugins.PluginManager(enabled=["domestic_live"])
    manager.load()
    check_protocols()
    asyncio.run(check_tcp(manager.platforms["douyu"]))
    asyncio.run(check_douyu_recovery(manager.platforms["douyu"]))
    for kind in ("huya", "douyin"):
        asyncio.run(check_websocket(manager.platforms[kind]))
        if kind == "douyin":
            asyncio.run(check_websocket(manager.platforms[kind], mapped=True))
    check_cancel(app, manager)
    check_window(app)
    check_window_cleanup()


if __name__ == "__main__":
    main()
