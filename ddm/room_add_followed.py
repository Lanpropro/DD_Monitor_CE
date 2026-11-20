"""Inline followed-room and preset pickers with viewport-rendered cards."""
from dataclasses import dataclass

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap, QPixmapCache
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHeaderView, QHBoxLayout,
                               QLabel, QLineEdit, QStyle, QStyledItemDelegate, QTableView, QVBoxLayout, QWidget)

from . import theme
from .avatar_widgets import AVATAR_COLORS, circular_pixmap
from .corner_geometry import continuous_path
from .search import matches_query
from .sidebar_navigation import NavigationButton


@dataclass(frozen=True)
class _RoomCard:
    room_id: str
    name: str
    terms: str
    room: dict
    face: QPixmap | None
    color: str
    detail: str = ''


class _FollowedRoomsModel(QAbstractTableModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.rows = []
        self.columns = 1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self.columns

    def entry(self, index):
        row = self.rows[index.row()]
        if isinstance(row, str):
            return row if index.column() == 0 else None
        return row[index.column()] if index.column() < len(row) else None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entry(index)
        if isinstance(entry, _RoomCard):
            if role == Qt.DisplayRole:
                return entry.name
            if role == Qt.UserRole:
                return entry.room_id
            if role in (Qt.ToolTipRole, Qt.AccessibleTextRole):
                return entry.detail or entry.name
        elif isinstance(entry, str) and role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.AccessibleTextRole):
            return entry
        return None

    def flags(self, index):
        if index.isValid() and isinstance(self.entry(index), _RoomCard):
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.NoItemFlags

    def set_rows(self, rows, columns):
        self.beginResetModel()
        self.rows, self.columns = rows, columns
        self.endResetModel()


class _FollowedRoomDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        entry = index.model().entry(index)
        if entry is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(option.font)
        if isinstance(entry, str):
            rect = option.rect.adjusted(3, 2, -3, -1)
            painter.fillPath(continuous_path(QRectF(rect), 5), theme.qcolor(theme.CONTENT))
            painter.setPen(theme.qcolor(theme.TEXT2))
            text = rect.adjusted(8, 0, -8, 0)
            painter.drawText(text, Qt.AlignVCenter, option.fontMetrics.elidedText(entry, Qt.ElideRight, text.width()))
        else:
            self._paint_card(painter, option, entry)
        painter.restore()

    @staticmethod
    def _paint_card(painter, option, entry):
        rect = option.rect.adjusted(3, 3, -3, -3)
        focused = bool(option.state & QStyle.State_HasFocus)
        highlighted = option.state & (QStyle.State_MouseOver | QStyle.State_Selected)
        path = continuous_path(QRectF(rect).adjusted(.5, .5, -.5, -.5), 9)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if focused else theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER if highlighted else theme.CONTENT))
        painter.drawPath(path)

        avatar = QRect(rect.center().x() - 13, rect.top() + 5, 28, 28)
        if entry.face is not None and not entry.face.isNull():
            ratio = painter.device().devicePixelRatioF()
            pixels = round(28 * ratio)
            key = f'followed-room-avatar:{entry.face.cacheKey()}:{pixels}'
            pixmap = QPixmapCache.find(key)
            if pixmap is None:
                pixmap = circular_pixmap(entry.face, pixels)
                QPixmapCache.insert(key, pixmap)
            painter.drawPixmap(avatar, pixmap)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(entry.color))
            painter.drawEllipse(avatar)
            painter.setPen(Qt.white)
            painter.drawText(avatar, Qt.AlignCenter, entry.name[:1])
        name = rect.adjusted(4, 34, -4, -2)
        painter.setPen(theme.qcolor(theme.TEXT1))
        painter.drawText(name, Qt.AlignCenter, option.fontMetrics.elidedText(entry.name, Qt.ElideRight, name.width()))


class _FollowedRoomsView(QTableView):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            index = self.currentIndex()
            if index.data(Qt.UserRole):
                self.clicked.emit(index)
                event.accept()
                return
        super().keyPressEvent(event)


