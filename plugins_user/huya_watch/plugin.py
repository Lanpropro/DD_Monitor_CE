"""虎牙关注卡片与官方网页观看。房间资料只在本地构建。"""
import re
from urllib.parse import urlsplit

from ddm import plugins as api


class HuyaPlatform(api.Platform):
    kind = "huya"
    label = "虎牙"
    playback_mode = "browser"

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

    def room_info(self, room_id: str) -> api.RoomInfo:
        canonical = self.normalize(room_id)
        raw = canonical.split(":", 1)[1]
        return api.RoomInfo(
            room_id=canonical, uname=f"虎牙 · {raw}",
            title="点击观看虎牙直播", platform=self.kind,
            extra={"playback_mode": self.playback_mode, "live_known": False},
        )

    def room_url(self, room_id: str) -> str:
        canonical = self.normalize(room_id)
        return f"https://www.huya.com/{canonical.split(':', 1)[1]}"


class HuyaWatchPlugin(api.Plugin):
    def on_load(self, context: api.PluginContext) -> None:
        context.register_platform(HuyaPlatform())


plugin = HuyaWatchPlugin()
