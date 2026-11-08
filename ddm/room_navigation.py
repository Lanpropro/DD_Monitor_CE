"""Room input/profile resolution and browser navigation actions; window remains the Qt owner."""
import webbrowser
from urllib.parse import urlsplit


class RoomNavigation:
    def __init__(self, host):
        self.host = host

    def room_browser_url(self, room: dict) -> str:
        host = self.host
        room_id = str(room.get("room_id") or "")
        if room_id.isascii() and room_id.isdecimal():
            return f"https://live.bilibili.com/{room_id}"
        kind, separator, raw_id = room_id.partition(":")
        platform = host.plugins.platforms.get(kind) if separator and raw_id else None
        if platform is None:
            return ""
        try:
            url = platform.room_url(room_id)
            parts = urlsplit(url)
            return url if parts.scheme in ("http", "https") and parts.netloc else ""
        except Exception:  # noqa: BLE001
            return ""

    def open_room_browser(self, url: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        host = self.host
        try:
            opened = webbrowser.open(url)
        except OSError:
            opened = False
        if not opened:
            QMessageBox.warning(host, "观看直播", "无法打开默认浏览器，请检查系统浏览器设置。")

    def normalize_room_input(self, text: str) -> str | None:
        from PySide6.QtWidgets import QDialog
        host = self.host
        from .room_input import bili_room_id, extract_room_input, is_bili_short_url
        text = extract_room_input(text)
        platform = host.plugins.platform_for(text)
        if platform is not None:
            profile = getattr(platform, "profile_sec_uid", None)
            sec_uid = profile(text) if callable(profile) else ""
            if sec_uid:
                from .profile_room import ProfileRoomDialog
                dialog = ProfileRoomDialog(platform, sec_uid, host)
                result = dialog.exec()
                room_id = dialog.room_id
                dialog.deleteLater()
                if result != QDialog.Accepted:
                    raise ValueError("主页读取已取消，可重新粘贴主页链接重试")
                return room_id
            return platform.normalize(text)
        if room_id := bili_room_id(text):
            return room_id
        if is_bili_short_url(text):
            return text  # Expand the short link in InfoResolver's background thread.
        # 未装载的平台输入不能被旧的数字提取误当作 B 站房间。
        if ":" in text and urlsplit(text).hostname != "live.bilibili.com":
            raise ValueError("未识别平台，请启用对应的平台插件并重启")
        return None                    # B 站仍使用原有房间号解析
