"""国内公开直播流：虎牙、斗鱼、抖音关注卡片与 VLC 格子内播放。"""
import base64
from html import unescape
import json
import re
import uuid
import zlib
from urllib.parse import parse_qsl, urlsplit

import requests
from streamlink import Streamlink
from streamlink.plugins.huya import Huya
from streamlink.plugins.douyu import Douyu
from streamlink.plugins.douyin import Douyin
from streamlink.stream.http import HTTPStream

from ddm import plugins as api


class LiveQualityPlatform(api.Platform):
    def __init__(self):
        self._qualities = {}                  # 只保存档位元数据，不保存带签名的地址

    def room_quality_options(self, room_id: str) -> list[dict]:
        return [{key: value for key, value in item.items() if key in ("qn", "desc", "label")} for item in
                self._qualities.get(room_id, [{"qn": 10000, "desc": "最高可用"}])]

    def _select_quality(self, room_id, quality, preview):
        options = self._qualities[room_id]
        if preview:
            return options[-1]
        return next((item for item in options if item["qn"] == quality), options[0])

    def preview_url(self, room_id: str) -> tuple:
        return self.play_url(room_id, 10000, preview=True)


class HuyaPlatform(LiveQualityPlatform):
    kind = "huya"
    label = "虎牙"
    playback_mode = "stream"

    def matches(self, room_id: str) -> bool:
        text = str(room_id or "").strip()
        if text.startswith("huya:"):
            return True
        try:
            parts = urlsplit(text)
            return parts.scheme in ("http", "https") and parts.hostname in (
                "www.huya.com", "huya.com", "m.huya.com")
        except ValueError:
            return False

    def normalize(self, room_id: str) -> str:
        text = str(room_id or "").strip()
        raw = text[5:] if text.startswith("huya:") else text
        if "://" in raw:
            parts = urlsplit(raw)
            if (parts.scheme not in ("http", "https") or
                    parts.hostname not in ("www.huya.com", "huya.com", "m.huya.com") or
                    parts.username or parts.password or parts.port not in (None, 80, 443)):
                raise ValueError("请使用虎牙官方直播间链接")
            raw = parts.path.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", raw):
            raise ValueError("请填写 huya:房间号，或虎牙官方直播间链接")
        return f"huya:{raw}"

    def _streams(self, room_id: str, quality: int = 250, *, preview=False):
        session = Streamlink({"http-timeout": 8})
        parser = Huya(session, self.room_url(room_id))
        try:
            page = session.http.get(parser.url).text
            config = re.search(r"\bvar\s+hyPlayerConfig\s*=\s*\{", page)
            if config is None:
                return session, parser, {}
            script = page[config.end():].split("</script>", 1)[0]
            match = re.search(r'"?stream"?\s*:\s*', script)
            if match is None:
                return session, parser, {}
            data, _end = json.JSONDecoder().raw_decode(script[match.end():].lstrip())
            if isinstance(data, str):
                data = json.loads(base64.b64decode(data, validate=True))
            options = [{"qn": 10000 if item["iBitRate"] == 0 else 1000000 + item["iBitRate"],
                        "desc": item.get("sDisplayName") or (
                            "原画" if item["iBitRate"] == 0 else f"{item['iBitRate']} kbps"),
                        "rate": item["iBitRate"]}
                       for item in data.get("vMultiStreamInfo", [])
                       if isinstance(item.get("iBitRate"), int) and item["iBitRate"] >= 0]
            if not any(item["rate"] == 0 for item in options):
                options.append({"qn": 10000, "desc": "原画", "rate": 0})
            self._qualities[room_id] = sorted(options, key=lambda item: (
                item["rate"] == 0, item["rate"]), reverse=True)
            selected = self._select_quality(room_id, quality, preview)
            bitrate = selected["rate"]
            streams = {}
            for info in data.get("data", [{}])[0].get("gameStreamInfoList", []):
                # 使用网页明确提供的 HLS 线路；签名参数仍交给固定版本的 Streamlink。
                base = info.get("sHlsUrl")
                if not base:
                    continue
                name = info["sStreamName"]
                qs = dict(parse_qsl(unescape(info["sHlsAntiCode"])))
                params = parser._get_stream_params(qs.get("fm", ""), qs.get("fs", ""),
                    qs.get("ctype", "huya_live"), qs.get("wsTime", ""), name, bitrate)
                url = f"{base}/{name}.{info['sHlsUrlSuffix']}"
                if url.startswith("//"):
                    url = "https:" + url
                stream = HTTPStream(session, url, params=params)
                stream.ddm_quality = selected["qn"]
                streams[f"{info['sCdnType'].lower()}_source"] = stream
        except Exception as error:  # noqa: BLE001
            session.http.close()
            raise RuntimeError("虎牙房间获取失败，请稍后重试") from error
        return session, parser, streams

    def room_info(self, room_id: str) -> api.RoomInfo:
        canonical = self.normalize(room_id)
        raw = canonical.split(":", 1)[1]
        try:
            with requests.get(self.room_url(canonical), headers={
                    "User-Agent": "Mozilla/5.0", "Referer": "https://www.huya.com/"},
                    timeout=(4, 8)) as response:
                response.raise_for_status()
                page = response.text
            def page_data(name):
                match = re.search(r"\b" + name + r"\s*=\s*", page)
                if match is None:
                    raise ValueError("Missing room data")
                data, _end = json.JSONDecoder().raw_decode(page[match.end():].lstrip())
                if not isinstance(data, dict):
                    raise ValueError("Invalid room data")
                return data

            room = page_data("TT_ROOM_DATA")
            profile = page_data("TT_PROFILE_INFO")
            if not isinstance(room.get("isOn"), bool):
                raise ValueError("Missing live status")

            def image_url(value):
                url = str(value or "")
                if url.startswith("//"):
                    url = "https:" + url
                parts = urlsplit(url)
                host = parts.hostname or ""
                if (parts.scheme in ("http", "https") and not parts.username and
                        not parts.password and (host == "msstatic.com" or host.endswith(".msstatic.com"))):
                    return url
                return ""

            return api.RoomInfo(
                room_id=canonical, uname=profile.get("nick") or f"虎牙 · {raw}",
                title=room.get("introduction") or "虎牙直播间", live=room["isOn"], platform=self.kind,
                face=image_url(profile.get("avatar")), cover_url=image_url(room.get("screenshot")),
                extra={"playback_mode": self.playback_mode, "live_known": True},
            )
        except (requests.RequestException, ValueError) as error:
            raise RuntimeError("虎牙房间信息获取失败，请稍后重试") from error

    def rooms_status(self, room_ids: list) -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self.room_info, rid): rid for rid in room_ids}
            for future in as_completed(futures):
                try:
                    result[futures[future]] = future.result().as_dict()
                except Exception:  # noqa: BLE001
                    continue                    # 请求失败保留旧状态，不误报下播
        if room_ids and not result:
            raise RuntimeError("虎牙状态获取失败")
        return result

    def play_url(self, room_id: str, quality: int = 250, *, preview=False) -> tuple:
        session, _parser, streams = self._streams(room_id, quality, preview=preview)
        try:
            if not streams:
                raise RuntimeError("虎牙房间未开播，或没有可用的公开直播流")
            headers = {"User-Agent": session.http.headers["User-Agent"],
                       "Referer": "https://www.huya.com/"}
            # HLS 分片交给 FFmpeg 转封装，避免旧 VLC 处理虎牙 FLV 时间戳时停帧。
            # 不写 Cookie、不保存带签名的 URL。
            candidates = list(streams.values())
            seen = set()
            for stream in candidates:
                url = stream.to_url()
                if url in seen:
                    continue
                seen.add(url)
                if len(seen) > 3:
                    break
                try:
                    with requests.get(url, headers=headers, stream=True, timeout=(4, 6)) as response:
                        response.raise_for_status()
                        if next(response.iter_content(7), b"") != b"#EXTM3U":
                            continue
                        qn = getattr(stream, "ddm_quality", 10000)
                        return response.url, qn if isinstance(qn, int) else 10000, "huya", headers
                except requests.RequestException:
                    continue
            raise RuntimeError("虎牙直播线路暂不可用，请重试")
        finally:
            session.http.close()

    def room_url(self, room_id: str) -> str:
        canonical = self.normalize(room_id)
        return f"https://www.huya.com/{canonical.split(':', 1)[1]}"


