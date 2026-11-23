"""Main window app notices; window remains the only state and Qt lifetime owner."""
from pathlib import Path
from uuid import uuid4
from .streamer_defaults import room_defaults


class AppNotices:
    def __init__(self, host):
        self.host = host
        self.official_announcement = None
        self._windows_live = {}

    def check_official_announcement(self):
        if self.host._closing or self.official_announcement is not None:
            return
        from .official_announcement import OfficialAnnouncement
        self.official_announcement = OfficialAnnouncement(self.host)

    def cancel_official_announcement(self):
        if self.official_announcement is not None:
            self.official_announcement.cancel()

    def windows_live_rooms(self):
        settings = self.host.settings
        profiles = settings.get('streamer_defaults')
        if not settings.get('notice_windows_recording') or not isinstance(profiles, dict):
            return {}
        return {room_id: row for room_id, row in profiles.items()
                if isinstance(room_id, str) and room_id and isinstance(row, dict)
                and row.get('windows_live_notice') is True}

    def apply_live_status(self, status):
        host = self.host
        if host._closing:
            return
        rooms = self.windows_live_rooms()
        for room_id in self._windows_live.keys() - rooms.keys():
            del self._windows_live[room_id]
        for room_id, profile in rooms.items():
            info = status.get(room_id)
            if not info or not info.get('live_known', True) or 'live' not in info:
                continue
            was_live, tag = self._windows_live.get(room_id, (None, None))
            live = bool(info['live'])
            if not live:
                tag = None
            elif was_live is False and host._startup_status_complete:
                from .windows_recording_notifications import send_recording_notification
                tag = uuid4().hex[:16]
                name = info.get('uname') or profile.get('name') or room_id
                send_recording_notification('开播提醒', f'{name} 开播了', tag=tag)
            self._windows_live[room_id] = live, tag

    def background_recording_transition(self, event: str, room: dict) -> None:
        host = self.host
        if host._closing or not host.settings.get('notice_windows_recording', False):
            return
        if not room_defaults(host.settings, room['room_id']).get('windows_recording_notice'):
            return
        from .windows_recording_notifications import send_recording_notification
        title = ('开播 · 已开启自动录制' if event == 'started' else '下播 · 已停止自动录制')
        name = str(room.get('uname') or room['room_id'])
        _, tag = self._windows_live.get(str(room['room_id']), (None, None))
        if event == 'started' and tag is not None:
            # Keep the opening toast in Notification Center as the recording status changes.
            send_recording_notification(title, name, tag=tag, suppress_popup=True)
        else:
            send_recording_notification(title, name)

    def record_notice(self, message: str, room=None) -> None:
        host = self.host
        if host._closing:
            return
        prefix, separator, path = message.partition('：')
        if separator and path and prefix in (
                '已保存录制', '已保存切片素材', '已保存即时回放', '正在导出录制', '正在导出即时回放',
                '导出录制失败（原始分段保留）', '导出即时回放失败（原始分段保留）'):
            host._show_notice(prefix + '：', rooms=[room] if room else (), file_path=path,
                              kind='warning' if '失败' in prefix else 'info',
                              notice_key=('record-export', str(Path(path))),
                              pending=prefix.startswith('正在导出'))
            return
        room_id = str((room or {}).get('room_id') or '')
        progress = any(text in message for text in (
            '开始录制', '开始自动录制', '已开始录制切片素材', '切片素材继续录制', '开启即时回放缓存', '正在重新获取录制地址', '取到新流，继续录制',
            '重新连接录制流', '正在保存分段', '分段已保存，', '等待 ',
            '重新获取录制地址失败', 'FFmpeg 意外退出'))
        warning = any(word in message for word in ("失败", "不足", "找不到", "请先", "只能", "意外退出"))
        host._show_notice(message, rooms=[room] if room else (), kind="warning" if warning else "info",
                          notice_key=('record-state', room_id) if room_id and progress else None,
                          auto_room_link=False)

    def show_notice(self, message: str, *, rooms=(), kind="info", on_click=None, file_path=None,
                     notice_key=None, pending=False, auto_room_link=True) -> None:
        host = self.host
        if host._closing:
            return
        from .online_ui import show_result
        by_id = {str(item.room.get('room_id')): item.room for item in host.sidebar._items}
        rooms = [{**by_id.get(str(room.get('room_id')), {}), **room} for room in rooms]
        host._load_room_banners(rooms)
        pinned_live = kind == 'live' and any(
            str(room.get('room_id')) in host.sidebar.pinned for room in rooms)
        category = 'pinned_live' if pinned_live else kind
        persistent = host.settings.get('notice_persist_' + category, pinned_live)
        if auto_room_link and on_click is None and rooms and not file_path:
            if kind == 'live':
                on_click = lambda targets=tuple(dict(room) for room in rooms): host._place_live_notice_rooms(targets)
            else:
                url = host._room_browser_url(rooms[0])
                if url:
                    on_click = lambda target=url: host._open_room_browser(target)
        show_result(host, message, rooms=rooms, kind=kind, on_click=on_click,
                    persistent=persistent or pending, file_path=file_path,
                    notice_key=notice_key, pending=pending)
