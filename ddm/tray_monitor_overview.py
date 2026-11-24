"""Read-only recording and monitoring groups inside the root tray menu."""
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import images, theme
from .avatar_widgets import Avatar, FollowAvatar
from .streamer_monitor_panel import (StreamerMonitorPanel, monitor_elapsed, monitor_identifier,
                                     monitor_platform_badge, monitor_status_badge, monitored_live_label)


class _ProfileStack(QWidget):
    def __init__(self, entries):
        super().__init__()
        self.shown = entries[:5]
        self.more = len(entries) - len(self.shown)
        self.started_at = min((entry.started_at for entry in entries if entry.started_at), default=0.0)
        self.avatars = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 6, 2)
        layout.setSpacing(8)
        layout.addWidget(self._avatar_stack())
        layout.addStretch(1)

        detail = QVBoxLayout()
        detail.setAlignment(Qt.AlignVCenter)
        detail.setSpacing(2)
        detail.addWidget(monitor_status_badge(entries[0].state), 0, Qt.AlignRight)
        self.elapsed = QLabel(self, objectName='AppSubtitle')
        detail.addWidget(self.elapsed, 0, Qt.AlignRight)
        self.elapsed.setHidden(not self.started_at)
        layout.addLayout(detail)
        self._update_tooltip()

    def _avatar_stack(self):
        size, stride = 36, 24
        stack = QWidget(objectName='TrayMonitorAvatars')
        stack.setAccessibleName('、'.join(entry.name for entry in self.shown))
        width = size + stride * (len(self.shown) - 1)
        for index, entry in enumerate(self.shown):
            rim = QWidget(stack, objectName='TrayMonitorAvatarRim')
            rim.setFixedSize(size, size)
            rim.setStyleSheet('#TrayMonitorAvatarRim {background: palette(window); border: 1px solid palette(mid); '
                              'border-radius: 18px;}')
            rim.move(index * stride, 0)
            if entry.state == 'recording':
                avatar = FollowAvatar(entry.name, index, size=size, ring_margin=6,
                                      recording_color=theme.PINK, parent=rim)
                avatar.set_recording_state('recording')
            else:
                avatar = Avatar(entry.name, index, size=28, parent=rim)
                avatar.move(4, 4)
            avatar.setAccessibleName(entry.name)
            avatar.set_pixmap_image(images.load_room_avatar(entry.room_id))
            if entry.platform:
                monitor_platform_badge(rim, entry.platform, 13).move(0, size - 13)
            self.avatars[entry.room_id] = avatar
        if self.more:
            remaining = QLabel(f'+{self.more}', stack, objectName='BadgeOff')
            remaining.setAccessibleName(f'同组另有 {self.more} 位主播')
            remaining.setAlignment(Qt.AlignCenter)
            remaining.setFixedSize(max(size, remaining.sizeHint().width() + 8), size - 8)
            remaining.move(width + 4, 4)
            width += remaining.width() + 4
        stack.setFixedSize(width, size)
        return stack

    def _update_tooltip(self, now=None):
        lines = []
        for entry in self.shown:
            line = f'{escape(entry.name)} · {escape(monitor_identifier(entry))}'
            if live_label := monitored_live_label(entry):
                line += f' · {live_label}'
            if now is not None and entry.started_at:
                line += f' · {monitor_elapsed(entry.started_at, now)}'
            lines.append(line)
        if self.more:
            lines.append(f'同组另有 {self.more} 位主播')
        self.setToolTip('<qt>' + '<br>'.join(lines) + '</qt>')

    def update_elapsed(self, now):
        self.elapsed.setText(f'最长 {monitor_elapsed(self.started_at, now)}')
        self._update_tooltip(now)


class TrayMonitorOverview(StreamerMonitorPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName('主播监控概览')
        self._stack_avatars = {}
        self._recording_stacks = []

    def _populate(self, rows):
        self._stack_avatars.clear()
        self._recording_stacks.clear()
        monitored = [entry for entry in rows if entry.state in ('monitoring', 'failed')]
        recordings = [entry for entry in rows if entry.state not in ('monitoring', 'failed')]
        self._add_grouped_section('录制', recordings)
        self._add_grouped_section('监控', monitored)

    def _add_grouped_section(self, title, entries):
        self._add_heading(title, len(entries))
        groups = {}
        for entry in entries:
            key = entry.profile_group if entry.profile_group is not None else entry.room_id
            groups.setdefault((entry.state, key), []).append(entry)
        for group in groups.values():
            if len(group) == 1:
                self._add_row(group[0], compact=True)
            else:
                stack = _ProfileStack(group)
                self._stack_avatars.update(stack.avatars)
                if stack.started_at:
                    self._recording_stacks.append(stack)
                self.rows.addWidget(stack)

    def _add_heading(self, text, count):
        heading = QWidget()
        layout = QHBoxLayout(heading)
        layout.setContentsMargins(8, 4, 8, 3)
        label = QLabel(text, heading, objectName='AppTitle')
        total = QLabel(f'{count} 位', heading, objectName='AppSubtitle')
        layout.addWidget(label, 1)
        layout.addWidget(total)
        self.rows.addWidget(heading)

    def _update_elapsed(self, now):
        super()._update_elapsed(now)
        for stack in self._recording_stacks:
            stack.update_elapsed(now)

    def set_room_avatar(self, room_id, pixmap):
        super().set_room_avatar(room_id, pixmap)
        avatar = self._stack_avatars.get(str(room_id))
        if avatar is not None:
            avatar.set_pixmap_image(pixmap)
