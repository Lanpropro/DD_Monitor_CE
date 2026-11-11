"""Douyu, Huya and Douyin read-only danmaku framing, field parsing and signature algorithms."""
import base64
import gzip
import hashlib
import random
import struct


MAX_PACKET = 4 * 1024 * 1024


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
                events.append({"kind": "danmaku", "uid": str(user.get(0) or ''), "uname": user.get(2, ""), "text": text})
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
            event = {"kind": "danmaku", "uname": proto_first(user, 3).decode("utf-8", "replace"),
                     "text": text}
            common = proto_fields(proto_first(chat, 1))
            mid = proto_first(message, 3, 0) or proto_first(common, 2, 0)
            if isinstance(mid, int) and mid > 0:
                event["message_id"] = str(mid)
            uid = proto_first(user, 1, 0)
            if isinstance(uid, int) and uid > 0:
                event["uid"] = str(uid)
            events.append(event)
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
