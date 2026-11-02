"""Choose a wall tile for live-notice replacement without changing its layout."""
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
        for room in rooms:
            room_id = str(room.get('room_id') or '')
            if not room_id or host._tile_of(room_id) is not None:
                continue
            current = next((item.room for item in host.sidebar._items
                            if str(item.room.get('room_id')) == room_id), room)
            if any(not tile.room.get('room_id') for tile in host.wall.visible_tiles()):
                host.add_to_wall(dict(current), empty_only=True)
            else:
                self.replacement_rooms.append(dict(current))
        if self.replacement_rooms:
            QApplication.instance().installEventFilter(self)
            QApplication.setOverrideCursor(Qt.CrossCursor)
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
        if event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            return False
        if event.button() != Qt.LeftButton:
            return False
        position = event.globalPosition().toPoint()
        target = next((tile for tile in self.host.wall.visible_tiles()
                       if isinstance(watched, QWidget) and (watched is tile or tile.isAncestorOf(watched))
                       and tile.video.rect().contains(tile.video.mapFromGlobal(position))), None)
        if event.type() == QEvent.MouseButtonPress:
            self._replacement_target = target
            return target is not None
        pressed, self._replacement_target = self._replacement_target, None
        if pressed is None:
            return False
        if target is pressed:
            room = self.replacement_rooms[0]
            if len(self.replacement_rooms) == 1:
                self.cancel_replacement()
            else:
                self.replacement_rooms.pop(0)
            QTimer.singleShot(0, self, lambda: self.placement.drop_room(target, str(room['room_id']), room=room)
                              if target in self.host.wall.visible_tiles() and not self.host._closing else None)
        return True
