"""Search and select followed rooms from the inline empty-slot editor."""
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from .room_choice import RoomChoice
from .search import matches_text


class FollowedRoomPicker(QWidget):
    selected = Signal(str)

    def __init__(self, sidebar, parent):
        super().__init__(parent)
        self.sidebar = sidebar
        self.groups = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.search = QLineEdit(self)
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('搜索关注主播 / 房间号')
        self.search.setAccessibleName(self.search.placeholderText())
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._arrange)
        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(self.search, 1)
        self.live_only = QCheckBox('直播中', self)
        self.live_only.toggled.connect(self._arrange)
        filters.addWidget(self.live_only)
        layout.addLayout(filters)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().installEventFilter(self)
        layout.addWidget(self.scroll, 1)

    def load(self, occupied):
        sidebar = self.sidebar
        default = sidebar.default_folder()['id']
        entries = {}
        for item in sidebar.items():
            room_id = str(item.room.get('room_id') or '')
            if room_id and room_id not in occupied:
                entries.setdefault(sidebar.folder_for(room_id) or default, []).append((room_id, item))
        previous = self.scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.groups = []
        for folder in sidebar.folders:
            group = entries.get(folder['id'])
            if not group:
                continue
            name = folder['name']
            holder = QFrame(content)
            holder.setObjectName('PluginCard')
            section = QVBoxLayout(holder)
            section.setContentsMargins(8, 8, 8, 8)
            section.setSpacing(6)
            title = QLabel(name, holder)
            title.setObjectName('SectionLabel')
            title.setTextFormat(Qt.PlainText)
            section.addWidget(title)
            grid = QGridLayout()
            grid.setSpacing(6)
            section.addLayout(grid)
            cards = []
            for index, (room_id, item) in enumerate(group):
                room = item.room
                display = str(room.get('uname') or room_id)
                card = RoomChoice(room, display, index, item.thumb.face_pixmap(), holder)
                card.setCheckable(False)
                card.setMinimumHeight(54)
                card.clicked.connect(lambda _checked, key=room_id: self.selected.emit(key))
                terms = ' '.join((display, room_id, str(room.get('display_room_id') or ''), name))
                cards.append((card, terms, room))
            box.addWidget(holder)
            self.groups.append((holder, grid, cards))
        self.empty = QLabel(content)
        self.empty.setObjectName('SettingsHint')
        self.empty.setAlignment(Qt.AlignCenter)
        box.addWidget(self.empty)
        box.addStretch(1)
        self.scroll.setWidget(content)
        self._arrange()

    def _arrange(self):
        if self.scroll.widget() is None:
            return
        columns = max(1, (self.scroll.viewport().width() - 16 + 6) // 106)
        words = self.search.text().split()
        live_only = self.live_only.isChecked()
        has_results = False
        for holder, grid, cards in self.groups:
            while grid.count():
                grid.takeAt(0)
            for column in range(max(columns, grid.columnCount())):
                grid.setColumnStretch(column, 1 if column < columns else 0)
            index = 0
            for button, terms, room in cards:
                live = room.get('live') and room.get('live_known', True)
                matched = (not live_only or live) and all(matches_text(terms, word) for word in words)
                button.setVisible(matched)
                if matched:
                    grid.addWidget(button, index // columns, index % columns)
                    index += 1
            holder.setVisible(bool(index))
            has_results |= bool(index)
        self.empty.setText('没有匹配的关注主播' if (words or live_only) and self.groups else '暂无可入墙的关注主播')
        self.empty.setVisible(not has_results)

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Resize:
            self._arrange()
        return super().eventFilter(watched, event)
