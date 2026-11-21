"""Independent settings for rooms explicitly selected by the user."""
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .settings_layout import SettingsSection
from .settings_streamer_picker import StreamerPicker
from .settings_streamer_profiles import StreamerProfileCard, quality_label
from .settings_streamer_undo import StreamerRemovalNotice
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
        self.clip_recording_available = any(room.get('clip_recording_available') for room in self.rooms.values())
        self.windows_notice_available = bool(settings.get('notice_windows_recording'))
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
        self.removed_profiles = {}
        self.removal_order = ()

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
            '主播监控', '按主播设置画质、音量和自动录制。开启后，主播未上墙也会后台录制。'))
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
        self.merge.setToolTip('合并相同配置；未选头像时编辑整组，选中头像后单独编辑。')
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
        self.undo_notice = StreamerRemovalNotice(self, self.scroll)
        self.undo_notice.undo_requested.connect(self.undo_removal)
        self.undo_notice.entry_undo_requested.connect(self.undo_removal)
        self.undo_notice.expired.connect(self._clear_removal)
        self.picker.set_occupied(self.entries)
        self._render_profiles()

    def _groups(self):
        if not self.merge.isChecked():
            return [(room_id,) for room_id in self.entries]
        groups = {}
        for room_id, row in self.entries.items():
            names = tuple(quality_label(row[key]).strip().casefold() if key in row else None
                          for key in ('playback', 'recording'))
            groups.setdefault((*names, row.get('volume'), bool(row.get('auto_record')),
                               bool(row.get('windows_recording_notice')), row.get('auto_record_mode')), []).append(room_id)
        return [tuple(group) for group in groups.values()]

    def _render_profiles(self):
        groups = self._groups()
        selections = set()
        for key in tuple(self.cards):
            if key in groups:
                continue
            card = self.cards.pop(key)
            if len(key) > 1 and card.room_id is not None:
                selections.add(card.room_id)
            self.profiles.removeWidget(card)
            card.hide()
            card.deleteLater()
        for index, group in enumerate(groups):
            card = self.cards.get(group)
            if card is None:
                selected = group[0] if len(group) == 1 else next(
                    (key for key in group if key in selections), None)
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
        self.expanded.add(room_id)
        self.picker.set_occupied(self.entries)
        self._render_profiles()
        QTimer.singleShot(0, self, lambda: self._scroll_to(room_id))
        self.changed.emit()
        if room_id in self.removed_profiles:
            self.removed_profiles.pop(room_id)
            self.removal_order = tuple(key for key in self.removal_order if key != room_id)
            if self.removed_profiles:
                self._show_removal_notice()
            else:
                self._clear_removal()
                self.undo_notice.confirm(0)

    def _scroll_to(self, room_id):
        for group, card in self.cards.items():
            if room_id in group:
                self.scroll.ensureWidgetVisible(card, 0, 8)
                break

    def set_expanded(self, room_ids, expanded):
        if expanded:
            self.expanded.update(room_ids)
        else:
            self.expanded.difference_update(room_ids)

    def set_windows_notice_available(self, enabled):
        self.windows_notice_available = enabled
        for card in self.cards.values():
            card.update_summary()

    def remove(self, room_ids):
        removed = [room_id for room_id in room_ids if room_id in self.entries]
        if not removed:
            return
        self.removal_order = tuple(dict.fromkeys((*self.removal_order, *self.entries)))
        for room_id in removed:
            self.removed_profiles[room_id] = self.entries.pop(room_id), room_id in self.expanded
            self.expanded.discard(room_id)
            self.requests.pop(room_id, None)
        self._refresh_removed_profiles()
        self._show_removal_notice()

    def undo_removal(self, room_id=None):
        targets = tuple(self.removed_profiles) if room_id is None else (room_id,)
        if not targets or any(key not in self.removed_profiles for key in targets):
            return
        for key in targets:
            row, expanded = self.removed_profiles.pop(key)
            self.entries[key] = row
            if expanded:
                self.expanded.add(key)
        order = dict.fromkeys((*self.removal_order, *self.entries))
        self.entries = {key: self.entries[key] for key in order if key in self.entries}
        self._refresh_removed_profiles()
        if self.removed_profiles:
            self._show_removal_notice()
        else:
            self._clear_removal()
            self.undo_notice.confirm(len(targets))

    def _show_removal_notice(self):
        self.undo_notice.present({room_id: self.rooms[room_id] for room_id in self.removed_profiles})

    def _clear_removal(self):
        self.removed_profiles.clear()
        self.removal_order = ()

    def _refresh_removed_profiles(self):
        self.picker.set_occupied(self.entries)
        self._render_profiles()
        self.changed.emit()

    def edit(self, field, values):
        changed = False
        for room_id, value in values.items():
            row = self.entries[room_id]
            if row.get(field) == value:
                continue
            if value is None:
                row.pop(field, None)
            else:
                row[field] = value
            changed = True
        if changed:
            self.regroup_timer.start(0)
            self.changed.emit()

    def request_quality(self, room_id):
        options, error = self.qualities.get(room_id, ([], ''))
        if room_id in self.requests or (options and not error):
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
            if room_id in card.editing_rooms:
                card.update_quality()

    def values(self):
        return {'streamer_defaults': {room_id: dict(row) for room_id, row in self.entries.items()},
                'streamer_defaults_merge_identical': self.merge.isChecked()}
