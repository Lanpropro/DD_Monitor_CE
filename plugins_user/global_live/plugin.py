"""Twitch、YouTube 公开直播；不读取浏览器账号或 Cookie。"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
import re
import zlib
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests
from streamlink import Streamlink
from streamlink.plugins.twitch import Twitch, TwitchAPI
from streamlink.plugins.youtube import YouTube
from streamlink.stream.hls import HLSStream

from ddm import plugins as api
from ddm.auto_quality import AUTO_QUALITY
from ddm.global_danmaku import GlobalDanmakuClient, page_json, renderers
from ddm.live_danmaku import USER_AGENT


def public_request(method, url, **kwargs):
    for attempt in range(2):
        response = None
        try:
            response = getattr(requests, method)(url, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if response is not None:
                response.close()
            if attempt:
                raise


def official_url(text, hosts):
    parts = urlsplit(text)
    if (parts.scheme not in ("http", "https") or parts.hostname not in hosts or
            parts.username or parts.password or parts.port not in (None, 80, 443)):
        raise ValueError("请使用平台官方直播链接")
    return parts


def image_url(value, hosts):
    parts = urlsplit(str(value or ""))
    host = parts.hostname or ""
    return str(value) if (parts.scheme == "https" and not parts.username and not parts.password and
        any(host == domain or host.endswith("." + domain) for domain in hosts)) else ""


def thumbnail(data, hosts):
    choices = sorted(data.get("thumbnails", []), key=lambda item: item.get("width", 0), reverse=True)
    return next((url for item in choices if (url := image_url(item.get("url"), hosts))), "")


class LiveYouTube(YouTube):
    def _get_res(self, url):
        response = super()._get_res(url)
        player = page_json(response.text, "ytInitialPlayerResponse")
        details = player.get("videoDetails", {})
        broadcast = player.get("microformat", {}).get("playerMicroformatRenderer", {}).get("liveBroadcastDetails", {})
        if details.get("isLiveContent") is False or not (details.get("isLive") or broadcast.get("isLiveNow")):
            raise ValueError("YouTube broadcast is not currently live")
        return response


class PublicLivePlatform(api.Platform):
    playback_mode = "stream"
    hosts = ()

    def __init__(self):
        self._qualities = {}

    def matches(self, room_id):
        text = str(room_id or "").strip()
        if text.startswith(self.kind + ":"):
            return True
        try:
            return urlsplit(text).hostname in self.hosts
        except ValueError:
            return False

    def room_quality_options(self, room_id):
        return [{"qn": AUTO_QUALITY, "desc": "自动（根据网络选择流畅的最高画质）", "label": "自动"}] + [
                {key: item[key] for key in ("qn", "desc", "label", "bandwidth") if key in item} for item in
                self._qualities.get(room_id, [{"qn": 10000, "desc": "最高可用", "label": "最高可用"}])]

    def rooms_status(self, room_ids):
        result = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self.room_info, rid): rid for rid in room_ids}
            for future in as_completed(futures):
                try:
                    result[futures[future]] = future.result().as_dict()
                except Exception:  # noqa: BLE001
                    continue  # 网络失败保留上次状态
        if room_ids and not result:
            raise RuntimeError(f"{self.label} 状态获取失败")
        return result

    def _quality_streams(self, streams):
        options = []
        for name, stream in streams.items():
            if name in ("best", "worst") or not isinstance(stream, HLSStream):
                continue
            master = stream.multivariant
            playlist = next((item for item in master.playlists if item.uri == stream.to_url()), None) if master else None
            info = playlist.stream_info if playlist else None
            resolution = info.resolution if info else None
            if not resolution or not any(codec.startswith(("avc1", "avc3")) for codec in info.codecs):
                continue
            width, height = resolution.width, resolution.height
            fps = info.framerate or 0
            desc = f"{name} · {width}x{height}" + (f" · {fps:g}fps" if fps else "")
            options.append({"key": name, "desc": desc, "label": name,
                            "pixels": width * height, "fps": fps, "bandwidth": info.bandwidth or 0})
        options.sort(key=lambda item: (item["pixels"], item["fps"], item["bandwidth"]), reverse=True)
        for index, item in enumerate(options):
            item["qn"] = 10000 if index == 0 else 5000000 + (zlib.crc32(item["key"].encode()) & 0xFFFFFF)
        return options

    def play_url(self, room_id, quality=10000, *, preview=False):
        canonical = self.normalize(room_id)
        session = Streamlink({"http-timeout": 8, "webbrowser": False})
        session.http.request = partial(session.http.request, retries=1)
        try:
            parser = self.parser(session, self.room_url(canonical))
            streams = parser.streams()
            options = self._quality_streams(streams)
            if not options:
                raise RuntimeError("没有可用的公开 H.264 直播流")
            self._qualities[canonical] = options
            selected = options[-1] if preview or quality == AUTO_QUALITY else next(
                (item for item in options if item["qn"] == quality), options[0])
            url = streams[selected["key"]].to_url()
            return url, selected["qn"], self.kind, {"User-Agent": USER_AGENT, "Referer": self.origin}
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(f"{self.label} 直播取流失败，请稍后重试") from error
        finally:
            session.http.close()

    def preview_url(self, room_id):
        return self.play_url(room_id, preview=True)

    def danmaku_client(self, room_id, parent=None):
        return GlobalDanmakuClient(room_id, self, parent)


class TwitchPlatform(PublicLivePlatform):
    kind = "twitch"
    label = "Twitch"
    hosts = ("twitch.tv", "www.twitch.tv", "m.twitch.tv", "player.twitch.tv")
    origin = "https://www.twitch.tv/"
    parser = Twitch

    def normalize(self, room_id):
        text = str(room_id or "").strip()
        raw = text[7:] if text.startswith("twitch:") else text
        if "://" in raw:
            parts = official_url(raw, self.hosts)
            if parts.hostname == "player.twitch.tv":
                query = parse_qs(parts.query)
                channels = query.get("channel", [])
                if len(channels) != 1 or "video" in query:
                    raise ValueError("请使用 Twitch 频道直播链接")
                raw = channels[0]
            else:
                raw = parts.path.strip("/")
        if (not re.fullmatch(r"[A-Za-z0-9_]{1,25}", raw) or
                raw.lower() in ("directory", "videos", "downloads", "settings", "subscriptions", "inventory", "search")):
            raise ValueError("请填写 twitch:频道名，或 Twitch 官方频道链接")
        return "twitch:" + raw.lower()

    def room_url(self, room_id):
        return self.origin + self.normalize(room_id).split(":", 1)[1]

    def room_info(self, room_id):
        canonical = self.normalize(room_id)
        query = """query($login:String!){user(login:$login){id login displayName
            profileImageURL(width:300) lastBroadcast{title}
            stream{id type previewImageURL(width:640,height:360)}}}"""
        try:
            with public_request("post", "https://gql.twitch.tv/gql", timeout=(4, 8),
                    headers={"Client-ID": TwitchAPI.CLIENT_ID, "User-Agent": USER_AGENT},
                    json={"query": query, "variables": {"login": canonical.split(":", 1)[1]}}) as response:
                payload = response.json()
            if payload.get("errors"):
                raise ValueError("Twitch query rejected")
            user = payload["data"]["user"]
            if not isinstance(user, dict) or "stream" not in user:
                raise ValueError("Missing Twitch channel")
            stream = user["stream"] or {}
            return api.RoomInfo(room_id=canonical, uname=user["displayName"],
                title=(user.get("lastBroadcast") or {}).get("title", "Twitch 直播"),
                live=stream.get("type") == "live", platform=self.kind,
                face=image_url(user.get("profileImageURL"), ("jtvnw.net",)),
                cover_url=image_url(stream.get("previewImageURL"), ("jtvnw.net",)),
                extra={"playback_mode": self.playback_mode, "live_known": True})
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("Twitch 频道信息获取失败，请检查频道名或稍后重试") from error


class YouTubePlatform(PublicLivePlatform):
    kind = "youtube"
    label = "YouTube"
    hosts = ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
    origin = "https://www.youtube.com/"
    parser = LiveYouTube
    image_hosts = ("ytimg.com", "ggpht.com", "googleusercontent.com")

    def normalize(self, room_id):
        text = str(room_id or "").strip()
        raw = text[8:] if text.startswith("youtube:") else text
        if "://" in raw:
            parts = official_url(raw, self.hosts)
            path = unquote(parts.path).strip("/").split("/")
            if parts.hostname == "youtu.be" and len(path) == 1:
                raw = path[0]
            elif path == ["watch"]:
                values = parse_qs(parts.query).get("v", [])
                raw = values[0] if len(values) == 1 else ""
            elif len(path) == 2 and path[0] in ("live", "embed", "shorts") and re.fullmatch(r"[A-Za-z0-9_-]{11}", path[1]):
                raw = path[1]
            elif path[0] == "channel" and len(path) in (2, 3) and re.fullmatch(r"UC[A-Za-z0-9_-]{22}", path[1]) and (
                    len(path) == 2 or path[2] in ("live", "streams")):
                raw = path[1]
            elif path[0].startswith("@") and (len(path) == 1 or (len(path) == 2 and path[1] in ("live", "streams"))):
                raw = path[0]
            else:
                raw = ""
        valid = re.fullmatch(r"[A-Za-z0-9_-]{11}|UC[A-Za-z0-9_-]{22}", raw)
        handle = raw.startswith("@") and 2 <= len(raw) <= 101 and not re.search(r"[\s/:?#%\\]", raw)
        if not valid and not handle:
            raise ValueError("请使用 YouTube 直播视频、@频道或 /channel/ 频道链接")
        return "youtube:" + raw

    def room_url(self, room_id):
        raw = self.normalize(room_id).split(":", 1)[1]
        if raw.startswith("@"):
            return self.origin + quote(raw, safe="@") + "/live"
        if raw.startswith("UC") and len(raw) == 24:
            return self.origin + "channel/" + raw + "/live"
        return self.origin + "watch?v=" + raw

    def room_info(self, room_id):
        canonical = self.normalize(room_id)
        try:
            with public_request("get", self.room_url(canonical), params={"hl": "en"},
                    headers={"User-Agent": USER_AGENT}, timeout=(4, 8)) as response:
                page = response.text
            player = page_json(page, "ytInitialPlayerResponse")
            data = page_json(page, "ytInitialData")
            details = player.get("videoDetails", {})
            if not details:
                channel = next(renderers(data, "channelMetadataRenderer"), {})
                if not channel.get("title") or not canonical.split(":", 1)[1].startswith(("@", "UC")):
                    raise ValueError("Missing YouTube live channel")
                return api.RoomInfo(room_id=canonical, uname=channel["title"], platform=self.kind,
                    face=thumbnail(channel.get("avatar", {}), self.image_hosts),
                    extra={"playback_mode": self.playback_mode, "live_known": True})
            broadcast = player.get("microformat", {}).get("playerMicroformatRenderer", {}).get("liveBroadcastDetails", {})
            live = bool(details.get("isLive") or broadcast.get("isLiveNow"))
            if details.get("isLiveContent") is False or not (
                    details.get("isLiveContent") or live or broadcast.get("startTimestamp")):
                raise ValueError("This video is not a live broadcast")
            owner = next((item for item in renderers(data, "videoOwnerRenderer") if
                item.get("navigationEndpoint", {}).get("browseEndpoint", {}).get("browseId") == details.get("channelId")), {})
            return api.RoomInfo(room_id=canonical, uname=details["author"], title=details["title"],
                live=live, platform=self.kind,
                face=thumbnail(owner.get("thumbnail", {}), self.image_hosts),
                cover_url=thumbnail(details.get("thumbnail", {}), self.image_hosts),
                extra={"playback_mode": self.playback_mode, "live_known": True})
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("YouTube 直播信息获取失败；请使用公开直播或频道链接") from error


class GlobalLivePlugin(api.Plugin):
    def on_load(self, context):
        context.register_platform(TwitchPlatform())
        context.register_platform(YouTubePlatform())


plugin = GlobalLivePlugin()
