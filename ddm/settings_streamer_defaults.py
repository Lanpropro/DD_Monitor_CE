"""Independent settings for rooms explicitly selected by the user."""
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .settings_layout import SettingsSection
from .settings_streamer_picker import StreamerPicker
from .settings_streamer_profiles import StreamerProfileCard, quality_label
from .streamer_defaults import native_quality_options, room_defaults
from .ui import ToggleSwitch, page_header


class StreamerDefaultsPage(QWidget):
    changed = Signal()
    qualityRequested = Signal(str, str)

    def __init__(self, settings, rooms):
        super().__init__()
        self.setObjectName('SettingsPage')
        self.rooms = {key: dict(value) if isinstance(value, dict) else {'name': str(value), 'followed': True}
                      for key, value in rooms.items()}
        self.entries = {}
        saved = settings.get('streamer_defaults')
        if isinstance(saved, dict):
            for room_id, row in saved.items():
                if isinstance(row, dict) and isinstance(room_id, str) and room_id:
                    room = self.rooms.setdefault(room_id, {'name': str(row.get('name') or room_id), 'followed': False})
                    self.entries[room_id] = {'name': room['name'], **room_defaults(settings, room_id)}
        self.expanded = set()
        self.qualities = {}
        self.requests = {}
        self.cards = {}
        self.edited_room = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)
        content = QWidget()
        self.scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.addLayout(page_header(
            '主播独立设置', '主播从墙下上墙时应用默认值。墙上的临时调整只影响当前观看。'))
        add_section = SettingsSection('添加主播')
        layout.addWidget(add_section)
        self.picker = StreamerPicker(self.rooms)
        self.picker.selected.connect(self.add)
        add_section.grid.addWidget(self.picker, 0, 0)
        add_section.grid.setColumnStretch(0, 1)
        add_section.grid.setColumnStretch(1, 0)

        heading = QHBoxLayout()
        title = QLabel('已配置的主播', objectName='SettingsSectionTitle')
        heading.addWidget(title, 1)
        label = QLabel('合并相同配置')
        self.merge = ToggleSwitch(label.text())
        self.merge.setChecked(bool(settings.get('streamer_defaults_merge_identical', False)))
        self.merge.setToolTip('只合并显示；点击叠放头像切换要编辑的主播。')
        label.setBuddy(self.merge)
        heading.addWidget(label)
        heading.addWidget(self.merge)
        layout.addLayout(heading)
        self.empty = QLabel('尚未配置主播', objectName='SettingsHint')
        layout.addWidget(self.empty)
        self.profiles = QVBoxLayout()
        self.profiles.setSpacing(8)
        layout.addLayout(self.profiles)
        layout.addStretch(1)

        self.regroup_timer = QTimer(self)
        self.regroup_timer.setSingleShot(True)
        self.regroup_timer.timeout.connect(self._render_profiles)
        self.merge.toggled.connect(self._merge_changed)
        self.picker.set_occupied(self.entries)
        self._render_profiles()

    def _groups(self):
        if not self.merge.isChecked():
            return [(room_id,) for room_id in self.entries]
        groups = {}
        for room_id, row in self.entries.items():
            names = tuple(quality_label(row[key]).strip().casefold() if key in row else None
                          for key in ('playback', 'recording'))
            groups.setdefault((*names, row.get('volume')), []).append(room_id)
        return [tuple(group) for group in groups.values()]

    def _render_profiles(self):
        groups = self._groups()
        for key in set(self.cards).difference(groups):
            card = self.cards.pop(key)
            self.profiles.removeWidget(card)
            card.hide()
            card.deleteLater()
        for index, group in enumerate(groups):
            card = self.cards.get(group)
            if card is None:
                selected = self.edited_room if self.edited_room in group else next(
                    (key for key in group if key in self.expanded), group[0])
                card = self.cards[group] = StreamerProfileCard(self, group, selected)
            if self.profiles.indexOf(card) != index:
                self.profiles.insertWidget(index, card)
            card.update_summary()
        self.empty.setVisible(not groups)

    def _merge_changed(self):
        self._render_profiles()
        self.changed.emit()

    def add(self, room_id):
        room = self.rooms.get(room_id)
        if room is None or not room['followed'] or room_id in self.entries:
            return
        self.entries[room_id] = {'name': room['name']}
        self.set_expanded(room_id, True)
        self.picker.set_occupied(self.entries)
        self._render_profiles()
        card = next(card for group, card in self.cards.items() if room_id in group)
        if card.room_id != room_id:
            card.select(room_id)
        QTimer.singleShot(0, self, lambda: self._scroll_to(room_id))
        self.changed.emit()

    def _scroll_to(self, room_id):
        for group, card in self.cards.items():
            if room_id in group:
                self.scroll.ensureWidgetVisible(card, 0, 8)
                break

    def set_expanded(self, room_id, expanded):
        if expanded:
            self.edited_room = room_id
            self.expanded.add(room_id)
        else:
            self.expanded.discard(room_id)

    def remove(self, room_id):
        self.entries.pop(room_id, None)
        self.expanded.discard(room_id)
        self.requests.pop(room_id, None)
        self.picker.set_occupied(self.entries)
        self._render_profiles()
        self.changed.emit()

    def edit(self, room_id, field, value):
        row = self.entries[room_id]
        if row.get(field) == value:
            return
        if value is None:
            row.pop(field, None)
        else:
            row[field] = value
        self.edited_room = room_id
        self.regroup_timer.start(0)
        self.changed.emit()

    def request_quality(self, room_id, *, refresh=False):
        if room_id in self.requests or (not refresh and room_id in self.qualities):
            return
        token = self.requests[room_id] = uuid4().hex
        self._update_quality_views(room_id)
        self.qualityRequested.emit(room_id, token)

    def receive_quality(self, room_id, token, options, error):
        if self.requests.get(room_id) != token:
            return
        self.requests.pop(room_id)
        self.qualities[room_id] = (native_quality_options(options), error)
        self._update_quality_views(room_id)

    def _update_quality_views(self, room_id):
        for card in self.cards.values():
            if card.room_id == room_id:
                card.update_quality()

    def values(self):
        return {'streamer_defaults': {room_id: dict(row) for room_id, row in self.entries.items()},
                'streamer_defaults_merge_identical': self.merge.isChecked()}
