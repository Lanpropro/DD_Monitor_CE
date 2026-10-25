"""B 站直播接口：房间信息与播放地址。

取流优先走 app-room，失败时退回 web 端 playUrl，并尝试同通道备用 CDN。
保留接口提供的 HTTP/HTTPS 地址，探测与播放使用相同请求头。
"""
import hashlib
import inspect
import json
import sys
import threading
import time
import urllib.parse

import requests
from PySide6.QtCore import QThread, Signal

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://live.bilibili.com/"}

# app-room 接口给出的流地址是给 Android 客户端的：CDN 只认 App UA，
# 而且**不能带 Referer**（带 live.bilibili.com 的 Referer 一律 403）。
APP_UA = ("Mozilla/5.0 BiliDroid/6.25.0 (bbcallen@gmail.com) os/android model/MuMu "
          "mobi_app/android build/6250300 channel/bili innerVer/6250300 osVer/6.0.1 network/2")
STREAM_APP = {"User-Agent": APP_UA}
STREAM_WEB = {"User-Agent": UA, "Referer": "https://live.bilibili.com/"}

# 未登录时接口固定返回 250（超清 720P），其余档位需要登录 cookie，
# 这里先把档位留着，等接入登录后再启用。
QUALITY_CHOICES = [("原画", 10000), ("蓝光", 400), ("超清 720P", 250), ("流畅", 80)]

#: 直播流编码方式：设置值 -> (界面文案, app-room 接口的 codec 参数)。
#: H.264 优先 FLV，HEVC / AV1 使用可稳定解析的 fMP4 HLS 通道。
BILI_CODECS = (
    ("avc", "H.264 / AVC（默认，兼容性最好）", 0),
    ("hevc", "HEVC / H.265（同画质省约一半码率）", 1),
    ("av1", "AV1（仅B站）", 2),
)

#: 设置值 -> 接口 codec 参数。
CODEC_PARAM = {value: param for value, _label, param in BILI_CODECS}

HLS_ONLY_CODECS = ("hevc", "av1")

#: 通道名保留容器及实际编码信息，供播放状态和录像使用。
HLS_SUFFIX = "-hls"
BILI_PROFILES = {"app": ("avc", False), "web": ("avc", False),
                 "app-hls": ("", True), "web-hls": ("", True)}
BILI_PROFILES.update({f"{source}-hls-{codec}": (codec, True)
                      for source in ("app", "web") for codec in CODEC_PARAM})


def is_hls_profile(profile: str) -> bool:
    """只匹配已约定的 B 站通道；插件通道由播放器的平台分支处理。"""
    return BILI_PROFILES.get(str(profile or "").lower(), ("", False))[1]


def codec_from_profile(profile: str) -> str:
    """通道名 -> 这一路流的视频编码（avc / hevc / av1）。

    取流结果只带通道名（``resolved`` 信号的参数个数被很多地方依赖，不能再加一个
    编码），编码就从名字里读：``app`` / ``web`` 是 FLV 直连，只有 H.264；
    ``app-hls-hevc`` / ``app-hls-av1`` 这类 HLS 通道把编码写在名字里。名字里
    查不到编码（没写编码的 HLS 通道、平台插件的 huya / twitch…）返回空串，
    表示「不知道编码，按原来的容器走」。
    """
    return BILI_PROFILES.get(str(profile or "").lower(), ("", False))[0]

# 登录后的 SESSDATA，带上它才能解锁原画、拉取关注列表
SESSION_DATA = ""
BILI_JCT = ""
BUVID3 = ""
_COOKIE_LOCK = threading.RLock()
_BUVID3_LOCK = threading.Lock()
_UID_CACHE: dict = {"uid": None}
_WBI_CACHE: dict = {"key": "", "expires": 0.0}
_WBI_KEY_INDEX = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
]


def set_sessdata(value: str) -> None:
    global SESSION_DATA, BILI_JCT
    with _COOKIE_LOCK:
        if not value or value != SESSION_DATA:
            BILI_JCT = ""            # CSRF 属于账号，不能跟到另一个会话。
        SESSION_DATA = value or ""
        _UID_CACHE["uid"] = None


def set_login_cookies(sessdata: str, bili_jct: str = "", buvid3: str | None = None) -> None:
    """原子更新登录态；未提供设备 Cookie 时保留本机已有浏览器身份。"""
    global BILI_JCT, BUVID3
    with _COOKIE_LOCK:
        set_sessdata(sessdata)
        BILI_JCT = (bili_jct or "") if SESSION_DATA else ""
        if buvid3 is not None:
            BUVID3 = buvid3 if isinstance(buvid3, str) else ""


def _cookies() -> dict:
    with _COOKIE_LOCK:
        cookies = {"buvid3": BUVID3} if BUVID3 else {}
        if SESSION_DATA:
            cookies["SESSDATA"] = SESSION_DATA
            if BILI_JCT:
                cookies["bili_jct"] = BILI_JCT
        return cookies


def ensure_buvid3() -> str:
    """后台按需补齐设备身份，多直播间共用一次请求；不在此处写配置。"""
    global BUVID3
    with _BUVID3_LOCK:
        cached = _cookies().get("buvid3")
        if cached:
            return cached
        response = requests.get("https://api.bilibili.com/x/frontend/finger/spi",
                                headers=HEADERS, timeout=10)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        value = data.get("b_3") if isinstance(data, dict) else None
        if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(value, str) or not value.strip():
            raise ValueError("无法取得 B 站浏览器标识")
        with _COOKIE_LOCK:
            # 获取期间可能已完成登录，优先保留登录页采集的浏览器身份。
            if not BUVID3:
                BUVID3 = value.strip()
            return BUVID3


