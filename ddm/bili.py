"""B 站直播接口：房间信息与播放地址。

取流走 web 端 playUrl —— app-room 接口返回的 FLV 地址现在会被 CDN 拒绝（403）。
CDN 地址统一从 https 改成 http：随程序打包的 VLC 插件集里没有 TLS 插件。
"""
import hashlib
import json
import sys
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

# 登录后的 SESSDATA，带上它才能解锁原画、拉取关注列表
SESSION_DATA = ""
_UID_CACHE: dict = {"uid": None}
_WBI_CACHE: dict = {"key": "", "expires": 0.0}
_WBI_KEY_INDEX = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
]


def set_sessdata(value: str) -> None:
    global SESSION_DATA
    SESSION_DATA = value or ""
    _UID_CACHE["uid"] = None          # 换了账号，UID 缓存作废


def _cookies() -> dict:
    return {"SESSDATA": SESSION_DATA} if SESSION_DATA else {}


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
    return {
        "room_id": str(room_id),
        "uname": info.get("uname") or f"房间 {room_id}",
        "title": info.get("title") or "",
        "live": live,
        "viewers": viewers,
        "face": info.get("face") or "",
        "live_start_ts": _parse_live_time(info.get("live_time")),
        "cover_url": (info.get("keyframe") if live else info.get("cover")) or info.get("cover") or "",
    }


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


def danmaku_conf(room_id: str) -> tuple[int, str, list]:
    """弹幕连接要用的东西：(真实房间号, token, 服务器列表)。

    优先使用带 WBI 签名的 getDanmuInfo；失败时再降级到老 getConf。
    """
    real_id = _resolve_room_id(room_id)
    data = {}
    key = _wbi_key()
    if key:
        try:
            response = requests.get(
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo",
                params=_wbi_signed_params({"id": real_id, "type": 0}, key),
                headers=HEADERS, cookies=_cookies(), timeout=10)
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
                headers=HEADERS, cookies=_cookies(), timeout=10)
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
    """快速确认地址真的能拉流（CDN 防盗链规则按来源通道不同）。"""
    try:
        response = requests.get(url, headers=headers, cookies=_cookies(),
                                stream=True, timeout=8)
        chunk = next(response.iter_content(16), b"")
        response.close()
        return response.status_code == 200 and bool(chunk)
    except Exception:  # noqa: BLE001
        return False


def _web_play_url(room_id: str, quality: int) -> tuple[str, int]:
    """web 端接口：未登录固定 720P，登录后按 qn 给。"""
    response = requests.get(
        "https://api.live.bilibili.com/room/v1/Room/playUrl",
        params={"cid": room_id, "platform": "web", "qn": quality},
        headers=HEADERS, cookies=_cookies(), timeout=10)
    data = response.json()
    if data.get("code") != 0:
        raise RuntimeError(f"接口返回 code={data.get('code')} {data.get('message')}")
    payload = data["data"]
    url = payload["durl"][0]["url"]
    current = int(payload.get("current_qn") or 0)
    return url, current


