"""虎牙公开直播流：关注卡片与 VLC 格子内播放。"""
import base64
from html import unescape
import json
import re
from urllib.parse import parse_qsl, urlsplit

import requests
from streamlink import Streamlink
from streamlink.plugins.huya import Huya
from streamlink.stream.http import HTTPStream

from ddm import plugins as api


class HuyaPlatform(api.Platform):
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

    def _streams(self, room_id: str):
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
            streams = {}
            for info in data.get("data", [{}])[0].get("gameStreamInfoList", []):
                # 使用网页明确提供的 HLS 线路；签名参数仍交给固定版本的 Streamlink。
                base = info.get("sHlsUrl")
                if not base:
                    continue
                name = info["sStreamName"]
                qs = dict(parse_qsl(unescape(info["sHlsAntiCode"])))
                params = parser._get_stream_params(qs.get("fm", ""), qs.get("fs", ""),
                    qs.get("ctype", "huya_live"), qs.get("wsTime", ""), name, 0)
                url = f"{base}/{name}.{info['sHlsUrlSuffix']}"
                if url.startswith("//"):
                    url = "https:" + url
                streams[f"{info['sCdnType'].lower()}_source"] = HTTPStream(session, url, params=params)
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

    def room_quality_options(self, room_id: str) -> list[dict]:
        return [{"qn": 10000, "desc": "原画"}]

    def play_url(self, room_id: str, quality: int = 250) -> tuple:
        session, _parser, streams = self._streams(room_id)
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
                        return response.url, 10000, "huya", headers
                except requests.RequestException:
                    continue
            raise RuntimeError("虎牙直播线路暂不可用，请重试")
        finally:
            session.http.close()

    def room_url(self, room_id: str) -> str:
        canonical = self.normalize(room_id)
        return f"https://www.huya.com/{canonical.split(':', 1)[1]}"


class HuyaWatchPlugin(api.Plugin):
    def on_load(self, context: api.PluginContext) -> None:
        context.register_platform(HuyaPlatform())


plugin = HuyaWatchPlugin()
