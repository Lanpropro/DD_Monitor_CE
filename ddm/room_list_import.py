"""Resolve a plugin's channel list and add selected rooms through the follow catalog."""
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QDialog, QLabel


class RoomListImport(QThread):
    def __init__(self, host, resolve, room_id, *, folder_id, target_tile, on_complete):
        super().__init__(host)
        self.host = host
        self.resolve = resolve
        self.room_id = room_id
        self.folder_id = folder_id
        self.target_tile = target_tile
        self.on_complete = on_complete
        self.result = None
        self.error = ''
        self.finished.connect(self._complete)

    def start(self):
        self.host._platform_info_running.add(self)
        super().start()

    def run(self):
        try:
            self.result = self.resolve(self.room_id, self.isInterruptionRequested)
        except Exception as error:
            self.error = str(getattr(error, 'user_message', '') or '无法读取频道列表，请检查来源后重试')[:600]

    def _choose(self, rooms, existing):
        from .room_dialogs import FollowImportDialog
        sidebar = self.host.sidebar
        dialog = FollowImportDialog(rooms, existing, self.host, folders=sidebar.folder_state(),
                                    folder_creator=sidebar.create_folder, channels=True)
        for action in dialog.folder_button.menu().actions():
            if action.isCheckable() and action.data() == self.folder_id:
                dialog._select_folder(action)
                break
        if self.result.warning:
            warning = QLabel(self.result.warning)
            warning.setWordWrap(True)
            warning.setObjectName('SettingsHint')
            dialog.secondary_actions.addWidget(warning)
        try:
            if dialog.exec() != QDialog.Accepted:
                return [], self.folder_id
            return dialog.selected(), dialog.folder_id
        finally:
            dialog.deleteLater()

    def _complete(self):
        host = self.host
        host._platform_info_running.discard(self)
        importing = False
        try:
            if host._closing:
                return
            if self.result is None or not self.result.rooms:
                self.on_complete(0, 0, self.error or '未找到可导入的频道')
                return
            existing = {str(room['room_id']) for room in host.sidebar.rooms()}
            rooms = [room.as_dict() for room in self.result.rooms]
            chosen, folder_id = self._choose(rooms, existing) if self.result.choose else (rooms, self.folder_id)
            if host._closing:
                return
            if not chosen:
                self.on_complete(0, 0, '未选择频道，可以重新导入')
                return
            if self.result.choose and self.target_tile is not None:
                catalog = host.room_placement.catalog
                if error := catalog.replacement_error(self.target_tile, str(chosen[0]['room_id'])):
                    self.on_complete(0, 0, error)
                    return
            if self.result.choose and getattr(host, '_follow_import_timer', None) is not None:
                self.on_complete(0, 0, '正在导入其他频道或关注，请稍后重试')
                return
            if self.result.store is not None:
                try:
                    self.result.store([room['room_id'] for room in chosen])
                except Exception as error:
                    self.on_complete(0, 0, str(getattr(error, 'user_message', '') or '无法保存频道来源，请重试')[:600])
                    return
            if self.result.choose:
                host._import_selected_follows(chosen, folder_id=folder_id,
                                              on_complete=lambda: self._import_finished(chosen, existing))
                importing = True
                return
            else:
                room = chosen[0]
                if room['room_id'] not in existing or self.target_tile is not None:
                    error = host._on_room_added(room, folder_id=folder_id, target_tile=self.target_tile)
                    if isinstance(error, str):
                        self.on_complete(0, 0, error)
                        return
            added = sum(room['room_id'] not in existing for room in chosen)
            self.on_complete(added, len(chosen) - added, '')
        finally:
            if not importing:
                self.deleteLater()

    def _import_finished(self, chosen, existing):
        host = self.host
        target = self.target_tile
        room = chosen[0]
        error = ''
        if target is not None and not host._closing:
            catalog = host.room_placement.catalog
            error = catalog.replacement_error(target, str(room['room_id']))
            if not error and target in host.wall.visible_tiles():
                catalog.place_in_target(target, room)
        added = sum(room['room_id'] not in existing for room in chosen)
        self.on_complete(added, len(chosen) - added, error)
        self.deleteLater()