def _app_play_url(room_id: str, quality: int) -> tuple[str, int]:
    """app-room 接口：尊重 qn（登录后能拿到原画）。"""
    params = {
        "appkey": "iVGUTjsxvpLeuDCf", "build": 6250300, "c_locale": "zh_CN",
        "channel": "bili", "codec": 0, "device": "android", "device_name": "MuMu",
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
    streams = ((data.get("data") or {}).get("playurl_info") or {}).get("playurl", {}).get("stream", [])
    for stream in streams:
        if stream.get("protocol_name") != "http_stream":
            continue
        codec = stream["format"][0]["codec"][0]
        info = codec["url_info"][0]
        url = info["host"] + codec["base_url"] + info["extra"]
        return url, int(codec.get("current_qn") or 0)
    raise RuntimeError("app-room 接口没有返回 FLV 地址")


class Cancelled(Exception):
    """这次取流已经被调用方作废（鼠标早就移开了、格子被停掉了）。

    只用它做「安静收尾」的信号，不当成失败上报 —— 见 StreamResolver.cancel()。
    """


def play_url(room_id: str, quality: int = 250,
             cancelled=None) -> tuple[str, int, str, dict]:
    """取可播放的 http FLV 地址，附带接口实际给到的画质。

    优先用尊重画质的 app-room 接口（App UA、不带 Referer 拉流）；
    失败时退回 web 端接口（Chrome UA + Referer）。VLC 插件集没有 TLS，
    所以统一把 https 换成 http。

    返回 ``(地址, 实际画质, 通道名, 请求头)``。请求头必须一起带走：插件要
    拿这个地址去录像，头不对 CDN 直接 403。

    ``cancelled`` 是个可选回调，返回 True 表示这次取流已经没人要了：每换一条
    通道、每次探测地址之前都会问一次，问到 True 就抛 Cancelled 早点收工，
    不把带宽和连接白耗在后面几条通道上。
    """
    def _cancelled() -> bool:
        return bool(cancelled is not None and cancelled())

    errors = []
    for source, profile, headers in ((_app_play_url, "app", STREAM_APP),
                                     (_web_play_url, "web", STREAM_WEB)):
        if _cancelled():
            raise Cancelled()
        try:
            url, current = source(room_id, quality)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{source.__name__}: {error}")
            continue
        if _cancelled():
            raise Cancelled()
        http_url = url.replace("https://", "http://", 1)
        if _fetchable(http_url, headers):
            if _cancelled():               # 探测期间被作废：别把这个地址交出去
                raise Cancelled()
            print(f"[取流] {room_id} 通道={profile} 请求画质={quality} 实际给到={current}",
                  file=sys.stderr, flush=True)
            return http_url, current, profile, dict(headers)
        errors.append(f"{source.__name__}: 地址不可用（CDN 拒绝）")
    raise RuntimeError("；".join(errors) or "取流失败")


class StreamResolver(QThread):
    """在后台线程取流，避免阻塞界面。"""

    resolved = Signal(str, str, int, str, list)   # room_id, url, 实际画质, 通道, 可选档位
    failed = Signal(str, str)       # room_id, 原因

    def __init__(self, room_id: str, quality: int = 250, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.quality = quality
        self.headers: dict = {}          # 本次取流的请求头，交给播放器/插件
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

    def run(self) -> None:
        if self._cancelled:
            return
        try:
            url, current, profile, headers = play_url(self.room_id, self.quality,
                                                      cancelled=self.is_cancelled)
        except Cancelled:
            return                       # 作废：不发结果，也不算失败
        except Exception as error:  # noqa: BLE001
            if not self._cancelled:
                self.failed.emit(self.room_id, str(error))
            return
        if self._cancelled:
            return
        options = room_quality_options(self.room_id)
        if self._cancelled:
            return
        self.headers = headers
        if options:
            print(f"[画质档位] {self.room_id}: "
                  + " / ".join(f"{item['desc']}({item['qn']})" for item in options),
                  file=sys.stderr, flush=True)
        self.resolved.emit(self.room_id, url, current, profile, options)


class InfoResolver(QThread):
    """在后台线程查房间信息（添加直播间时用）。"""

    resolved = Signal(dict)
    failed = Signal(str)

    def __init__(self, room_id: str, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)

    def run(self) -> None:
        info = room_info(self.room_id)
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


def following(uid: int, page_size: int = 50, max_pages: int = 20) -> list[dict]:
    """拉取关注列表（分页）。"""
    result: list[dict] = []
    for page in range(1, max_pages + 1):
        response = requests.get(
            "https://api.bilibili.com/x/relation/followings",
            params={"vmid": uid, "pn": page, "ps": page_size, "order": "desc"},
            headers=HEADERS, cookies=_cookies(), timeout=10)
        data = response.json()
        if data.get("code") != 0:
            break
        items = (data.get("data") or {}).get("list") or []
        if not items:
            break
        result.extend({"uid": int(item["mid"]), "uname": item["uname"]} for item in items)
        if len(items) < page_size:
            break
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


def rooms_status(room_ids: list[str]) -> dict[str, dict]:
    """批量刷新直播状态：room_id -> {live, title, uname, viewers}。"""
    ids = [int(room_id) for room_id in room_ids if str(room_id).isdigit()]
    if not ids:
        return {}
    response = requests.post(
        "https://api.live.bilibili.com/room/v2/Room/get_by_ids",
        data=json.dumps({"ids": ids}), headers=HEADERS, cookies=_cookies(), timeout=15)
    by_id = response.json().get("data") or {}
    uid_of: dict[str, int] = {}
    for key, item in by_id.items():
        try:
            uid_of[str(key)] = int(item["uid"])
        except (KeyError, TypeError, ValueError):
            continue
    if not uid_of:
        return {}
    response = requests.post(
        "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
        data=json.dumps({"uids": list(uid_of.values())}),
        headers=HEADERS, cookies=_cookies(), timeout=15)
    status = response.json().get("data") or {}
    result: dict[str, dict] = {}
    for room_id, uid in uid_of.items():
        info = status.get(str(uid))
        if not info:
            continue
        live = info.get("live_status") == 1
        online = info.get("online") or 0
        result[room_id] = {
            "live": live,
            "title": info.get("title") or "",
            "uname": info.get("uname") or "",
            "face": info.get("face") or "",
            # 开播时用直播画面当封面，没开播用房间封面（关注列表的缩略图要用）
            "cover_url": (info.get("keyframe") if live else info.get("cover"))
                          or info.get("cover") or "",
            "viewers": (f"{online / 10000:.1f}万" if online >= 10000 else str(online)) if live else "",
            "live_start_ts": _parse_live_time(info.get("live_time")),
        }
    return result


class StatusPoller(QThread):
    """定时批量刷新关注房间的直播状态。"""

    updated = Signal(dict)
    failed = Signal(str)

    def __init__(self, room_ids: list[str], parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        try:
            self.updated.emit(rooms_status(self.room_ids))
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error))


class AccountLoader(QThread):
    """后台获取当前登录账号信息。"""

    loaded = Signal(dict)

    def run(self) -> None:
        account = my_account()
        if account:
            self.loaded.emit(account)


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


def room_quality_options(room_id: str) -> list[dict]:
    """这个直播间实际提供的画质档位（web 接口里的 quality_description）。"""
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
