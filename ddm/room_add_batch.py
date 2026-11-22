"""Sequential room lookups; the window owns resolvers and normal placement rules."""
from collections import deque

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox


class RoomAddBatch(QObject):
    def __init__(self, host, room_ids, folder_id='', *, target_tile=None, resolver_type, on_complete=None):
        super().__init__(host)
        self.host = host
        self.on_complete = on_complete
        self.pending = deque(dict.fromkeys(room_ids))
        self.folder_id = folder_id
        self.target_tile = target_tile
        self.resolver_type = resolver_type
        self.added = 0
        self.skipped = 0
        self.failures = []
        self.resolver = None

    def start(self):
        from .online_ui import show_result
        show_result(self.host, f'正在查询 {len(self.pending)} 个直播间…')
        QTimer.singleShot(0, self._next)

    def _place(self, room):
        self.host._on_room_added(room, folder_id=self.folder_id,
                                 target_tile=self.target_tile, notify=False)
        self.target_tile = None

    def _next(self):
        host = self.host
        if host._closing:
            self.deleteLater()
            return
        if not self.pending:
            from .online_ui import show_result
            summary = f'已添加 {self.added} 个直播间，已关注 {self.skipped} 个，失败 {len(self.failures)} 个'
            show_result(host, summary)
            if self.on_complete is not None:
                self.on_complete(self)
            elif self.failures:
                dialog = QMessageBox(QMessageBox.Warning, '添加结果', summary, QMessageBox.Ok, host)
                dialog.setInformativeText('失败项可复制后重新批量添加；已添加的直播间会保留。')
                dialog.setDetailedText('\n'.join(f'{rid}：{reason}' for rid, reason in self.failures))
                dialog.exec()
                dialog.deleteLater()
            self.deleteLater()
            return
        room_id = self.pending.popleft()
        existing = next((room for room in host.sidebar.rooms()
                         if str(room.get('room_id')) == room_id), None)
        if existing is not None:
            self.skipped += 1
            if self.target_tile is not None:
                self._place(existing)
            QTimer.singleShot(0, self._next)
            return
        platform = host.plugins.platform_for(room_id)
        if callable(getattr(platform, 'room_list', None)):
            from .room_list_import import RoomListImport
            def list_added(added, skipped, error):
                self.added += added
                self.skipped += skipped
                if error:
                    self.failures.append((room_id, error))
                else:
                    self.target_tile = None
                QTimer.singleShot(0, self._next)
            RoomListImport(host, platform.room_list, room_id, folder_id=self.folder_id,
                           target_tile=self.target_tile, on_complete=list_added).start()
            return
        if ':' in room_id and '://' not in room_id and platform is None:
            self.failures.append((room_id, '请启用对应的平台插件并重启'))
            QTimer.singleShot(0, self._next)
            return
        options = {'platform': platform} if platform is not None else {}
        resolver = self.resolver_type(room_id, host, **options)
        self.resolver = resolver
        resolver.resolved.connect(self._resolved)
        resolver.failed.connect(lambda _rid, r=resolver: self.failures.append((room_id,
            getattr(r, 'error_message', '') or '房间查询失败，请检查链接、网络或平台登录状态')))
        resolver.finished.connect(self._finished)
        host._platform_info_running.add(resolver)
        resolver.start()

    def _resolved(self, room):
        if self.host._closing:
            return
        if any(str(old.get('room_id')) == str(room.get('room_id')) for old in self.host.sidebar.rooms()):
            self.skipped += 1
        else:
            self.added += 1
        self._place(room)

    def _finished(self):
        resolver, self.resolver = self.resolver, None
        self.host._platform_info_running.discard(resolver)
        resolver.deleteLater()
        QTimer.singleShot(0, self._next)
