"""Followed-room search with picture-in-picture avatar cards."""
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                              QListView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget)

from .room_choice import RoomChoice
from .search import matches_text


class StreamerPicker(QWidget):
    selected = Signal(str)

    def __init__(self, rooms):
        super().__init__()
        self.rooms = rooms
        self.occupied = set()
        self.items = {}
        self.buttons = {}
        self.pending_faces = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('搜索关注主播 / 房间号')
        self.search.setAccessibleName(self.search.placeholderText())
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.live_only = QCheckBox('直播中')
        filters.addWidget(self.live_only)
        layout.addLayout(filters)
        self.empty = QLabel('暂无可添加的关注主播', objectName='SettingsHint')
        self.empty.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty)
        self.view = QListWidget()
        self.view.setAccessibleName('可添加的关注主播')
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMovement(QListView.Static)
        self.view.setWrapping(True)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setSelectionMode(QListView.NoSelection)
        self.visible_rooms = 0
        height = 90 if any(room.get('platform') for room in rooms.values()) else 74
        self.view.setGridSize(QSize(116, height))
        self.face_timer = QTimer(self)
        self.face_timer.setSingleShot(True)
        self.face_timer.timeout.connect(self._load_visible_faces)
        self.view.verticalScrollBar().valueChanged.connect(self._queue_faces)
        self.view.viewport().installEventFilter(self)
        layout.addWidget(self.view)
        for index, (room_id, room) in enumerate(rooms.items()):
            if not room['followed']:
                continue
            self.pending_faces.add(room_id)
            item = QListWidgetItem(self.view)
            item.setSizeHint(QSize(110, height - 6))
            button = RoomChoice({'room_id': room_id, 'uname': room['name']}, room['name'],
                                index, None, self.view, platform_label=room.get('platform', ''))
            button.clicked.connect(lambda _checked=False, key=room_id: self.selected.emit(key))
            self.view.setItemWidget(item, button)
            self.items[room_id], self.buttons[room_id] = item, button
        self.search.textChanged.connect(self._filter)
        self.live_only.toggled.connect(self._filter)
        self._filter()

    def set_occupied(self, rooms):
        self.occupied = set(rooms)
        self._filter()

    def _filter(self):
        words = self.search.text().split()
        live_only = self.live_only.isChecked()
        self.visible_rooms = 0
        for room_id, item in self.items.items():
            room = self.rooms[room_id]
            terms = ' '.join((room['name'], room_id, room.get('display_room_id', ''),
                              room.get('folder', ''), room.get('platform', '')))
            visible = (room_id not in self.occupied and (not live_only or room.get('live'))
                       and all(matches_text(terms, word) for word in words))
            item.setHidden(not visible)
            self.buttons[room_id].setChecked(False)
            self.visible_rooms += int(visible)
        self.empty.setText('没有匹配的关注主播' if words or live_only else '暂无可添加的关注主播')
        self.empty.setVisible(not self.visible_rooms)
        self.view.setVisible(self.visible_rooms > 0)
        self._fit_height()
        self._queue_faces()

    def _fit_height(self):
        grid = self.view.gridSize()
        columns = max(1, (self.view.width() - 18) // grid.width())
        rows = min(2, max(1, (self.visible_rooms + columns - 1) // columns))
        self.view.setFixedHeight(rows * grid.height() + 2)

    def _queue_faces(self):
        self.face_timer.start(0)

    def _load_visible_faces(self):
        viewport = self.view.viewport().rect()
        for room_id in tuple(self.pending_faces):
            item = self.items[room_id]
            if not item.isHidden() and self.view.visualItemRect(item).intersects(viewport):
                self.pending_faces.remove(room_id)
                path = self.rooms[room_id].get('avatar')
                if path:
                    self.buttons[room_id].avatar.set_pixmap_image(QPixmap(path))

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            self._fit_height()
            self._queue_faces()
        return super().eventFilter(watched, event)