class RoomCardPicker(QWidget):
    selected = Signal(str)

    def __init__(self, parent, *, search_label, list_label):
        super().__init__(parent)
        self.groups = []
        self._header_rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.filters = QHBoxLayout()
        self.filters.setSpacing(8)
        self.search = QLineEdit(self)
        self.search.setObjectName('Search')
        self.search.setPlaceholderText(search_label)
        self.search.setAccessibleName(search_label)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._arrange)
        self.filters.addWidget(self.search, 1)
        layout.addLayout(self.filters)

        self.empty = QLabel(objectName='SettingsHint')
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        layout.addWidget(self.empty)
        self.scroll = _FollowedRoomsView(self)
        self.scroll.setAccessibleName(list_label)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.scroll.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scroll.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scroll.setMouseTracking(True)
        self.scroll.setShowGrid(False)
        self.scroll.horizontalHeader().hide()
        self.scroll.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        header = self.scroll.verticalHeader()
        header.hide()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setMinimumSectionSize(20)
        header.setDefaultSectionSize(58)
        self.model = _FollowedRoomsModel(self.scroll)
        self.scroll.setModel(self.model)
        self.scroll.setItemDelegate(_FollowedRoomDelegate(self.scroll))
        self.scroll.clicked.connect(self._select)
        self.scroll.viewport().installEventFilter(self)
        layout.addWidget(self.scroll, 1)

    def _select(self, index):
        room_id = index.data(Qt.UserRole)
        if room_id:
            self.selected.emit(room_id)

    def _column_count(self):
        scrollbar = self.scroll.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        return max(1, (self.scroll.contentsRect().width() - scrollbar) // 106)

    def _matches(self, card, query):
        return matches_query(card.terms, query)

    def _empty_text(self, query):
        return ''

    def _arrange(self):
        columns = self._column_count()
        query = self.search.text().strip()
        rows = []
        header_rows = []
        for title, cards in self.groups:
            matches = [card for card in cards if self._matches(card, query)]
            if matches:
                header_rows.append(len(rows))
                rows.append(title)
                rows.extend(matches[i:i + columns] for i in range(0, len(matches), columns))
        position = self.scroll.verticalScrollBar().value()
        self.scroll.clearSpans()
        header = self.scroll.verticalHeader()
        font_height = self.scroll.fontMetrics().height()
        header.setDefaultSectionSize(max(58, font_height + 42))
        for row in self._header_rows:
            self.scroll.setRowHeight(row, header.defaultSectionSize())
        self._header_rows = header_rows
        self.model.set_rows(rows, columns)
        for row in header_rows:
            self.scroll.setRowHeight(row, max(26, font_height + 8))
            if columns > 1:
                self.scroll.setSpan(row, 0, 1, columns)
        self.scroll.verticalScrollBar().setValue(position)
        self.empty.setText(self._empty_text(query))
        self.empty.setVisible(not rows and bool(self.empty.text()))

    def eventFilter(self, watched, event):
        if (watched is self.scroll.viewport() and event.type() == QEvent.Resize
                and self._column_count() != self.model.columns):
            self._arrange()
        return super().eventFilter(watched, event)


class FollowedRoomPicker(RoomCardPicker):
    def __init__(self, sidebar, parent):
        super().__init__(parent, search_label='搜索关注主播 / 房间号', list_label='可选的关注主播')
        self.sidebar = sidebar
        self.live_only = QCheckBox('直播中', self)
        self.live_only.toggled.connect(self._arrange)
        self.filters.addWidget(self.live_only)

    def load(self, occupied):
        sidebar = self.sidebar
        default = sidebar.default_folder()['id']
        folders = {folder['id']: folder['name'] for folder in sidebar.folders}
        entries = {}
        for index, item in enumerate(sidebar.items()):
            room = item.room
            room_id = str(room.get('room_id') or '')
            if not room_id or room_id in occupied:
                continue
            folder_id = sidebar.folder_for(room_id) or default
            name = str(room.get('uname') or room_id)
            terms = ' '.join((name, room_id, str(room.get('display_room_id') or ''), folders.get(folder_id, '')))
            entries.setdefault(folder_id, []).append(_RoomCard(
                room_id, name, terms, room, item.thumb.face_pixmap(), AVATAR_COLORS[index % len(AVATAR_COLORS)],
                detail=f'{name} · {room_id}'))
        self.groups = [(title, entries[key]) for key, title in folders.items() if key in entries]
        self._arrange()

    def _matches(self, card, query):
        live = card.room.get('live') and card.room.get('live_known', True)
        return (not self.live_only.isChecked() or live) and super()._matches(card, query)

    def _empty_text(self, query):
        return '没有匹配的关注主播' if (query or self.live_only.isChecked()) and self.groups else '暂无可入墙的关注主播'


class PresetRoomPicker(RoomCardPicker):
    def __init__(self, parent):
        super().__init__(parent, search_label='搜索电视频道', list_label='电视预设频道')
        self.rooms = {}
        self.file_button = NavigationButton('选择本地播放列表', 'open_folder', self)
        self.filters.addWidget(self.file_button)
        self.filters.setAlignment(Qt.AlignLeft)

    def load(self, presets, has_file_filters):
        self.rooms = {}
        entries = {}
        for index, (room, avatar_path) in enumerate(presets):
            room_id, name = room['room_id'], room['uname']
            group = room.get('import_group') or room.get('title') or '电视频道'
            face = QPixmap(avatar_path) if avatar_path else None
            entries.setdefault(group, []).append(_RoomCard(
                room_id, name, f'{name} {group}', room, face, AVATAR_COLORS[index % len(AVATAR_COLORS)]))
            self.rooms[room_id] = room
        self.groups = list(entries.items())
        self.file_button.setVisible(has_file_filters)
        self.search.setVisible(bool(self.rooms))
        self.scroll.setVisible(bool(self.rooms))
        self._arrange()

    def _empty_text(self, query):
        return '没有匹配的频道' if self.rooms else ''