class NumericLivePlatform(LiveQualityPlatform):
    """斗鱼、抖音共用的数字房间链接、原画和状态查询。"""
    hosts = ()
    image_hosts = ()

    def matches(self, room_id: str) -> bool:
        text = str(room_id or "").strip()
        if text.startswith(self.kind + ":"):
            return True
        try:
            parts = urlsplit(text)
            return parts.scheme in ("http", "https") and parts.hostname in self.hosts
        except ValueError:
            return False

    def normalize(self, room_id: str) -> str:
        text = str(room_id or "").strip()
        raw = text[len(self.kind) + 1:] if text.startswith(self.kind + ":") else text
        if "://" in raw:
            parts = urlsplit(raw)
            if (parts.scheme not in ("http", "https") or parts.hostname not in self.hosts or
                    parts.username or parts.password or parts.port not in (None, 80, 443)):
                raise ValueError(f"请使用{self.label}官方直播间链接")
            raw = self._room_id_from_url(parts)
        if not re.fullmatch(r"[0-9]{1,20}", raw):
            raise ValueError(f"请填写 {self.kind}:房间号，或{self.label}官方直播间链接")
        return f"{self.kind}:{raw}"

    def _room_id_from_url(self, parts) -> str:
        return parts.path.strip("/")

    def room_url(self, room_id: str) -> str:
        return f"https://{self.hosts[0]}/{self.normalize(room_id).split(':', 1)[1]}"

    def _image_url(self, value) -> str:
        if isinstance(value, dict):
            value = next(iter(value.get("url_list", [])), "")
        url = str(value or "")
        if url.startswith("//"):
            url = "https:" + url
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (parts.scheme in ("http", "https") and not parts.username and not parts.password and
                any(host == domain or host.endswith("." + domain) for domain in self.image_hosts)):
            return url
        return ""

    def rooms_status(self, room_ids: list) -> dict:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        result = {}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(self.room_info, rid): rid for rid in room_ids}
            for future in as_completed(futures):
                try:
                    result[futures[future]] = future.result().as_dict()
                except Exception:  # noqa: BLE001
                    continue                    # 请求失败保留旧状态
        if room_ids and not result:
            raise RuntimeError(f"{self.label}状态获取失败")
        return result

    def play_url(self, room_id: str, quality: int = 250, *, preview=False) -> tuple:
        session = Streamlink({"http-timeout": 8})
        try:
            streams = self._streams(session, room_id, quality, preview=preview)
            if not streams:
                raise RuntimeError(f"{self.label}房间未开播，或没有可用的公开直播流")
            stream = streams.get("worst" if preview else "best") or next(iter(streams.values()))
            qn = getattr(stream, "ddm_quality", 10000)
            qn = qn if isinstance(qn, int) else 10000
            url = stream.to_url()
            headers = {"User-Agent": session.http.headers["User-Agent"],
                       "Referer": f"https://{self.hosts[0]}/"}
            if self.kind == "douyu":
                # 斗鱼部分地址只允许一个消费者，提前探流会使随后播放器连接短时间断开。
                return url, qn, self.kind, headers
            with session.http.get(url, headers=headers, stream=True, timeout=(4, 6)) as response:
                response.raise_for_status()
                if next(response.iter_content(3), b"") != b"FLV":
                    raise RuntimeError(f"{self.label}直播线路暂不可用，请重试")
                return response.url, qn, self.kind, headers
        except RuntimeError:
            raise
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(f"{self.label}取流失败，请检查房间链接或稍后重试") from error
        finally:
            session.http.close()