def _danmaku_result(response) -> dict:
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise ValueError("B 站接口未接受请求")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        reason = (payload.get("message") or payload.get("msg")) if isinstance(payload, dict) else None
        raise ValueError(str(reason or "B 站接口返回异常"))
    return payload


def _sending_room_id(room_id: str) -> str:
    room_id = str(room_id or "").strip()
    if not room_id.isascii() or not room_id.isdigit() or not room_id.strip("0"):
        raise ValueError("仅支持有效的 B 站直播间")
    return _resolve_room_id(room_id)


def send_danmaku(room_id: str, message: str, *, dm_type: int = 0,
                 cookies: dict | None = None) -> dict:
    """发送文字或完整大表情标识；POST 不自动重试，避免超时后重复发送。"""
    if not isinstance(message, str) or not message.strip() or dm_type not in (0, 1):
        raise ValueError("弹幕内容或类型无效")
    snapshot = dict(_cookies() if cookies is None else cookies)
    if not snapshot.get("SESSDATA"):
        raise ValueError("请先登录 B 站")
    if not snapshot.get("bili_jct"):
        raise ValueError("登录缺少 bili_jct，请退出 B 站账号后重新登录")
    real_id = _sending_room_id(room_id)
    if not snapshot.get("buvid3"):
        snapshot["buvid3"] = ensure_buvid3()
    csrf = snapshot["bili_jct"]
    response = requests.post(
        "https://api.live.bilibili.com/msg/send",
        data={"roomid": real_id, "msg": message, "dm_type": str(dm_type),
              "rnd": str(int(time.time())), "fontsize": "25", "color": "16777215",
              "mode": "1", "bubble": "0", "csrf": csrf, "csrf_token": csrf},
        headers={**HEADERS, "Origin": "https://live.bilibili.com",
                 "Referer": f"https://live.bilibili.com/{real_id}"},
        cookies=snapshot, timeout=10, allow_redirects=False)
    payload = _danmaku_result(response)
    # 有些拒绝仍返回 code=0（包括 message="f"），不能据此清空草稿。
    data = payload.get("data")
    for section in (payload, data if isinstance(data, dict) else {}):
        for key in ("message", "msg"):
            reason = section.get(key)
            if reason not in (None, "", "0", 0):
                raise ValueError("发送未成功，请稍后重试" if reason == "f" else str(reason))
    return payload


def get_emoticons(room_id: str, *, cookies: dict | None = None) -> list[dict]:
    """保留服务端表情类型、完整标识和解锁权限；设备身份复用接收弹幕的缓存。"""
    snapshot = dict(_cookies() if cookies is None else cookies)
    real_id = _sending_room_id(room_id)
    if not snapshot.get("buvid3"):
        snapshot["buvid3"] = ensure_buvid3()
    response = requests.get(
        "https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons",
        params={"platform": "pc", "room_id": real_id},
        headers=HEADERS, cookies=snapshot, timeout=10)
    data = _danmaku_result(response).get("data")
    packages = data.get("data") if isinstance(data, dict) else None
    if not isinstance(packages, list) or any(not isinstance(p, dict) for p in packages):
        raise ValueError("表情列表格式异常，请重试")
    for package in packages:
        emotes = package.get("emoticons")
        if emotes is not None and (not isinstance(emotes, list) or any(not isinstance(e, dict) for e in emotes)):
            raise ValueError("表情列表格式异常，请重试")
    return packages


