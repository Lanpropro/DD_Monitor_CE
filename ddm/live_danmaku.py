"""国内直播平台的只读弹幕连接；协议参考见 domestic_live 插件的 README。"""
import asyncio
import base64
import gzip
import hashlib
import json
import random
import re
import struct
import threading
from urllib.parse import urlencode

import aiohttp
from PySide6.QtCore import QThread, Signal

from .live_danmaku_protocol import (MAX_PACKET, douyu_packet, douyu_messages, tars_int, tars_bytes, tars_fields, huya_events, varint, proto_field, proto_fields, proto_first, douyin_events, douyin_signature)
DOUYU_HEARTBEAT = 20.0
DOUYU_RECEIVE_TIMEOUT = 45.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


class LiveDanmakuClient(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, room_id, platform, parent=None):
        super().__init__(parent)
        self.room_id = platform.normalize(room_id)
        self.platform = platform
        self._stopped = threading.Event()
        self._loop = self._task = None
        self._connected = False

    def stop(self):
        self._stopped.set()
        loop, task = self._loop, self._task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def run(self):
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass
        except Exception as error:  # noqa: BLE001
            if not self._stopped.is_set():
                self.status.emit(f"弹幕连接出错：{type(error).__name__}")
        finally:
            self._task = self._loop = None

    async def _main(self):
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        retries = 0
        failures = 0
        while not self._stopped.is_set():
            self.status.emit("连接中…" if not retries else f"重连中…（第 {retries} 次）")
            self._connected = False
            try:
                async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                        timeout=aiohttp.ClientTimeout(total=12, connect=5)) as session:
                    if self.platform.kind == "douyu":
                        await self._douyu(retries)
                    else:
                        await self._websocket(session, retries)
            except (aiohttp.ClientError, OSError, ValueError, KeyError, RuntimeError, asyncio.TimeoutError):
                if not self._stopped.is_set():
                    self.status.emit("弹幕连接中断，准备重连…")
            failures = 1 if self._connected else failures + 1
            retries += 1
            if not self._stopped.is_set():
                await asyncio.sleep(min(failures, 5))

    async def _douyu(self, retries=0):
        # The public URL can be a vanity number; subscription requires the actual room.
        info = await asyncio.to_thread(self.platform.room_info, self.room_id)
        if self._stopped.is_set():
            return
        raw = self.platform.normalize(info.room_id).split(":", 1)[1]
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            "danmuproxy.douyu.com", 8601 + retries % 2), 5)
        try:
            writer.write(douyu_packet(f"type@=loginreq/roomid@={raw}/"))
            await writer.drain()
            buffer = bytearray()
            authenticated = False
            heartbeat = asyncio.get_running_loop().time()
            last_received = heartbeat
            while not self._stopped.is_set():
                now = asyncio.get_running_loop().time()
                if now >= heartbeat:
                    writer.write(douyu_packet("type@=mrkl/"))
                    await writer.drain()
                    heartbeat = now + DOUYU_HEARTBEAT
                try:
                    deadline = last_received + (DOUYU_RECEIVE_TIMEOUT if authenticated else 5)
                    chunk = await asyncio.wait_for(reader.read(65536), max(.01, min(heartbeat, deadline) - now))
                except asyncio.TimeoutError:
                    if not authenticated or asyncio.get_running_loop().time() - last_received >= DOUYU_RECEIVE_TIMEOUT:
                        raise ValueError("Douyu response timeout")
                    continue
                if not chunk:
                    raise OSError("Douyu connection closed")
                last_received = asyncio.get_running_loop().time()
                buffer.extend(chunk)
                for data in douyu_messages(buffer):
                    if data.get("type") == "loginres":
                        if data.get("error", "0") != "0":
                            raise ValueError("Douyu login rejected")
                        writer.write(douyu_packet(f"type@=joingroup/rid@={raw}/gid@=-9999/"))
                        await writer.drain()
                        authenticated = True
                        self._connected = True
                        self.status.emit("已连接")
                    elif data.get("type") == "error":
                        raise ValueError("Douyu server rejected subscription")
                    elif data.get("type") == "chatmsg" and data.get("txt"):
                        self.message.emit({"kind": "danmaku", "uname": data.get("nn", ""),
                                           "text": data["txt"]})
        finally:
            writer.close()
            await writer.wait_closed()

    async def _websocket(self, session, retries):
        url = self.platform.room_url(self.room_id)
        headers = {"Referer": url, "Origin": url.rsplit("/", 1)[0]}
        if self.platform.kind == "huya":
            async with session.get(url) as response:
                response.raise_for_status()
                page = await response.text()
            match = re.search(r'\bTT_ROOM_DATA\s*=\s*', page)
            if match is None:
                raise ValueError("Missing Huya presenter")
            room, _ = json.JSONDecoder().raw_decode(page[match.end():].lstrip())
            uid = int(room["id"])
            user = (tars_int(0, uid) + tars_int(1, 0) + b"\x26\0\x36\0" + tars_int(4, 0) +
                    tars_int(5, 0) + tars_int(6, uid) + tars_int(7, 3))
            registration = tars_int(0, 1) + tars_bytes(1, user)
            endpoint = "wss://cdnws.api.huya.com/"
            heartbeat = tars_int(0, 5) + tars_bytes(1, b"")
        else:
            info = await self.platform.room_data_async(session, self.room_id)
            room = info["room"]
            if info.get("ttwid"):
                headers["Cookie"] = "ttwid=" + info["ttwid"]
            if room["status"] != 2:
                self.status.emit("主播未开播")
                await asyncio.sleep(30)
                return
            params = {"app_name": "douyin_web", "compress": "gzip", "device_platform": "web",
                "browser_language": "zh-CN", "browser_platform": "Win32", "browser_name": "Mozilla",
                "browser_version": "130.0.0.0", "aid": "6383", "live_id": "1", "enter_from": "web_live",
                "version_code": "180800",
                "webcast_sdk_version": "1.0.15", "update_version_code": "1.0.15",
                "host": "https://live.douyin.com", "did_rule": "3", "identity": "audience",
                "endpoint": "live_pc", "need_persist_msg_count": "15", "heartbeatDuration": "0",
                "room_id": str(room["id_str"]), "user_unique_id": str(random.randrange(7300000000000000000, 8000000000000000000))}
            params["signature"] = douyin_signature(params)
            host = ("lq", "hl", "lf")[retries % 3]
            endpoint = f"wss://webcast100-ws-web-{host}.douyin.com/webcast/im/push/v2/?" + urlencode(params)
            registration, heartbeat = b"", proto_field(7, "hb")
        async with session.ws_connect(endpoint, headers=headers, heartbeat=20,
                timeout=aiohttp.ClientWSTimeout(ws_receive=60, ws_close=1), max_msg_size=MAX_PACKET) as ws:
            if registration:
                await ws.send_bytes(registration)
            async def keepalive():
                while True:
                    await ws.send_bytes(heartbeat)
                    await asyncio.sleep(10)
            task = asyncio.create_task(keepalive())
            connected = False
            try:
                async for packet in ws:
                    if packet.type != aiohttp.WSMsgType.BINARY:
                        if packet.type == aiohttp.WSMsgType.ERROR:
                            raise OSError("WebSocket receive error")
                        continue
                    if self.platform.kind == "huya":
                        kind, events = huya_events(packet.data)
                        ready, ack = kind in (2, 7), None
                    else:
                        ready, events, ack = douyin_events(packet.data)
                    if ack is not None:
                        await ws.send_bytes(ack)
                    if ready and not connected:
                        self._connected = True
                        self.status.emit("已连接")
                        connected = True
                    for event in events:
                        self.message.emit(event)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        raise OSError("WebSocket closed")
