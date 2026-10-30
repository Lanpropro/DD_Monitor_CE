"""Android Bilibili provider; no Qt, desktop config, cookies or third-party packages.

The app-room request and CDN header distinction follow ddm/bili.py. Prefer AVC
HLS for Android; use AVC FLV if the room exposes no HLS channel.
"""
import json
import re
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
APP_UA = ("Mozilla/5.0 BiliDroid/6.25.0 (bbcallen@gmail.com) os/android model/MuMu "
          "mobi_app/android build/6250300 channel/bili innerVer/6250300 osVer/6.0.1 network/2")
API_HEADERS = {"User-Agent": WEB_UA, "Referer": "https://live.bilibili.com/"}
API_ROOT = "https://api.live.bilibili.com"


def validate_room_id(value):
    room_id = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,12}", room_id) or int(room_id) == 0:
        raise ValueError("请输入有效的 B 站直播间数字房间号")
    return str(int(room_id))


def _get(path, params):
    request = Request(API_ROOT + path + "?" + urlencode(params), headers=API_HEADERS)
    with urlopen(request, timeout=12) as response:
        payload = json.load(response)
    if payload.get("code") != 0:
        raise ValueError("B 站接口暂不可用（%s）" % payload.get("code"))
    return payload.get("data") or {}


def select_stream(play):
    for protocol in ("http_hls", "http_stream"):
        for stream in play.get("stream") or []:
            if stream.get("protocol_name") != protocol:
                continue
            for fmt in stream.get("format") or []:
                for entry in fmt.get("codec") or []:
                    if entry.get("codec_name") != "avc":
                        continue
                    urls = list(dict.fromkeys(
                        item["host"] + entry["base_url"] + item.get("extra", "")
                        for item in entry.get("url_info") or []
                        if item.get("host") and entry.get("base_url")))
                    if urls:
                        return {"urls": urls, "quality": int(entry.get("current_qn") or 0),
                                "protocol": protocol, "headers": {"User-Agent": APP_UA}}
    raise ValueError("该直播间暂未提供可播放的 H.264 直播流")


def resolve(value):
    room_id = validate_room_id(value)
    room = _get("/room/v1/Room/room_init", {"id": room_id})
    if room.get("live_status") != 1:
        raise ValueError("该直播间尚未开播")
    real_id = str(room["room_id"])
    data = _get("/xlive/app-room/v2/index/getRoomPlayInfo", {
        "appkey": "iVGUTjsxvpLeuDCf", "build": 6250300, "c_locale": "zh_CN",
        "channel": "bili", "codec": 0, "device": "android", "device_name": "MuMu",
        "dolby": 1, "format": "0,2", "free_type": 0, "http": 1, "mask": 0,
        "mobi_app": "android", "network": "wifi", "no_playurl": 0, "only_audio": 0,
        "only_video": 0, "platform": "android", "play_type": 0, "protocol": "0,1",
        "qn": 250, "room_id": real_id, "s_locale": "zh_CN",
        "statistics": '{"appId":1,"platform":3,"version":"6.25.0","abtest":""}',
        "ts": int(time.time()),
    })
    play = ((data.get("playurl_info") or {}).get("playurl") or {})
    result = select_stream(play)
    result["room_id"] = real_id
    return result


def resolve_json(value):
    try:
        return json.dumps({"ok": True, **resolve(value)}, ensure_ascii=False)
    except ValueError as error:
        return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)
    except (URLError, TimeoutError, OSError):
        return json.dumps({"ok": False, "error": "网络连接失败，请检查网络后重试"}, ensure_ascii=False)