class DouyuPlatform(NumericLivePlatform):
    kind = "douyu"
    label = "斗鱼"
    hosts = ("www.douyu.com", "douyu.com", "m.douyu.com")
    image_hosts = ("douyucdn.cn", "douyu.com")

    def room_info(self, room_id: str) -> api.RoomInfo:
        canonical = self.normalize(room_id)
        raw = canonical.split(":", 1)[1]
        try:
            with requests.get(f"https://www.douyu.com/betard/{raw}", headers={
                    "User-Agent": "Mozilla/5.0", "Referer": "https://www.douyu.com/"},
                    timeout=(4, 8)) as response:
                response.raise_for_status()
                room = response.json()["room"]
            if type(room.get("show_status")) is not int or not room.get("room_id"):
                raise ValueError("Missing room status")
            return api.RoomInfo(room_id=canonical, uname=room.get("nickname") or f"斗鱼 · {raw}",
                title=room.get("room_name") or "斗鱼直播间", platform=self.kind,
                live=room["show_status"] == 1 and not room.get("videoLoop"),
                face=self._image_url(room.get("owner_avatar") or room.get("avatar_small")),
                cover_url=self._image_url(room.get("room_pic") or room.get("coverSrc")),
                extra={"playback_mode": "stream", "live_known": True})
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("斗鱼房间信息获取失败，请稍后重试") from error

    def _streams(self, session, room_id, quality=250, *, preview=False):
        if not self.room_info(room_id).live:
            return {}
        parser = Douyu(session, self.room_url(room_id))
        raw = self.normalize(room_id).split(":", 1)[1]
        data = self._request_source(parser, raw)
        # 网页默认的 P2P 边缘线路可能很快断流，优先使用接口明确给出的普通 CDN。
        cdns = {item.get("cdn") for item in data.get("cdnsWithName", [])}
        cdn = ""
        if (urlsplit(data.get("rtmp_url", "")).hostname or "").endswith(".edgesrv.com"):
            cdn = next((name for name in ("hw-h5", "tct-h5", "ali-h5") if name in cdns), "")
        options = [{"qn": 10000 if item["rate"] == 0 else 2000000 + item["rate"],
                    "desc": item.get("name") or (
                        "原画" if item["rate"] == 0 else f"{item.get('bit', 0)} kbps"),
                    "rate": item["rate"], "bit": item.get("bit", 0)}
                   for item in data.get("multirates", [])
                   if isinstance(item.get("rate"), int) and item["rate"] >= 0]
        if not any(item["rate"] == 0 for item in options):
            options.append({"qn": 10000, "desc": "原画", "rate": 0, "bit": 0})
        self._qualities[room_id] = sorted(options, key=lambda item: (
            item["rate"] == 0, item["bit"]), reverse=True)
        selected = self._select_quality(room_id, quality, preview)
        rate = selected["rate"]
        if cdn or rate:
            changed = self._request_source(parser, raw, cdn, rate=rate)
            if changed:
                data = changed
            else:
                rate = 0
        if not data:
            return {}
        stream = HTTPStream(session, f"{data['rtmp_url']}/{data['rtmp_live']}")
        actual_rate = data.get("rate", rate)
        stream.ddm_quality = 10000 if actual_rate == 0 else 2000000 + actual_rate
        return {"source": stream}

    def _request_source(self, parser, raw, cdn="", *, rate=0):
        # 与固定版本 Streamlink 的公开网页请求一致，请求 AVC 及网页提供的画质/CDN。
        encryption = parser._get_encryption(parser.DID)
        if not encryption:
            return {}
        timestamp, values = encryption
        auth = parser._compute_auth(raw, timestamp, values["key"], values["rand_str"],
                                   values["enc_time"], values["is_special"])
        with parser.session.http.post(parser._URL_PLAY.format(rid=raw), data={
                "enc_data": values["enc_data"], "tt": str(timestamp), "did": parser.DID,
                "auth": auth, "cdn": cdn, "rate": str(rate), "hevc": "0", "fa": "0", "ive": "0"},
                headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
            response.raise_for_status()
            result = response.json()
        data = result.get("data")
        if result.get("error") != 0 or not isinstance(data, dict):
            return {}
        if urlsplit(data.get("rtmp_url", "")).scheme != "https" or not data.get("rtmp_live"):
            raise ValueError("Invalid public stream")
        return data


class DouyinPlatform(NumericLivePlatform):
    kind = "douyin"
    label = "抖音"
    hosts = ("live.douyin.com", "douyin.com")
    image_hosts = ("douyinpic.com", "byteimg.com", "ibytedtos.com", "douyincdn.com")

    def _room_id_from_url(self, parts) -> str:
        path = super()._room_id_from_url(parts)
        if re.fullmatch(r"categorynew/[0-9]+_[0-9]+", path):
            room_ids = [value for key, value in parse_qsl(parts.query, keep_blank_values=True)
                        if key == "live_web_rid"]
            if len(room_ids) != 1:
                raise ValueError("抖音分类页链接需包含唯一的 live_web_rid 直播间号")
            return room_ids[0]
        return path

    def room_info(self, room_id: str) -> api.RoomInfo:
        canonical = self.normalize(room_id)
        raw = canonical.split(":", 1)[1]
        try:
            with requests.get(self.room_url(canonical), headers={
                    "User-Agent": "Mozilla/5.0", "Referer": "https://live.douyin.com/"},
                    cookies={"__ac_nonce": uuid.uuid4().hex[:21]}, timeout=(4, 8)) as response:
                response.raise_for_status()
                page = response.text
            info = self._page_info(page)
            room = info["room"]
            owner = room.get("owner") or info.get("anchor") or {}
            return api.RoomInfo(room_id=canonical, uname=owner.get("nickname") or f"抖音 · {raw}",
                title=room.get("title") or "抖音直播间", live=room["status"] == 2,
                platform=self.kind, face=self._image_url(owner.get("avatar_thumb")),
                cover_url=self._image_url(room.get("cover")),
                extra={"playback_mode": "stream", "live_known": True})
        except (requests.RequestException, ValueError, KeyError, TypeError, StopIteration) as error:
            raise RuntimeError("抖音房间信息获取失败，请使用直播间完整链接或稍后重试") from error

    @staticmethod
    def _page_info(page):
        # 与 Streamlink 8.6.1 相同的公开页面数据格式，保留网页的画质元数据。
        chunks = re.findall(r'self\.__pace_f\.push\(\[\d+,("\w+:.+?")]\)</script>', page)
        for chunk in reversed(chunks):
            if "state" not in chunk or "streamStore" not in chunk:
                continue
            payload = json.loads(re.sub(r"^\w+:", "", json.loads(chunk)))
            state = next(item["state"] for item in payload
                         if isinstance(item, dict) and "state" in item)
            info = state["roomStore"]["roomInfo"]
            room = info["room"]
            if type(room.get("status")) is not int or not room.get("id_str"):
                raise ValueError("Missing room status")
            return info
        raise ValueError("Missing public room data")

    def _streams(self, session, room_id, quality=250, *, preview=False):
        page = session.http.get(self.room_url(room_id),
                                cookies={"__ac_nonce": uuid.uuid4().hex[:21]}).text
        room = self._page_info(page)["room"]
        if room["status"] != 2:
            return {}
        stream_url = room.get("stream_url") or {}
        urls = {key.lower(): value for key, value in stream_url.get("flv_pull_url", {}).items()
                if isinstance(value, str) and urlsplit(value).scheme in ("http", "https")}
        if not urls:
            return {}
        # 这些 FLV 档位对应网页 SDK 的 ld/sd/hd/uhd；分辨率、帧率只用本房间元数据。
        sdk_keys = {"sd1": "ld", "sd2": "sd", "hd1": "hd", "full_hd1": "uhd"}
        metadata = stream_url.get("live_core_sdk_data", {}).get("pull_data", {}).get(
            "options", {}).get("qualities", [])
        metadata = {item.get("sdk_key"): item for item in metadata}
        keys = sorted(urls, key=lambda key: Douyin.stream_weight(key)[0], reverse=True)
        options = []
        for index, key in enumerate(keys):
            item = metadata.get(sdk_keys.get(key, key), {})
            label = item.get("name") or key.upper()
            desc = label
            resolution = str(item.get("resolution") or "")
            if re.fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", resolution):
                desc += f" · {resolution}"
            if isinstance(item.get("fps"), int) and item["fps"] > 0:
                desc += f" · {item['fps']}fps"
            # 稳定的整数仅用于软件保存/信号；不能当作像素高度或平台 rate。
            qn = 10000 if index == 0 else 3000000 + (zlib.crc32(key.encode()) & 0xFFFFFF)
            options.append({"qn": qn, "desc": desc, "label": label, "key": key})
        self._qualities[room_id] = options
        selected = self._select_quality(room_id, quality, preview)
        url = urls[selected["key"]]
        if url.startswith("http://"):
            url = "https://" + url[7:]
        stream = HTTPStream(session, url)
        stream.ddm_quality = selected["qn"]
        return {"source": stream}


class LivePlatformsPlugin(api.Plugin):
    def on_load(self, context: api.PluginContext) -> None:
        context.register_platform(HuyaPlatform())
        context.register_platform(DouyuPlatform())
        context.register_platform(DouyinPlatform())


plugin = LivePlatformsPlugin()
