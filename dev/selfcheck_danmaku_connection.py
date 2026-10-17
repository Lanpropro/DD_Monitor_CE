"""Offline regression: shared browser identity, signed auth and reconnect recovery."""
import asyncio
import http.cookies
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiohttp
from aiohttp import web
from ddm import bili
from ddm.danmaku import _Client
from blivedm.clients import ws_base


class Socket:
    closed = False

    def __init__(self):
        self.packets = []

    async def send_bytes(self, packet):
        head = ws_base.HEADER_STRUCT.unpack_from(packet)
        self.packets.append((head[3], json.loads(packet[head[1]:head[0]])))


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in ("SESSION_DATA", "BILI_JCT", "BUVID3"):
            cache = patch.object(bili, name, "", create=True)
            cache.start()
            self.addCleanup(cache.stop)
        self.session = aiohttp.ClientSession(headers=bili.HEADERS)
        self.addAsyncCleanup(self.session.close)
        self.signed_requests = 0

    def config_get(self, url, **kwargs):
        if url.endswith("/finger/spi"):
            payload = {"code": 0, "data": {"b_3": "fixture-browser"}}
        elif url.endswith("/room_init"):
            payload = {"code": 0, "data": {"room_id": 123}}
        elif url.endswith("/getDanmuInfo"):
            if kwargs.get("cookies", {}).get("buvid3") != "fixture-browser":
                payload = {"code": -352}
            else:
                self.signed_requests += 1
                self.assertEqual(kwargs["headers"]["User-Agent"], self.session.headers["User-Agent"])
                payload = {"code": 0, "data": {"token": f"signed-{self.signed_requests}",
                           "host_list": [{"host": "example.invalid", "wss_port": 443}]}}
        else:
            payload = {"code": 0, "data": {"token": "legacy-rejected-by-room",
                       "host_server_list": [{"host": "example.invalid", "wss_port": 443}]}}
        return Mock(status_code=200, json=lambda: payload)

    async def connect(self):
        client = _Client(123, session=self.session, token="legacy-rejected-by-room",
                         hosts=[{"host": "example.invalid", "wss_port": 443}])
        await client._on_before_ws_connect(0)
        return client

    async def test_signed_token_and_auth_share_browser_identity(self):
        with patch.object(bili.requests, "get", self.config_get), \
                patch.object(bili, "_wbi_key", return_value="fixture-wbi-key"):
            client = await self.connect()
            socket = Socket()
            client._websocket = socket
            await client._send_auth()
            operation, auth = socket.packets[-1]
            self.assertEqual(operation, ws_base.Operation.AUTH)
            self.assertEqual(auth["buvid"], "fixture-browser")
            self.assertEqual(auth["key"], "signed-1")

    async def test_auth_rejection_refreshes_token_before_retry(self):
        with patch.object(bili.requests, "get", self.config_get), \
                patch.object(bili, "_wbi_key", return_value="fixture-wbi-key"):
            client = await self.connect()
            socket = Socket()
            client._websocket = socket
            header = ws_base.HeaderTuple(0, 16, ws_base.ProtoVer.NORMAL,
                                         ws_base.Operation.AUTH_REPLY, 1)
            with self.assertRaises(ws_base.AuthError):
                await client._parse_business_message(header, b'{"code": -101}')
            client._need_init_room = True  # Set by the upstream network loop on AuthError.
            await client._on_before_ws_connect(1)
            await client._send_auth()
            self.assertEqual(socket.packets[-1][1]["key"], "signed-2")

    async def test_lookup_failure_can_recover_on_next_attempt(self):
        client = _Client(123, session=self.session)
        with patch.object(bili, "ensure_buvid3", return_value="fixture-browser"), \
                patch.object(bili, "danmaku_conf", side_effect=[(123, "", []),
                             (123, "new-token", [{"host": "example.invalid", "wss_port": 443}])]):
            with self.assertRaises(aiohttp.ClientConnectionError):
                await client._on_before_ws_connect(0)
            await client._on_before_ws_connect(1)
            socket = Socket()
            client._websocket = socket
            await client._send_auth()
            self.assertEqual(socket.packets[-1][1]["key"], "new-token")

    async def test_normal_disconnect_also_refreshes_credentials(self):
        with patch.object(bili.requests, "get", self.config_get), \
                patch.object(bili, "_wbi_key", return_value="fixture-wbi-key"):
            client = await self.connect()
            await client._on_before_ws_connect(1)
            socket = Socket()
            client._websocket = socket
            await client._send_auth()
            self.assertEqual(socket.packets[-1][1]["key"], "signed-2")

    async def test_invalid_uid_response_is_retryable(self):
        client = _Client(123, session=self.session)
        calls = []
        async def uid():
            calls.append(True)
            if len(calls) == 1:
                raise aiohttp.ContentTypeError(None, (), message="Non-JSON response")
            client._uid = 1234
            return True
        with patch.object(client, "_init_uid", uid), \
                patch.object(bili.requests, "get", self.config_get), \
                patch.object(bili, "_wbi_key", return_value="fixture-wbi-key"):
            with self.assertRaises(aiohttp.ClientConnectionError):
                await client._on_before_ws_connect(0)
            await client._on_before_ws_connect(1)
            self.assertEqual(client._host_server_token, "signed-1")
            self.assertEqual(client._uid, 1234)

    async def test_existing_session_cookies_are_used_as_one_snapshot(self):
        cookies = http.cookies.SimpleCookie()
        for name, value in {"SESSDATA": "captured-session", "bili_jct": "captured-csrf", "buvid3": "fixture-browser"}.items():
            cookies[name] = value
            cookies[name]["domain"] = "bilibili.com"
        self.session.cookie_jar.update_cookies(cookies)
        # Switching the app account must not pair an old connection with the new account token.
        bili.set_login_cookies("new-session", "new-csrf", "new-browser")
        async def uid(client):
            client._uid = 1234
            return True
        with patch.object(bili.requests, "get", self.config_get), \
                patch.object(_Client, "_init_uid", uid), \
                patch.object(bili, "_wbi_key", return_value="fixture-wbi-key"), \
                patch.object(bili, "danmaku_conf", wraps=bili.danmaku_conf) as lookup:
            client = await self.connect()
            self.assertEqual(lookup.call_args.kwargs["cookies"],
                             {"SESSDATA": "captured-session", "bili_jct": "captured-csrf", "buvid3": "fixture-browser"})
            self.assertEqual(client._uid, 1234)

    async def test_network_retry_renews_token_and_preserves_user_agent(self):
        authenticated = asyncio.Event()
        received = []
        async def subscribe(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            message = await socket.receive()
            head = ws_base.HEADER_STRUCT.unpack_from(message.data)
            auth = json.loads(message.data[head[1]:head[0]])
            received.append((request.headers.get("User-Agent"), auth))
            code = -101 if len(received) == 1 else 0
            await socket.send_bytes(ws_base.WebSocketClientBase._make_packet(
                {"code": code}, ws_base.Operation.AUTH_REPLY))
            async for _ in socket:
                pass
            return socket
        server = web.Application()
        server.router.add_get("/sub", subscribe)
        runner = web.AppRunner(server)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        def status(text):
            if text == "已连接":
                authenticated.set()
        client = _Client(123, session=self.session, on_status=status)
        with patch.object(bili.requests, "get", self.config_get), \
                patch.object(bili, "_wbi_key", return_value="fixture-wbi-key"), \
                patch.object(client, "_get_ws_url", return_value=f"http://127.0.0.1:{port}/sub"), \
                patch.object(ws_base.logger, "exception"):
            try:
                client.start()
                await asyncio.wait_for(authenticated.wait(), 4)
            finally:
                await client.stop_and_close()
        self.assertEqual([item[0] for item in received], [bili.UA, bili.UA])
        self.assertEqual([item[1]["key"] for item in received], ["signed-1", "signed-2"])
        self.assertEqual([item[1]["buvid"] for item in received], ["fixture-browser"] * 2)


if __name__ == "__main__":
    unittest.main()