def room_info(room_id: str) -> dict | None:
    """房间基础信息（直播状态、标题、主播、封面）。"""
    room_id = _resolve_room_id(room_id)
    try:
        response = requests.get(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo",
            params={"req_biz": "web_room_componet", "room_ids": room_id},
            headers=HEADERS, cookies=_cookies(), timeout=10)
        info = response.json()["data"]["by_room_ids"][str(room_id)]
    except Exception:  # noqa: BLE001
        return None
    live = info.get("live_status") == 1
    online = info.get("online")
    viewers = ""
    if live and isinstance(online, int) and online > 0:
        viewers = f"{online / 10000:.1f}万" if online >= 10000 else str(online)
    result = {
        "room_id": str(room_id),
        "uname": info.get("uname") or f"房间 {room_id}",
        "title": info.get("title") or "",
        "live": live,
        "viewers": viewers,
        "face": info.get("face") or "",
        "live_start_ts": _parse_live_time(info.get("live_time")),
        "cover_url": (info.get("keyframe") if live else info.get("cover")) or info.get("cover") or "",
    }
    # 同一个坑：getRoomBaseInfo 不给 face，得拿 uid 去另一个接口补
    try:
        uid = int(info.get("uid") or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid:
        _fill_faces({str(room_id): result}, {str(room_id): uid})
    return result


def _parse_live_time(text) -> int:
    """把直播开始时间转成时间戳，用来算直播时长。

    有的接口给 "2026-09-15 01:23:45"，有的给 Unix 秒数；两种都收。
    """
    try:
        if text is None:
            return 0
        if isinstance(text, (int, float)):
            return int(text)
        text = str(text).strip()
        if text.isdigit():
            return int(text)
        return int(time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S")))
    except Exception:  # noqa: BLE001
        return 0


def my_account() -> dict | None:
    """当前登录账号的信息（昵称、头像）。"""
    try:
        response = requests.get("https://api.bilibili.com/x/web-interface/nav",
                                headers=HEADERS, cookies=_cookies(), timeout=10)
        data = response.json().get("data") or {}
    except Exception:  # noqa: BLE001
        return None
    if not data.get("isLogin"):
        return None
    return {"uid": data.get("mid"), "uname": data.get("uname") or "",
            "face": data.get("face") or ""}


def _resolve_room_id(room_id: str) -> str:
    """短号（如 213）先换成真实房间号，getRoomBaseInfo 不认短号。"""
    room_id = str(room_id).strip()
    if not room_id.isdigit():
        return room_id
    try:
        response = requests.get(
            "https://api.live.bilibili.com/room/v1/Room/room_init",
            params={"id": room_id}, headers=HEADERS, cookies=_cookies(), timeout=10)
        data = response.json()
        real_id = (data.get("data") or {}).get("room_id")
        if real_id:
            return str(real_id)
    except Exception:  # noqa: BLE001
        pass
    return room_id


def _wbi_key() -> str:
    """从 nav 接口取 WBI 混淆密钥，并缓存到当前进程。"""
    now = time.time()
    if _WBI_CACHE["key"] and now < _WBI_CACHE["expires"]:
        return str(_WBI_CACHE["key"])
    try:
        payload = requests.get("https://api.bilibili.com/x/web-interface/nav",
                               headers=HEADERS, cookies=_cookies(), timeout=10).json()
        wbi_img = (payload.get("data") or {}).get("wbi_img") or {}
        img_key = str(wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
        sub_key = str(wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".", 1)[0]
        source = img_key + sub_key
        key = "".join(source[index] for index in _WBI_KEY_INDEX if index < len(source))
    except Exception:  # noqa: BLE001
        return ""
    if key:
        _WBI_CACHE.update(key=key, expires=now + 11 * 60 * 60)
    return key


def _wbi_signed_params(params: dict, key: str) -> dict:
    """给 getDanmuInfo 参数加 wts / w_rid。"""
    signed = {**params, "wts": str(int(time.time()))}
    cleaned = {
        name: "".join(ch for ch in str(signed[name]) if ch not in "!'()*")
        for name in sorted(signed)
    }
    query = urllib.parse.urlencode(cleaned)
    return {**signed, "w_rid": hashlib.md5((query + key).encode("utf-8")).hexdigest()}


def danmaku_conf(room_id: str, *, cookies: dict | None = None, user_agent: str = UA) -> tuple[int, str, list]:
    """弹幕连接要用的东西：(真实房间号, token, 服务器列表)。

    优先使用带 WBI 签名的 getDanmuInfo；失败时再降级到老 getConf。
    """
    real_id = _resolve_room_id(room_id)
    cookies = dict(_cookies() if cookies is None else cookies)
    if not cookies.get("buvid3"):
        cookies["buvid3"] = ensure_buvid3()
    headers = {**HEADERS, "User-Agent": user_agent}
    data = {}
    key = _wbi_key()
    if key:
        try:
            response = requests.get(
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo",
                params=_wbi_signed_params({"id": real_id, "type": 0}, key),
                headers=headers, cookies=cookies, timeout=10)
            payload = response.json()
            if payload.get("code") == 0:
                data = payload.get("data") or {}
        except Exception:  # noqa: BLE001
            data = {}
    if not data.get("host_list"):
        try:
            response = requests.get(
                "https://api.live.bilibili.com/room/v1/Danmu/getConf",
                params={"room_id": real_id, "platform": "pc", "player": "web"},
                headers=headers, cookies=cookies, timeout=10)
            data = response.json().get("data") or {}
        except Exception:  # noqa: BLE001
            return int(real_id) if str(real_id).isdigit() else 0, "", []
    hosts = []
    seen_hosts = set()
    for host in data.get("host_list") or data.get("host_server_list") or []:
        key = (host.get("host"), host.get("wss_port"))
        if not all(key) or key in seen_hosts:
            continue
        seen_hosts.add(key)
        hosts.append(host)
    real = data.get("room_id") or real_id
    return (int(real) if str(real).isdigit() else 0), (data.get("token") or ""), hosts


def _fetchable(url: str, headers: dict) -> bool:
    """用播放器实际会发送的请求头确认 CDN 地址能拉流。"""
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=8)
        try:
            chunk = next(response.iter_content(16), b"")
            return response.status_code == 200 and bool(chunk)
        finally:
            response.close()
    except Exception:  # noqa: BLE001
        return False


def _app_protocol(codec: str) -> str:
    """这种编码在 app-room 接口里该挑哪条通道。

    H.264 是 ``http_stream``（FLV）；HEVC / AV1 只有
    ``http_hls``（fMP4 分片），由 libmpv 原生播放。
    """
    return "http_hls" if codec in HLS_ONLY_CODECS else "http_stream"


def _app_codec_entry(stream: dict, codec: str) -> dict | None:
    """从一条 stream 里挑出 ``codec`` 对应的那条 codec 条目。

    同一条通道可能同时列出几种编码；接口没给 ``codec_name`` 时（老响应）沿用
    第一条，H.264 的老行为不变。明确给的是别的编码时返回 None：宁可报错，也
    不能把 H.264 的地址当成 HEVC / AV1 交出去。
    """
    entries = [entry for fmt in stream.get("format") or []
               for entry in fmt.get("codec") or []]
    if not entries:
        return None
    for entry in entries:
        if entry.get("codec_name") == codec:
            return entry
    if codec != "avc":
        return None                   # HEVC / AV1 认不到同名条目就报错，不将就
    return next((entry for entry in entries if not entry.get("codec_name")), None)


def _web_play_urls(room_id: str, quality: int, codec: str = "avc") -> tuple[list[str], int]:
    """web 端接口：未登录固定 720P，登录后按 qn 给。

    ``codec`` 只为和 app-room 那边的签名对齐：这个老接口**只有 H.264**，
    HEVC / AV1 不会走到这里（见 :func:`play_url`）。
    """
    response = requests.get(
        "https://api.live.bilibili.com/room/v1/Room/playUrl",
        params={"cid": room_id, "platform": "web", "qn": quality},
        headers=HEADERS, cookies=_cookies(), timeout=10)
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"接口返回 code={data.get('code')} {data.get('message')}")
    payload = data["data"]
    stream = payload["durl"][0]
    urls = [stream["url"], *(stream.get("backup_url") or [])]
    current = int(payload.get("current_qn") or 0)
    return list(dict.fromkeys(urls)), current


def _app_play_info(room_id: str, quality: int, codec: str = "avc") -> dict:
    """app-room 的取流信息，包含实际可用档位和流地址。"""
    params = {
        "appkey": "iVGUTjsxvpLeuDCf", "build": 6250300, "c_locale": "zh_CN",
        "channel": "bili", "codec": CODEC_PARAM.get(codec, 0),
        "device": "android", "device_name": "MuMu",
        "dolby": 1, "format": "0,2", "free_type": 0, "http": 1, "mask": 0,
        "mobi_app": "android", "network": "wifi", "no_playurl": 0, "only_audio": 0,
        "only_video": 0, "platform": "android", "play_type": 0, "protocol": "0,1",
        "qn": quality, "room_id": room_id, "s_locale": "zh_CN",
        "statistics": '{"appId":1,"platform":3,"version":"6.25.0","abtest":""}',
        "ts": int(time.time()),
    }
    response = requests.get(
        "https://api.live.bilibili.com/xlive/app-room/v2/index/getRoomPlayInfo",
        params=params, headers=HEADERS, cookies=_cookies(), timeout=10)
    data = response.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"接口返回 code={data.get('code')} {data.get('message')}")
    return ((data.get("data") or {}).get("playurl_info") or {}).get("playurl") or {}


