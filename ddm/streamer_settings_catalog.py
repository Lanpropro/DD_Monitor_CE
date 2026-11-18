"""Host-side followed-room snapshot and asynchronous platform quality lookup."""
from PySide6.QtCore import QObject

from .images import room_avatar_path
from .online_tasks import OnlineTask
from .streamer_defaults import native_quality_options


def room_choices(host):
    sidebar = host.sidebar
    platforms = getattr(host.plugins, 'platforms', {})
    folders = {folder['id']: folder['name'] for folder in getattr(sidebar, 'folders', ())}
    rooms = {str(room['room_id']): room for room in sidebar.rooms() if room.get('room_id')}
    saved = host.settings.get('streamer_defaults')
    choices = {}
    for room_id in dict.fromkeys([*rooms, *(saved if isinstance(saved, dict) else ())]):
        if not isinstance(room_id, str) or not room_id:
            continue
        room = rooms.get(room_id)
        stored = saved.get(room_id) if isinstance(saved, dict) else None
        stored_name = stored.get('name') if isinstance(stored, dict) else ''
        name = (room or {}).get('uname') or stored_name or room_id
        kind = room_id.partition(':')[0] if ':' in room_id else 'bilibili'
        platform = platforms.get(kind)
        label = ('B 站' if platforms else '') if kind == 'bilibili' else getattr(platform, 'label', '') or kind
        folder = sidebar.folder_for(room_id) if folders and room is not None else None
        choices[room_id] = {
            'name': str(name), 'platform': label, 'folder': folders.get(folder, ''),
            'display_room_id': str((room or {}).get('display_room_id') or ''),
            'live': bool(room and room.get('live') and room.get('live_known', True)),
            'followed': room is not None, 'avatar': room_avatar_path(room_id),
        }
    return choices


class StreamerSettingsCatalog(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.tasks = {}

    def request(self, room_id, reply):
        host = self.host
        tile = host._tile_of(room_id)
        options = native_quality_options(tile.quality_options) if tile is not None else []
        if options:
            reply(options, '')
            return
        pending = next((listeners for current, listeners in self.tasks.values() if current == room_id), None)
        if pending is not None:
            pending.append(reply)
            return
        platform = host.plugins.platform_for(room_id)
        if platform is None and not room_id.isdigit():
            reply([], '平台扩展未启用')
            return
        codec = host._codec_settings(tile)['bili_codec'] if platform is None else None

        def load(_cancelled, _progress):
            if platform is not None:
                return native_quality_options(platform.room_quality_options(room_id))
            from .bili import room_quality_options
            return native_quality_options(room_quality_options(room_id, codec))

        task = OnlineTask(load, None, self)
        self.tasks[task] = (room_id, [reply])
        host._platform_info_running.add(task)
        task.succeeded.connect(self._loaded)
        task.failed.connect(self._failed)
        task.finished.connect(self._finished)
        task.start()

    def _loaded(self, payload):
        task, options = payload
        self._deliver(task, options, '')

    def _failed(self, payload):
        task, _error = payload
        self._deliver(task, [], '画质读取失败，请重试')

    def _deliver(self, task, options, error):
        if not self.host._closing:
            for reply in self.tasks[task][1]:
                reply(options, error)

    def _finished(self):
        task = self.sender()
        self.tasks.pop(task, None)
        self.host._platform_info_running.discard(task)
        task.deleteLater()
