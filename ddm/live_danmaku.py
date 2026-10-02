"""国内直播平台的只读弹幕连接；协议参考见 plugins_user/huya_watch/README.md。"""
import asyncio
import base64
import gzip
import hashlib
import json
import random
import re
import struct
import threading
import uuid
from urllib.parse import urlencode

import aiohttp
from PySide6.QtCore import QThread, Signal

MAX_PACKET = 4 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def douyu_packet(text):
    body = text.encode("utf-8") + b"\0"
    return struct.pack("<III", len(body) + 8, len(body) + 8, 689) + body


def douyu_messages(buffer):
    messages = []
    while len(buffer) >= 12:
        size, repeated, kind = struct.unpack_from("<III", buffer)
        if size < 9 or size > MAX_PACKET or repeated != size or kind not in (689, 690):
            raise ValueError("Invalid Douyu packet")
        if len(buffer) < size + 4:
            break
        body = bytes(buffer[12:size + 3]).decode("utf-8")
        if buffer[size + 3] != 0:
            raise ValueError("Missing Douyu terminator")
        del buffer[:size + 4]
        values = {}
        for part in body.split("/"):
            if "@=" in part:
                key, value = part.split("@=", 1)
                values[key] = value.replace("@S", "/").replace("@A", "@")
        messages.append(values)
    return messages


def tars_int(tag, value):
    if value == 0:
        return bytes([tag << 4 | 12])
    for kind, fmt in enumerate((">b", ">h", ">i", ">q")):
        bits = 8 * struct.calcsize(fmt)
        if -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
            return bytes([tag << 4 | kind]) + struct.pack(fmt, value)
    raise ValueError("TARS integer overflow")


def tars_bytes(tag, value):
    return bytes([tag << 4 | 13, 0]) + tars_int(0, len(value)) + value


def tars_fields(data):
    """读取 TARS 字段（包括嵌套结构和未知字段），严格限制包长及嵌套。"""
    pos = 0
    def take(size):
        nonlocal pos
        if size < 0 or pos + size > len(data):
            raise ValueError("Truncated TARS packet")
        value = data[pos:pos + size]
        pos += size
        return value
    def field(depth=0):
        if depth > 20:
            raise ValueError("TARS nesting too deep")
        head = take(1)[0]
        tag, kind = head >> 4, head & 15
        if tag == 15:
            tag = take(1)[0]
        if kind <= 5:
            fmt = (">b", ">h", ">i", ">q", ">f", ">d")[kind]
            value = struct.unpack(fmt, take(struct.calcsize(fmt)))[0]
        elif kind in (6, 7):
            size = take(1)[0] if kind == 6 else struct.unpack(">I", take(4))[0]
            value = take(size).decode("utf-8", "replace")
        elif kind in (8, 9):
            count = field(depth + 1)[1]
            if not isinstance(count, int) or not 0 <= count <= len(data):
                raise ValueError("Invalid TARS collection size")
            value = [field(depth + 1)[1] for _ in range(count * (2 if kind == 8 else 1))]
        elif kind == 10:
            value = fields(depth + 1, nested=True)
        elif kind in (11, 12):
            value = 0
        elif kind == 13:
            if take(1) != b"\x00":
                raise ValueError("Invalid TARS byte array")
            value = take(field(depth + 1)[1])
        else:
            raise ValueError("Unknown TARS type")
        return tag, value, kind
    def fields(depth=0, nested=False):
        result = {}
        while pos < len(data):
            tag, value, kind = field(depth)
            if kind == 11:
                if not nested:
                    raise ValueError("Unexpected TARS struct end")
                return result
            result[tag] = value
        if nested:
            raise ValueError("Missing TARS struct end")
        return result
    return fields()


def huya_events(data):
    command = tars_fields(data)
    kind = command.get(0)
    events = []
    if kind == 2:
        registration = tars_fields(command.get(1, b""))
        if registration.get(0) != 0:
            raise ValueError("Huya subscription rejected")
    elif kind == 7:
        push = tars_fields(command.get(1, b""))
        if push.get(1) == 1400:
            notice = tars_fields(push.get(2, b""))
            user = notice.get(0, {})
            text = notice.get(3, "")
            if text:
                events.append({"kind": "danmaku", "uname": user.get(2, ""), "text": text})
    return kind, events