def _app_profile(codec: str) -> str:
    """这种编码走 app-room 时对应的通道名。

    后缀记录 HLS 容器及实际编码，播放器直接交给 libmpv。
    """
    return f"app{HLS_SUFFIX}-{codec}" if codec in HLS_ONLY_CODECS else "app"


class CodecUnavailable(RuntimeError):
    pass


def _app_play_urls(room_id: str, quality: int, codec: str = "avc") -> tuple[list[str], int]:
    """app-room 接口：尊重 qn（登录后能拿到原画）。

    H.264 取 FLV 通道（给播放器直连）；HEVC / AV1 只有 HLS 通道，取回来要
    由 libmpv 直接读取分片（见 :func:`_app_profile`）。
    """
    protocol = _app_protocol(codec)
    streams = _app_play_info(room_id, quality, codec).get("stream") or []
    for stream in streams:
        if stream.get("protocol_name") != protocol:
            continue
        entry = _app_codec_entry(stream, codec)
        if entry is None:
            continue
        urls = [info["host"] + entry["base_url"] + info["extra"]
                for info in entry.get("url_info") or []]
        if urls:
            return list(dict.fromkeys(urls)), int(entry.get("current_qn") or 0)
    error = CodecUnavailable if codec in HLS_ONLY_CODECS else RuntimeError
    raise error(f"app-room 接口没有返回 {protocol} 地址（{codec}）")


class Cancelled(Exception):
    """这次取流已经被调用方作废（鼠标早就移开了、格子被停掉了）。

    只用它做「安静收尾」的信号，不当成失败上报 —— 见 StreamResolver.cancel()。
    """


def play_url(room_id: str, quality: int = 250,
             cancelled=None, source_offset: int = 0,
             codec: str = "avc", allow_codec_fallback: bool = True) -> tuple[str, int, str, dict]:
    """取可播放的 http 流地址，附带接口实际给到的画质。

    优先用尊重画质的 app-room 接口（App UA、不带 Referer 拉流）；
    失败时退回 web 端接口（Chrome UA + Referer）。保留 CDN 的 URL 协议。

    返回 ``(地址, 实际画质, 通道名, 请求头)``。请求头必须一起带走：插件要
    拿这个地址去录像，头不对 CDN 直接 403。

    ``codec`` 是要哪种编码（``avc`` / ``hevc`` / ``av1``）。HEVC / AV1 只有
    HLS 通道。接口未提供所选编码时，仅该房间回退 H.264，并返回实际编码对应
    的通道与请求头。网络或 CDN 错误仍由原有重连逻辑处理。
    切换前探测使用 allow_codec_fallback=False，缺少目标格式时抛 CodecUnavailable。

    ``cancelled`` 是个可选回调，返回 True 表示这次取流已经没人要了：每换一条
    通道、每次探测地址之前都会问一次，问到 True 就抛 Cancelled 早点收工，
    不把带宽和连接白耗在后面几条通道上。
    """
    def _cancelled() -> bool:
        return bool(cancelled is not None and cancelled())

    sources = [(_app_play_urls, _app_profile(codec), STREAM_APP)]
    if codec not in HLS_ONLY_CODECS:
        sources.append((_web_play_urls, "web", STREAM_WEB))
    errors = []
    for source, profile, headers in sources:
        if _cancelled():
            raise Cancelled()
        try:
            urls, current = source(room_id, quality, codec)
        except CodecUnavailable:
            if _cancelled():
                raise Cancelled()
            if not allow_codec_fallback:
                raise
            print(f"[取流] {room_id} 未提供 {codec.upper()}，改用 H.264",
                  file=sys.stderr, flush=True)
            return play_url(room_id, quality, cancelled=cancelled,
                            source_offset=source_offset, codec="avc")
        except Exception as error:  # noqa: BLE001
            errors.append(f"{source.__name__}: {error}")
            continue
        if urls:
            offset = source_offset % len(urls)
        else:
            offset = 0
        for url in urls[offset:] + urls[:offset]:
            if _cancelled():
                raise Cancelled()
            playback_url = url
            if _fetchable(playback_url, headers):
                if _cancelled():           # 探测期间被作废：别把这个地址交出去
                    raise Cancelled()
                print(f"[取流] {room_id} 通道={profile} 请求画质={quality} 实际给到={current}",
                      file=sys.stderr, flush=True)
                return playback_url, current, profile, dict(headers)
        errors.append(f"{source.__name__}: 地址不可用（CDN 拒绝）")
    detail = "；".join(errors) or "取流失败"
    if codec in HLS_ONLY_CODECS:
        detail = f"{codec.upper()} 流取不到（{detail}）"
    raise RuntimeError(detail)


