"""虎牙公开直播流：关注卡片与 VLC 格子内播放。"""
import re
from urllib.parse import urlsplit

import requests
from streamlink import Streamlink
from streamlink.plugins.huya import Huya

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
            streams = parser.streams()
        except Exception as error:  # noqa: BLE001
            session.http.close()
            raise RuntimeError("虎牙房间获取失败，请稍后重试") from error
        return session, parser, streams

    def room_info(self, room_id: str) -> api.RoomInfo:
        canonical = self.normalize(room_id)
        raw = canonical.split(":", 1)[1]
        session, parser, streams = self._streams(canonical)
        try:
            return api.RoomInfo(
                room_id=canonical, uname=parser.author or f"虎牙 · {raw}",
                title=parser.title or "虎牙直播间", live=bool(streams), platform=self.kind,
                extra={"playback_mode": self.playback_mode, "live_known": True},
            )
        finally:
            session.http.close()

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
            # 当前 VLC 运行库没有 TLS 模块；验证 CDN 的 HTTP 流后交给播放器。
            # 只用解析器公开提供的原画线路，不写 Cookie、不保存带签名的 URL。
            candidates = [streams["best"]]
            candidates.extend(stream for name, stream in streams.items() if "source" in name)
            seen = set()
            for stream in candidates:
                url = stream.to_url().replace("https://", "http://", 1)
                if url in seen:
                    continue
                seen.add(url)
                if len(seen) > 3:
                    break
                try:
                    with requests.get(url, headers=headers, stream=True, timeout=(4, 6)) as response:
                        response.raise_for_status()
                        if next(response.iter_content(3), b"") != b"FLV":
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