def varint(value):
    result = bytearray()
    while value >= 128:
        result.append(value & 127 | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def proto_field(tag, value):
    if isinstance(value, int):
        return varint(tag << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode("utf-8")
    return varint(tag << 3 | 2) + varint(len(value)) + value


def proto_fields(data):
    pos, result = 0, {}
    def integer():
        nonlocal pos
        value = 0
        for shift in range(0, 70, 7):
            if pos >= len(data):
                raise ValueError("Truncated Protobuf varint")
            byte = data[pos]
            pos += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("Invalid Protobuf varint")
    while pos < len(data):
        head = integer()
        tag, wire = head >> 3, head & 7
        if not tag:
            raise ValueError("Invalid Protobuf tag")
        if wire == 0:
            value = integer()
        elif wire in (1, 2, 5):
            size = integer() if wire == 2 else (8 if wire == 1 else 4)
            if pos + size > len(data):
                raise ValueError("Truncated Protobuf field")
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError("Unsupported Protobuf wire type")
        result.setdefault(tag, []).append(value)
    return result


def proto_first(fields, tag, default=b""):
    return fields.get(tag, [default])[0]


def douyin_events(data):
    frame = proto_fields(data)
    payload = proto_first(frame, 8)
    if not payload:
        return False, [], None
    if payload.startswith(b"\x1f\x8b"):
        # 限制解压结果，避免损坏的网络包占满内存。
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as zipped:
            payload = zipped.read(MAX_PACKET + 1)
        if len(payload) > MAX_PACKET:
            raise ValueError("Oversized Douyin payload")
    response = proto_fields(payload)
    ack = None
    if proto_first(response, 9, 0):
        ack = (proto_field(2, proto_first(frame, 2, 0)) + proto_field(7, "ack") +
               proto_field(8, proto_first(response, 5)))
    events = []
    for item in response.get(1, []):
        message = proto_fields(item)
        method = proto_first(message, 1)
        if method not in (b"WebcastChatMessage", b"WebcastEmojiChatMessage"):
            continue                       # 不接入人数、点赞等统计消息
        chat = proto_fields(proto_first(message, 2))
        user = proto_fields(proto_first(chat, 2))
        text = proto_first(chat, 3 if method == b"WebcastChatMessage" else 5).decode("utf-8", "replace")
        if text:
            events.append({"kind": "danmaku", "uname": proto_first(user, 3).decode("utf-8", "replace"),
                           "text": text})
    return True, events, ack


def douyin_signature(params):
    """网页 IM signature 的紧凑算法，改写自 biliup（MIT，见第三方声明）。"""
    keys = ("live_id", "aid", "version_code", "webcast_sdk_version", "room_id", "sub_room_id",
            "sub_channel_id", "did_rule", "user_unique_id", "device_platform", "device_type", "ac", "identity")
    stub = hashlib.md5(",".join(f"{key}={params.get(key, '')}" for key in keys).encode()).digest()
    seed = random.randrange(255)
    payload = bytearray([1, 0, 1, 14, 69, 63, *hashlib.md5(stub).digest()[-2:], seed])
    checksum = 0
    for byte in payload:
        checksum ^= byte
    payload.append(checksum)
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + seed) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    for offset in range(len(payload)):
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        payload[offset] ^= state[(state[i] + state[j]) & 255]
    alphabet = b"Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe"
    encoded = base64.b64encode(bytes([64 | random.randrange(32), seed]) + payload)
    return encoded.translate(bytes.maketrans(
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/", alphabet)).decode()


class LiveDanmakuClient(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, room_id, platform, parent=None):
        super().__init__(parent)
        self.room_id = platform.normalize(room_id)
        self.platform = platform
        self._stopped = threading.Event()
        self._loop = self._task = None

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
        while not self._stopped.is_set():
            self.status.emit("连接中…" if not retries else f"重连中…（第 {retries} 次）")
            try:
                async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                        timeout=aiohttp.ClientTimeout(total=12, connect=5)) as session:
                    if self.platform.kind == "douyu":
                        await self._douyu(retries)
                    else:
                        await self._websocket(session, retries)
            except (aiohttp.ClientError, OSError, ValueError, KeyError, asyncio.TimeoutError):
                if not self._stopped.is_set():
                    self.status.emit("弹幕连接中断，准备重连…")
            retries += 1
            if not self._stopped.is_set():
                await asyncio.sleep(min(2 * retries, 15))

    async def _douyu(self, retries=0):
        raw = self.room_id.split(":", 1)[1]
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
                    heartbeat = now + 40
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), 10)
                except asyncio.TimeoutError:
                    if not authenticated or asyncio.get_running_loop().time() - last_received > 65:
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
                        self.status.emit("已连接")
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
            async with session.get(url, cookies={"__ac_nonce": uuid.uuid4().hex[:21]}) as response:
                response.raise_for_status()
                info = self.platform._page_info(await response.text())
            room = info["room"]
            if room["status"] != 2:
                self.status.emit("主播未开播")
                await asyncio.sleep(30)
                return
            params = {"app_name": "douyin_web", "compress": "gzip", "device_platform": "web",
                "browser_language": "zh-CN", "browser_platform": "Win32", "browser_name": "Mozilla",
                "browser_version": "130.0.0.0", "aid": "6383", "live_id": "1", "version_code": "180800",
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
                        self.status.emit("已连接")
                        connected = True
                    for event in events:
                        self.message.emit(event)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        raise OSError("WebSocket closed")