class StreamResolver(QThread):
    """在后台线程取流，避免阻塞界面。"""

    resolved = Signal(str, str, int, str, list)   # room_id, url, 实际画质, 通道, 可选档位
    failed = Signal(str, str)       # room_id, 原因

    def __init__(self, room_id: str, quality: int = 250, parent=None,
                 *, source_offset: int = 0, platform=None, preview: bool = False,
                 codec: str = "avc", strict_codec: bool = False):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.quality = quality
        self.source_offset = source_offset
        self.platform = platform
        self.preview = preview
        self.codec = codec if codec in CODEC_PARAM else "avc"
        self.strict_codec = strict_codec
        self.codec_unavailable = False
        self.source_codec = ""
        self.codec_probe_note = ""
        self.original_quality_note = ""
        self.headers: dict = {}          # 本次取流的请求头，交给播放器/插件
        self.login_required = False
        self._cancelled = False

    def cancel(self) -> None:
        """作废这次取流：跑完当前这步就收工，结果不再发出来。

        以前这里是 ``QThread.terminate()`` —— 强杀一个正阻塞在 socket 读上的
        线程，会留下没释放的锁 / GIL 和坏掉的线程本地存储（控制台里那几行
        "QThreadStorage: entry ... destroyed before end of thread" 就是证据），
        主线程随后可能直接卡死：窗口不动、也不退出。只置个标志、让线程自己
        跑完最后一步，代价是最多再等一次请求超时，换来的是绝不会卡死。
        """
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _platform_play_url(self) -> tuple:
        from .plugins import LoginRequiredError, Platform, StreamCodecUnavailable

        platform = self.platform
        if platform is None:
            raise ValueError("未指定取流平台")
        # Static lookup avoids treating dynamically fabricated mock attributes as hooks.
        hook = (getattr(platform, "play_url_for_codec", None)
                if inspect.getattr_static(platform, "play_url_for_codec", None) is not None
                else None)
        legacy = (not callable(hook)
                  or getattr(hook, "__func__", None) is Platform.play_url_for_codec)
        candidates = ("avc",) if self.codec == "avc" else ("hevc", "avc")
        prefix = "AV1 仅 B 站；" if self.codec == "av1" else ""
        fallback_note = ""
        retrieval_error = None
        for codec in candidates:
            if self._cancelled:
                raise Cancelled()
            try:
                if callable(hook):
                    result = hook(self.room_id, self.quality, codec=codec)
                    if not isinstance(result, (tuple, list)) or len(result) != 5:
                        raise ValueError("平台编码接口必须返回五项取流结果")
                    actual_codec = result[4]
                    if actual_codec != codec and not (legacy and actual_codec == ""):
                        raise StreamCodecUnavailable(f"平台未提供已验证的 {codec.upper()} 直播源")
                else:
                    if codec != "avc":
                        raise StreamCodecUnavailable("旧版平台插件不支持选择 HEVC 直播源")
                    result = platform.play_url(self.room_id, self.quality)
                    actual_codec = ""
                if not isinstance(result, (tuple, list)):
                    raise TypeError("平台取流结果必须为元组或列表")
                url, current, profile = result[:3]
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("平台未返回有效直播地址")
                headers = dict(result[3]) if len(result) > 3 else {}
            except (Cancelled, LoginRequiredError):
                raise
            except Exception as error:
                if not isinstance(error, StreamCodecUnavailable):
                    retrieval_error = error
                if codec == candidates[-1]:
                    if retrieval_error is not None:
                        raise retrieval_error
                    raise
                fallback_note = ("HEVC 直播源不可用，已回退 H.264"
                                 if isinstance(error, StreamCodecUnavailable)
                                 else "HEVC 取流失败，已回退 H.264")
                continue
            self.source_codec = actual_codec
            if legacy:
                self.codec_probe_note = prefix + "旧版插件使用兼容取流，实际编码以解码读数为准"
            elif fallback_note:
                self.codec_probe_note = prefix + fallback_note
            elif prefix:
                self.codec_probe_note = prefix + "本房间使用 HEVC"
            return url, current, profile, headers
        raise StreamCodecUnavailable("平台未提供可用的直播源格式")

    def run(self) -> None:
        if self._cancelled:
            return
        try:
            if self.platform is not None:
                result = (self.platform.preview_url(self.room_id) if self.preview
                          else self._platform_play_url())
                url, current, profile = result[:3]
                headers = dict(result[3]) if len(result) > 3 else {}
                current = int(current)
                if (not isinstance(url, str) or not url.strip()
                        or not -(2 ** 31) <= current < 2 ** 31
                        or not isinstance(profile, str)):
                    raise ValueError("平台取流结果无效")
            elif self.room_id.isdigit():
                url, current, profile, headers = play_url(
                    self.room_id, self.quality, cancelled=self.is_cancelled,
                    source_offset=self.source_offset, codec=self.codec,
                    allow_codec_fallback=not self.strict_codec)
            else:
                raise ValueError("请启用对应的平台插件并重启")
            if self._cancelled:
                return
            options = ([] if self.preview else
                       self.platform.room_quality_options(self.room_id) if self.platform
                       else room_quality_options(self.room_id,
                                                 codec_from_profile(profile) or self.codec))
            if (self.platform is None and not self.preview
                    and (self.strict_codec or codec_from_profile(profile) in HLS_ONLY_CODECS)
                    and not any(int(option["qn"]) >= 10000 for option in options)):
                name = {"avc": "H.264", "hevc": "HEVC", "av1": "AV1"}[self.codec]
                self.original_quality_note = (f"{name} 未提供原画" if options
                                              else f"未能验证 {name} 的原画档位")
                if self.strict_codec:
                    raise RuntimeError(self.original_quality_note)
                if self._cancelled:
                    return
                url, current, profile, headers = play_url(
                    self.room_id, self.quality, cancelled=self.is_cancelled,
                    source_offset=self.source_offset, codec="avc")
                if self._cancelled:
                    return
                options = room_quality_options(self.room_id, "avc")
            options = options or []
            if not isinstance(options, list):
                raise TypeError("平台画质档位必须为列表")
            if options:
                print(f"[画质档位] {self.room_id}: "
                      + " / ".join(f"{item['desc']}({item['qn']})" for item in options),
                      file=sys.stderr, flush=True)
        except Cancelled:
            return                       # 作废：不发结果，也不算失败
        except CodecUnavailable as error:
            self.codec_unavailable = True
            if not self._cancelled:
                self.failed.emit(self.room_id, str(error))
            return
        except Exception as error:  # noqa: BLE001
            from .plugins import LoginRequiredError, StreamCodecUnavailable
            self.login_required = isinstance(error, LoginRequiredError)
            self.codec_unavailable = isinstance(error, StreamCodecUnavailable)
            if not self._cancelled:
                self.failed.emit(self.room_id, str(error))
            return
        if self._cancelled:
            return
        self.headers = headers
        if self.platform is None:
            self.source_codec = codec_from_profile(profile)
        self.resolved.emit(self.room_id, url, current, profile, options)


