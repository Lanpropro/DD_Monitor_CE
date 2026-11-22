"""Read-only recording and monitoring groups inside the root tray menu."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from . import images
from .avatar_widgets import Avatar
from .streamer_monitor_panel import StreamerMonitorPanel, monitor_platform_badge


class TrayMonitorOverview(StreamerMonitorPanel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName('主播监控概览')
        self._stack_avatars = {}

    def _populate(self, rows):
        self._stack_avatars.clear()
        monitored = [entry for entry in rows if entry.state in ('monitoring', 'failed')]
        recordings = [entry for entry in rows if entry.state not in ('monitoring', 'failed')]
        self._add_heading('录制', len(recordings))
        for entry in recordings:
            self._add_row(entry)

        self._add_heading('监控', len(monitored))
        watching = [entry for entry in monitored if entry.state == 'monitoring']
        if len(watching) > 3:
            self.rows.addWidget(self._avatar_stack(watching), 0, Qt.AlignLeft)
            monitored = [entry for entry in monitored if entry.state == 'failed']
        for entry in monitored:
            self._add_row(entry)

    def _add_heading(self, text, count):
        heading = QWidget()
        layout = QHBoxLayout(heading)
        layout.setContentsMargins(8, 4, 8, 3)
        label = QLabel(text, heading, objectName='AppTitle')
        total = QLabel(f'{count} 位', heading, objectName='AppSubtitle')
        layout.addWidget(label, 1)
        layout.addWidget(total)
        self.rows.addWidget(heading)

    def _avatar_stack(self, entries):
        shown = entries[:5]
        more = len(entries) - len(shown)
        size, stride = 34, 23
        stack = QWidget(objectName='TrayMonitorAvatars')
        stack.setAccessibleName('、'.join(entry.name for entry in shown))
        width = size + stride * (len(shown) - 1)
        for index, entry in enumerate(shown):
            rim = QWidget(stack, objectName='TrayMonitorAvatarRim')
            rim.setFixedSize(size, size)
            rim.setStyleSheet('#TrayMonitorAvatarRim {background: palette(window); border: 1px solid palette(mid); '
                              'border-radius: 17px;}')
            rim.move(index * stride, 0)
            avatar = Avatar(entry.name, index, size=28, parent=rim)
            avatar.setAccessibleName(entry.name)
            avatar.move(3, 3)
            avatar.set_pixmap_image(images.load_room_avatar(entry.room_id))
            if entry.platform:
                monitor_platform_badge(rim, entry.platform, 13).move(0, size - 13)
            self._stack_avatars[entry.room_id] = avatar
        if more:
            remaining = QLabel(f'+{more}', stack, objectName='BadgeOff')
            remaining.setAccessibleName(f'另有 {more} 位正在监控')
            remaining.setAlignment(Qt.AlignCenter)
            remaining.setFixedSize(max(size, remaining.sizeHint().width() + 8), size - 6)
            remaining.move(width + 4, 3)
            width += remaining.width() + 4
        stack.setFixedSize(width, size)
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(8, 1, 8, 4)
        layout.addWidget(stack)
        return holder

    def set_room_avatar(self, room_id, pixmap):
        super().set_room_avatar(room_id, pixmap)
        avatar = self._stack_avatars.get(str(room_id))
        if avatar is not None:
            avatar.set_pixmap_image(pixmap)
