"""Followed-room search with picture-in-picture avatar cards."""
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                              QLineEdit, QScrollArea, QStyle, QVBoxLayout, QWidget)

from .room_choice import RoomChoice
from .search import matches_text


class StreamerPicker(QWidget):
    selected = Signal(str)
    CARD_WIDTH = 110
    SPACING = 6

    def __init__(self, rooms):
        super().__init__()
        self.rooms = rooms
        self.occupied = set()
        self.buttons = {}
        self.headings = {}
        self.groups = {}
        self.visible_groups = {}
        self.pending_faces = set()
        self.columns = 0
        followed = [(key, room) for key, room in rooms.items() if room['followed']]
        followed.sort(key=lambda entry: entry[1].get('folder_order', 0))
        self.card_height = 84 if any(room.get('platform') for _, room in followed) else 68
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
        self.view = QScrollArea(objectName='StreamerFollowedList')
        self.view.setAccessibleName('可添加的关注主播')
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setWidgetResizable(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget(objectName='StreamerFollowedListContent')
        self.view.viewport().setObjectName('StreamerFollowedListViewport')
        self.view.setWidget(self.content)
        self.view.viewport().setAutoFillBackground(False)
        self.content.setAutoFillBackground(False)
        self.view.setStyleSheet(
            '#StreamerFollowedList, #StreamerFollowedListViewport, #StreamerFollowedListContent '
            '{ background: transparent; }')
        self.grid = QGridLayout(self.content)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(self.SPACING)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.face_timer = QTimer(self)
        self.face_timer.setSingleShot(True)
        self.face_timer.timeout.connect(self._load_visible_faces)
        self.view.verticalScrollBar().valueChanged.connect(self._queue_faces)
        self.view.viewport().installEventFilter(self)
        layout.addWidget(self.view)

        for index, (room_id, room) in enumerate(followed):
            folder = room.get('folder') or '未分组'
            folder_id = room.get('folder_id') or folder
            if folder_id not in self.groups:
                self.groups[folder_id] = []
                heading = QLabel(folder, self.content, objectName='SectionLabel')
                heading.setTextFormat(Qt.PlainText)
                self.headings[folder_id] = heading
            self.groups[folder_id].append(room_id)
            self.pending_faces.add(room_id)
            button = RoomChoice({'room_id': room_id, 'uname': room['name']}, room['name'],
                                index, None, self.content, platform_label=room.get('platform', ''))
            button.setFixedWidth(self.CARD_WIDTH)
            button.clicked.connect(lambda _checked=False, key=room_id: self.selected.emit(key))
            self.buttons[room_id] = button
        self.search.textChanged.connect(self._filter)
        self.live_only.toggled.connect(self._filter)
        self._filter()

    def set_occupied(self, rooms):
        self.occupied = set(rooms)
        self._filter()

    def _filter(self):
        words = self.search.text().split()
        live_only = self.live_only.isChecked()
        self.visible_groups = {}
        for folder_id, members in self.groups.items():
            matches = []
            for room_id in members:
                room = self.rooms[room_id]
                terms = ' '.join((room['name'], room_id, room.get('display_room_id', ''),
                                  room.get('folder', ''), room.get('platform', '')))
                visible = (room_id not in self.occupied and (not live_only or room.get('live'))
                           and all(matches_text(terms, word) for word in words))
                self.buttons[room_id].setVisible(visible)
                self.buttons[room_id].setChecked(False)
                if visible:
                    matches.append(room_id)
            self.headings[folder_id].setVisible(bool(matches))
            if matches:
                self.visible_groups[folder_id] = matches
        self.empty.setText('没有匹配的关注主播' if words or live_only else '暂无可添加的关注主播')
        self.empty.setVisible(not self.visible_groups)
        self.view.setVisible(bool(self.visible_groups))
        self._arrange()

    def _column_count(self):
        scrollbar = self.view.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        width = self.view.contentsRect().width() - scrollbar
        return max(1, (width + self.SPACING) // (self.CARD_WIDTH + self.SPACING))

    def _arrange(self):
        self.columns = self._column_count()
        while self.grid.count():
            self.grid.takeAt(0)
        row = 0
        for folder_id, members in self.visible_groups.items():
            self.grid.addWidget(self.headings[folder_id], row, 0, 1, self.columns)
            row += 1
            for index, room_id in enumerate(members):
                self.grid.addWidget(self.buttons[room_id], row + index // self.columns, index % self.columns)
            row += (len(members) + self.columns - 1) // self.columns
        heading_height = next(iter(self.headings.values())).sizeHint().height() if self.headings else 0
        maximum_height = 2 * (self.card_height + self.SPACING + heading_height)
        self.view.setFixedHeight(min(self.grid.sizeHint().height(), maximum_height))
        self._queue_faces()

    def _queue_faces(self):
        self.face_timer.start(0)

    def _load_visible_faces(self):
        viewport = self.view.viewport().rect().translated(-self.content.pos())
        for room_id in tuple(self.pending_faces):
            button = self.buttons[room_id]
            if not button.isHidden() and button.geometry().intersects(viewport):
                self.pending_faces.remove(room_id)
                path = self.rooms[room_id].get('avatar')
                if path:
                    button.avatar.set_pixmap_image(QPixmap(path))

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            if self._column_count() != self.columns:
                self._arrange()
            self._queue_faces()
        return super().eventFilter(watched, event)