class InfoResolver(QThread):
    """在后台线程查房间信息（添加直播间时用）。"""

    resolved = Signal(dict)
    failed = Signal(str)

    def __init__(self, room_id: str, parent=None, *, platform=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.platform = platform

    def run(self) -> None:
        try:
            if self.platform is not None:
                result = self.platform.room_info(self.room_id)
                info = result.as_dict() if result is not None else None
            else:
                from .room_input import is_bili_short_url, resolve_bili_share
                room_id = resolve_bili_share(self.room_id) if is_bili_short_url(self.room_id) else self.room_id
                info = room_info(room_id) if room_id.isdigit() else None
        except Exception:  # noqa: BLE001
            info = None
        if info is None:
            self.failed.emit(self.room_id)
        else:
            self.resolved.emit(info)


def my_uid(force: bool = False) -> int | None:
    """当前登录账号的 UID，未登录返回 None。"""
    if _UID_CACHE["uid"] and not force:
        return _UID_CACHE["uid"]
    try:
        response = requests.get("https://api.bilibili.com/x/web-interface/nav",
                                headers=HEADERS, cookies=_cookies(), timeout=10)
        data = response.json()
    except Exception:  # noqa: BLE001
        return None
    if data.get("code") != 0 or not (data.get("data") or {}).get("isLogin"):
        return None
    uid = int(data["data"]["mid"])
    _UID_CACHE["uid"] = uid
    return uid


def following(uid: int, page_size: int = 50, max_pages: int | None = None) -> list[dict]:
    """拉取关注列表（分页）。"""
    result: list[dict] = []
    seen = set()
    page = 1
    while max_pages is None or page <= max_pages:
        response = requests.get(
            "https://api.bilibili.com/x/relation/followings",
            params={"vmid": uid, "pn": page, "ps": page_size, "order": "desc"},
            headers=HEADERS, cookies=_cookies(), timeout=10)
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("message") or "读取 B 站关注失败")
        items = (data.get("data") or {}).get("list") or []
        total = (data.get("data") or {}).get("total")
        if not items:
            if total and len(result) < int(total):
                raise RuntimeError("B 站关注列表未读取完整，请重新读取")
            break
        new_items = [{"uid": int(item["mid"]), "uname": item["uname"]}
                     for item in items if int(item["mid"]) not in seen]
        if not new_items:
            raise RuntimeError("B 站关注分页未前进，请重新读取")
        result.extend(new_items)
        seen.update(item["uid"] for item in new_items)
        if len(items) < page_size or (total and len(result) >= int(total)):
            break
        page += 1
    return result


