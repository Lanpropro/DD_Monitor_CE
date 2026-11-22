"""Choose a video tile or a custom-grid vacancy for a live notice."""
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget


class WallReplacement(QObject):
    def __init__(self, placement):
        super().__init__(placement.host)
        self.placement = placement
        self.host = placement.host
        self.replacement_rooms = []
        self._replacement_target = None

    def place(self, rooms):
        self.cancel_replacement()
        host = self.host
        wall = host.wall
        for room in rooms:
            room_id = str(room.get('room_id') or '')
            if (not room_id or host._tile_of(room_id) is not None
                    or any(str(queued['room_id']) == room_id for queued in self.replacement_rooms)):
                continue
            current = next((item.room for item in host.sidebar._items
                            if str(item.room.get('room_id')) == room_id), room)
            if not wall.snap_grid.interactive() and any(not tile.room.get('room_id') for tile in wall.visible_tiles()):
                host.add_to_wall(dict(current), empty_only=True)
            else:
                self.replacement_rooms.append(dict(current))
        if self.replacement_rooms:
            QApplication.instance().installEventFilter(self)
            QApplication.setOverrideCursor(Qt.CrossCursor)
            if wall.snap_grid.interactive():
                host._show_notice('点击空位放入直播，或点击画面进行替换。按 Esc 取消。')
            else:
                host._show_notice('点击画面墙中的画面进行替换，按 Esc 取消')

    def cancel_replacement(self):
        if self.replacement_rooms:
            QApplication.instance().removeEventFilter(self)
            QApplication.restoreOverrideCursor()
        self.replacement_rooms = []
        self._replacement_target = None

    def eventFilter(self, watched, event):
        if not self.replacement_rooms:
            return False
        if event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            event.accept()
            return True
        if ((watched is self.host and event.type() in (QEvent.Hide, QEvent.Close))
                or event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape):
            self.cancel_replacement()
            return event.type() == QEvent.KeyPress
        # Native clicks visit QWindow before Qt dispatches them to QWidget.
        # Consuming that release would prevent the target video from seeing it.
        if (event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
                or not isinstance(watched, QWidget)):
            return False
        if event.button() != Qt.LeftButton:
            return False
        position = event.globalPosition().toPoint()
        wall = self.host.wall
        target = next((tile for tile in wall.visible_tiles()
                       if (watched is tile or tile.isAncestorOf(watched))
                       and tile.video.rect().contains(tile.video.mapFromGlobal(position))), None)
        if target is None and watched is wall:
            target = wall.snap_grid.vacant_unit_at(wall.mapFromGlobal(position))
        if event.type() == QEvent.MouseButtonPress:
            self._replacement_target = (wall.layout_id, target) if target is not None else None
            return target is not None
        pressed, self._replacement_target = self._replacement_target, None
        if pressed is None:
            return False
        if (wall.layout_id, target) == pressed:
            room = self.replacement_rooms[0]
            if len(self.replacement_rooms) == 1:
                self.cancel_replacement()
            else:
                self.replacement_rooms.pop(0)
            QTimer.singleShot(0, self, lambda: self._place_at_target(pressed, room))
        return True

    def _place_at_target(self, selection, room):
        host = self.host
        wall = host.wall
        layout, target = selection
        room_id = str(room['room_id'])
        if host._closing or wall.layout_id != layout or host._tile_of(room_id) is not None:
            return
        if isinstance(target, tuple):
            wall.snap_grid.place_room_in_unit(target, room_id, lambda tile, rid:
                                              self.placement.drop_room(tile, rid, room=room))
        elif target in wall.visible_tiles():
            self.placement.drop_room(target, room_id, room=room)
