"""The status list shared by the sidebar and system tray."""
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import images, theme
from .avatar_widgets import FollowAvatar, RoomStrip
from .follow_folders import PLATFORM_NAMES
from .room_artwork import platform_icon
from .ui.labels import ElidedLabel


STATUS_LABELS = {
    'recording': '正在录制',
    'reconnecting': '等待重连',
    'preparing': '准备录制',
    'stopping': '正在收尾',
    'failed': '录制启动失败',
    'monitoring': '监控中',
}


def monitor_platform_badge(parent, platform, size=16):
    badge = QLabel(parent)
    badge.setFixedSize(size, size)
    badge.setAlignment(Qt.AlignCenter)
    badge.setStyleSheet(f'background: palette(window); border-radius: {size // 2}px;')
    badge.setPixmap(platform_icon(platform).pixmap(size - 3, size - 3))
    badge.setAccessibleName(PLATFORM_NAMES.get(platform, platform))
    return badge


def monitor_status_badge(state):
    badge = QLabel(STATUS_LABELS[state], objectName='BadgeLive' if state == 'recording' else 'BadgeOff')
    if state == 'monitoring':
        badge.setStyleSheet(f'background: #006fa3; color: white; border: none; '
                            f'border-radius: {theme.RADIUS_MD}px;')
    return badge


def monitor_elapsed(started_at, now):
    hours, remaining = divmod(max(0, int(now - started_at)), 3600)
    minutes, seconds = divmod(remaining, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'


def monitor_identifier(entry):
    if entry.account_id:
        return f'ID {entry.account_id}'
    return f'房间号 {entry.display_room_id or entry.room_id}'


class _MonitorRow(QWidget):
    def __init__(self, entry, *, compact=False):
        super().__init__()
        self.entry = entry
        box = QHBoxLayout(self)
        padding = 2 if compact else 4
        box.setContentsMargins(4, padding, 6, padding)
        box.setSpacing(8)
        size = 24 if compact else RoomStrip.AVATAR
        ring_margin = 7
        logo_size = 13 if compact else 16
        portrait_box = QWidget(self)
        portrait_size = size + 2 * ring_margin
        portrait_box.setFixedSize(portrait_size, portrait_size)
        if entry.state == 'recording':
            self.avatar = FollowAvatar(entry.name, 2, size=portrait_size, ring_margin=ring_margin,
                                       recording_color=theme.PINK, parent=portrait_box)
            self.avatar.set_recording_state('recording')
        else:
            self.avatar = FollowAvatar(entry.name, 2, size=size, parent=portrait_box)
            self.avatar.move(ring_margin, ring_margin)
        self.avatar.set_pixmap_image(images.load_room_avatar(entry.room_id))
        if entry.platform:
            self.platform_badge = monitor_platform_badge(portrait_box, entry.platform, logo_size)
            self.platform_badge.move(ring_margin + size - logo_size, ring_margin + size - logo_size)
        box.addWidget(portrait_box)

        identity = QVBoxLayout()
        identity.setAlignment(Qt.AlignVCenter)
        identity.setSpacing(1)
        self.name = ElidedLabel(entry.name)
        self.name.setTextFormat(Qt.PlainText)
        self.name.setToolTip(entry.name)
        self.name.setAccessibleName(entry.name)
        identity.addWidget(self.name)
        identifier = monitor_identifier(entry)
        self.identifier = ElidedLabel(identifier)
        self.identifier.setTextFormat(Qt.PlainText)
        self.identifier.setToolTip(identifier)
        self.identifier.setObjectName('AppSubtitle')
        identity.addWidget(self.identifier)
        box.addLayout(identity, 1)

        status_box = QVBoxLayout()
        status_box.setAlignment(Qt.AlignVCenter)
        status_box.setSpacing(2)
        self.status = monitor_status_badge(entry.state)
        status_box.addWidget(self.status, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.elapsed = QLabel(self, objectName='AppSubtitle')
        self.elapsed.setAccessibleName('录制时长')
        self.elapsed.setVisible(bool(entry.started_at))
        status_box.addWidget(self.elapsed, 0, Qt.AlignRight)
        box.addLayout(status_box)

    def update_elapsed(self, now):
        if self.entry.started_at:
            self.elapsed.setText(monitor_elapsed(self.entry.started_at, now))


class StreamerMonitorPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.read_rows = tuple
        self._snapshot = None
        self._room_rows = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea(self)
        self.scroll.setAccessibleName('主播与录制状态')
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)
        self.rows.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(holder)
        layout.addWidget(self.scroll)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)

    def refresh(self):
        rows = self.read_rows()
        if rows != self._snapshot:
            self._replace_rows(rows)
        self._update_elapsed(time.monotonic())

    def _update_elapsed(self, now):
        for row in self._room_rows.values():
            row.update_elapsed(now)

    def _replace_rows(self, rows):
        self._snapshot = rows
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value()
        self._room_rows.clear()
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self._populate(rows)
        self.rows.activate()
        self.updateGeometry()
        scrollbar.setValue(position)

    def _populate(self, rows):
        if not rows:
            empty = QLabel('暂无监控或录制中的主播')
            empty.setObjectName('SettingsHint')
            empty.setWordWrap(True)
            self.rows.addWidget(empty)
        for entry in rows:
            self._add_row(entry)

    def _add_row(self, entry, *, compact=False):
        row = _MonitorRow(entry, compact=compact)
        self._room_rows[entry.room_id] = row
        self.rows.addWidget(row)

    def set_room_avatar(self, room_id, pixmap):
        row = self._room_rows.get(str(room_id))
        if row is not None:
            row.avatar.set_pixmap_image(pixmap)

    def sizeHint(self):
        return QSize(296, min(320, max(24, self.rows.sizeHint().height()) + 4))

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)