def _live_by_uids(uids: list[int]) -> dict:
    if not uids:
        return {}
    response = requests.post(
        "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
        data=json.dumps({"uids": uids}),
        headers=HEADERS, cookies=_cookies(), timeout=15)
    data = response.json()
    if data.get("code") != 0:
        return {}
    return data.get("data") or {}


def _faces_by_room(uids: list[int]) -> dict[str, str]:
    """按 uid 批量取主播头像；返回 ``room_id -> face``。

    **`getRoomBaseInfo` 不返回 face**（它只给 ``uid``）—— 头像是
    ``get_status_info_by_uids`` 那边的事。以前 `rooms_status()` 直接读
    ``info.get("face")``，拿到的永远是空串，关注栏头像于是一直不显示。
    """
    wanted = [int(uid) for uid in dict.fromkeys(uids) if uid]
    if not wanted:
        return {}
    result: dict[str, str] = {}
    for start in range(0, len(wanted), 100):
        data = _live_by_uids(wanted[start:start + 100])
        for info in data.values():
            if not isinstance(info, dict):
                continue
            room_id = str(info.get("room_id") or "")
            face = str(info.get("face") or "")
            if room_id and face:
                result[room_id] = face
    return result


def _fill_faces(result: dict[str, dict], uids: dict[str, int]) -> None:
    """就地给 ``result`` 补上 face（``uid -> room_id`` 对应关系由 ``uids`` 给）。"""
    missing = [uid for uid in uids.values() if uid]
    if not missing:
        return
    try:
        faces = _faces_by_room(missing)
    except Exception:  # noqa: BLE001
        return                      # 补头像失败不该影响状态刷新本身
    for room_id, info in result.items():
        if not info.get("face"):
            info["face"] = faces.get(room_id, "")


def follow_rooms() -> list[dict]:
    """把关注列表转换成直播间列表（只保留有直播间的账号）。"""
    uid = my_uid()
    if uid is None:
        raise RuntimeError("未登录或登录已失效")
    follows = following(uid)
    infos: dict[int, dict] = {item["uid"]: item for item in follows}
    rooms: list[dict] = []
    uids = list(infos.keys())
    for start in range(0, len(uids), 100):
        data = _live_by_uids(uids[start:start + 100])
        for key, info in data.items():
            try:
                account_uid = int(key)
            except ValueError:
                continue
            room_id = info.get("room_id")
            if not room_id:
                continue
            live = info.get("live_status") == 1
            rooms.append({
                "room_id": str(room_id),
                "uid": account_uid,
                "uname": info.get("uname") or infos.get(account_uid, {}).get("uname", ""),
                "title": info.get("title") or "",
                "live": live,
                "viewers": "",
                "face": info.get("face") or "",
                "cover_url": (info.get("keyframe") if live else info.get("cover")) or info.get("cover") or "",
            })
    rooms.sort(key=lambda room: (not room["live"], room["uname"]))
    return rooms


class FollowLoader(QThread):
    """后台拉取关注列表。"""

    loaded = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.loaded.emit(follow_rooms())
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))


def _rooms_status_base(room_ids: list[str]) -> tuple[dict[str, dict], dict[str, int]]:
    """先取开播状态，头像在状态送达后补齐。"""
    ids = [str(room_id) for room_id in room_ids if str(room_id).isdigit()]
    if not ids:
        return {}, {}
    result: dict[str, dict] = {}
    uids: dict[str, int] = {}
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        response = requests.get(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo",
            params=[("req_biz", "web_room_componet")]
                   + [("room_ids", room_id) for room_id in batch],
            headers=HEADERS, cookies=_cookies(), timeout=15)
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"直播状态接口返回 code={payload.get('code')}")
        by_id = (payload.get("data") or {}).get("by_room_ids") or {}
        for room_id in batch:
            info = by_id.get(room_id)
            if info is None:
                # 短房间号不一定被批量接口识别；单房间接口会先转成长号。
                fallback = room_info(room_id)
                if fallback is not None:
                    result[room_id] = fallback
                continue
            live = info.get("live_status") == 1
            online = info.get("online") or 0
            result[room_id] = {
                "live": live,
                "title": info.get("title") or "",
                "uname": info.get("uname") or "",
                # 这个批量接口**不给 face**，只给 uid；统一在循环外补（见 _fill_faces）
                "face": info.get("face") or "",
                "cover_url": (info.get("keyframe") if live else info.get("cover"))
                              or info.get("cover") or "",
                "viewers": (f"{online / 10000:.1f}万" if online >= 10000 else str(online)) if live else "",
                "live_start_ts": _parse_live_time(info.get("live_time")),
            }
            try:
                uids[room_id] = int(info.get("uid") or 0)
            except (TypeError, ValueError):
                pass
    return result, uids


def rooms_status(room_ids: list[str]) -> dict[str, dict]:
    """批量刷新直播状态：room_id -> {live, title, uname, viewers}。"""
    result, uids = _rooms_status_base(room_ids)
    _fill_faces(result, uids)
    return result


