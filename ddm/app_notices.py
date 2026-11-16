"""Main window app notices; window remains the only state and Qt lifetime owner."""
from pathlib import Path


class AppNotices:
    def __init__(self, host):
        self.host = host

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
            '开始录制', '已开始录制切片素材', '切片素材继续录制', '开启即时回放缓存', '正在重新获取录制地址', '取到新流，继续录制',
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