class StatusPoller(QThread):
    """定时批量刷新关注房间的直播状态。"""

    updated = Signal(dict)
    failed = Signal(str)
    status_ready = Signal()

    def __init__(self, room_ids: list[str], parent=None, *, platforms=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)
        self.platforms = platforms or {}

    def run(self) -> None:
        bili_ids = [rid for rid in self.room_ids if str(rid).isdigit()]
        status, uids = {}, {}
        try:
            status, uids = _rooms_status_base(bili_ids)
            if status:
                # 后续补头像会修改原字典，不能改变已排队的状态快照。
                self.updated.emit({rid: dict(info) for rid, info in status.items()})
            missing = set(bili_ids) - status.keys()
            if missing:
                self.failed.emit(f"{len(missing)} 个房间没有返回状态")
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))
        # 各平台查完就送达；失败不阻塞其他平台，也不误标成下播。
        for kind, platform in self.platforms.items():
            ids = [rid for rid in self.room_ids if str(rid).startswith(kind + ":")]
            if not ids:
                continue
            try:
                self.updated.emit(platform.rooms_status(ids))
            except Exception:  # noqa: BLE001
                self.failed.emit(f"{platform.label or kind} 状态获取失败")
        self.status_ready.emit()
        before = {rid: info.get("face") for rid, info in status.items()}
        _fill_faces(status, uids)
        enriched = {rid: info for rid, info in status.items() if info.get("face") != before[rid]}
        if enriched:
            self.updated.emit(enriched)


class AccountLoader(QThread):
    """后台获取当前登录账号信息。"""

    loaded = Signal(dict)
    failed = Signal()

    def run(self) -> None:
        account = my_account()
        if account:
            self.loaded.emit(account)
        else:
            self.failed.emit()


def room_stats(room_id: str) -> dict | None:
    """房间的实时数据：在线人数（高能榜的 onlineNum，和网页一致）与人气值。"""
    try:
        base = requests.get(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo",
            params={"req_biz": "web_room_componet", "room_ids": room_id},
            headers=HEADERS, cookies=_cookies(), timeout=10).json()
        entry = ((base.get("data") or {}).get("by_room_ids") or {}).get(str(room_id)) or {}
        anchor_uid = entry.get("uid")
        popularity = int(entry.get("online") or 0)
        if not anchor_uid:
            return None
        rank = requests.get(
            "https://api.live.bilibili.com/xlive/general-interface/v1/rank/getOnlineGoldRank",
            params={"ruid": anchor_uid, "roomId": room_id, "page": 1, "pageSize": 50},
            headers=HEADERS, cookies=_cookies(), timeout=10).json()
        rank_data = rank.get("data") or {}
    except Exception:  # noqa: BLE001
        return None
    online = int(rank_data.get("onlineNum") or 0)
    return {
        "online": online,
        "online_text": rank_data.get("onlineNumText") or (str(online) if online else ""),
        "popularity": popularity,
    }


def room_quality_options(room_id: str, codec: str = "avc") -> list[dict]:
    """优先使用实际流的档位，旧 web 接口会漏掉2K等新画质。

    必须跟取流用同一个 ``codec``：同一直播间各编码的可用档位不一样（实测 AV1
    只有 ``[10000, 400]``，按 H.264 的档位列出来就会出现点了 720P 取不到流）。
    所以挑的是与 ``_app_play_urls`` 同一条通道同一个编码的 ``accept_qn``；
    HEVC / AV1 取不到就返回空表 —— web 端那个老接口只有 H.264，把它的档位
    当成 HEVC / AV1 的，用户同样会点到一个取不到的档。
    """
    try:
        play = _app_play_info(room_id, 10000, codec)
        for stream in play.get("stream") or []:
            if stream.get("protocol_name") != _app_protocol(codec):
                continue
            # 与 _app_play_urls 选取同一条流，避免列出其他编码/协议的档位。
            entry = _app_codec_entry(stream, codec)
            if entry is None:
                continue
            accepted = set(entry.get("accept_qn") or [])
            standard = {value for _, value in QUALITY_CHOICES}
            result = []
            for item in play.get("g_qn_desc") or []:
                qn = int(item.get("qn") or 0)
                if not qn or qn not in accepted:
                    continue
                names = item.get("media_base_desc") or {}
                desc = (names.get("detail_desc") or {}).get("desc") or item.get("desc") or str(qn)
                option = {"qn": qn, "desc": desc}
                label = (names.get("brief_desc") or {}).get("desc")
                if label and qn in standard:
                    label = item.get("desc") or label
                if label:
                    option["label"] = label
                result.append(option)
            if result:
                return result
            break
    except Exception:  # noqa: BLE001
        pass
    if codec in HLS_ONLY_CODECS:
        return []               # 老 web 接口只有 H.264，不能拿来当这两档的档位
    try:
        response = requests.get(
            "https://api.live.bilibili.com/room/v1/Room/playUrl",
            params={"cid": room_id, "platform": "web", "qn": 10000},
            headers=HEADERS, cookies=_cookies(), timeout=10)
        data = response.json().get("data") or {}
    except Exception:  # noqa: BLE001
        return []
    result = []
    for item in (data.get("quality_description") or []):
        try:
            qn = int(item.get("qn") or 0)
        except (TypeError, ValueError):
            continue
        if qn:
            result.append({"qn": qn, "desc": item.get("desc") or str(qn)})
    return result


class StatsPoller(QThread):
    """批量取"看过人数"（只对画面墙上的房间调用）。"""

    updated = Signal(dict)

    def __init__(self, room_ids: list[str], parent=None):
        super().__init__(parent)
        self.room_ids = [str(item) for item in room_ids]

    def run(self) -> None:
        result = {}
        for room_id in self.room_ids:
            stats = room_stats(room_id)
            if stats:
                result[room_id] = stats
            time.sleep(0.2)          # 稍微错开，避免触发风控
        if result:
            self.updated.emit(result)
