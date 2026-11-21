"""Streamer monitoring status and settings shortcut anchored to the sidebar rail."""
import time

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import images, theme
from .avatar_widgets import FollowAvatar, RoomStrip
from .follow_folders import PLATFORM_NAMES
from .room_artwork import platform_icon
from .sidebar_navigation import NavigationButton
from .ui.labels import ElidedLabel


STATUS_LABELS = {
    'recording': '正在录制',
    'reconnecting': '等待重连',
    'preparing': '准备录制',
    'stopping': '正在收尾',
    'failed': '录制启动失败',
    'monitoring': '监控中',
}


class _MonitorRow(QWidget):
    def __init__(self, entry):
        super().__init__()
        self.entry = entry
        box = QHBoxLayout(self)
        box.setContentsMargins(4, 4, 6, 4)
        box.setSpacing(8)
        size = RoomStrip.AVATAR
        ring_margin = 7
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
            platform_name = PLATFORM_NAMES.get(entry.platform, entry.platform)
            self.platform_badge = QLabel(portrait_box)
            self.platform_badge.setFixedSize(16, 16)
            self.platform_badge.setAlignment(Qt.AlignCenter)
            self.platform_badge.setStyleSheet('background: palette(window); border-radius: 8px;')
            self.platform_badge.setPixmap(platform_icon(entry.platform).pixmap(13, 13))
            self.platform_badge.setAccessibleName(platform_name)
            self.platform_badge.move(ring_margin + size - 16, ring_margin + size - 16)
        box.addWidget(portrait_box)

        identity = QVBoxLayout()
        identity.setAlignment(Qt.AlignVCenter)
        identity.setSpacing(1)
        self.name = ElidedLabel(entry.name)
        self.name.setTextFormat(Qt.PlainText)
        self.name.setToolTip(entry.name)
        self.name.setAccessibleName(entry.name)
        identity.addWidget(self.name)
        identifier = f'ID {entry.account_id}' if entry.account_id else f'房间号 {entry.display_room_id or entry.room_id}'
        self.identifier = ElidedLabel(identifier)
        self.identifier.setTextFormat(Qt.PlainText)
        self.identifier.setToolTip(identifier)
        self.identifier.setObjectName('AppSubtitle')
        identity.addWidget(self.identifier)
        box.addLayout(identity, 1)

        status_box = QVBoxLayout()
        status_box.setAlignment(Qt.AlignVCenter)
        status_box.setSpacing(2)
        self.status = QLabel(STATUS_LABELS[entry.state])
        self.status.setObjectName('BadgeLive' if entry.state == 'recording' else 'BadgeOff')
        if entry.state == 'monitoring':
            self.status.setStyleSheet(f'background: #006fa3; color: white; border: none; '
                                      f'border-radius: {theme.RADIUS_MD}px;')
        status_box.addWidget(self.status, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.elapsed = QLabel(self, objectName='AppSubtitle')
        self.elapsed.setAccessibleName('录制时长')
        self.elapsed.setVisible(bool(entry.started_at))
        status_box.addWidget(self.elapsed, 0, Qt.AlignRight)
        box.addLayout(status_box)

    def update_elapsed(self, now):
        if self.entry.started_at:
            seconds = max(0, int(now - self.entry.started_at))
            hours, minutes = divmod(seconds, 3600)
            minutes, seconds = divmod(minutes, 60)
            self.elapsed.setText(f'{hours:02d}:{minutes:02d}:{seconds:02d}')


class StreamerMonitorMenu(QFrame):
    settingsRequested = Signal()

    def __init__(self, button):
        super().__init__(button, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.button = button
        self.setObjectName('StreamerMonitorMenu')
        self.setAccessibleName('主播监控')
        self.read_rows = tuple
        self._snapshot = None
        self._room_rows = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel('主播监控', self)
        title.setObjectName('AppTitle')
        header.addWidget(title, 1)
        close = NavigationButton('关闭监控', 'close', self)
        close.setFixedSize(26, 26)
        close.clicked.connect(self._dismiss)
        header.addWidget(close)
        layout.addLayout(header)

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
        self.settings_button = QPushButton('主播监控设置', self, objectName='IconButton')
        self.settings_button.clicked.connect(self._open_settings)
        layout.addWidget(self.settings_button)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        button.setCheckable(True)
        button.clicked.connect(self._toggle)
        button.installEventFilter(self)

    def refresh(self):
        rows = self.read_rows()
        now = time.monotonic()
        if rows == self._snapshot:
            for row in self._room_rows.values():
                row.update_elapsed(now)
            return
        self._snapshot = rows
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value()
        self._room_rows.clear()
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        if not rows:
            empty = QLabel('暂无监控或录制中的主播')
            empty.setObjectName('SettingsHint')
            empty.setWordWrap(True)
            self.rows.addWidget(empty)
        for entry in rows:
            row = _MonitorRow(entry)
            row.update_elapsed(now)
            self._room_rows[entry.room_id] = row
            self.rows.addWidget(row)
        self.rows.activate()
        scrollbar.setValue(position)

    def set_room_avatar(self, room_id, pixmap):
        row = self._room_rows.get(str(room_id))
        if row is not None:
            row.avatar.set_pixmap_image(pixmap)

    def _toggle(self, checked):
        if not checked:
            self.hide()
            return
        self.refresh()
        button = self.button
        anchor = button.mapToGlobal(QPoint(0, button.height()))
        area = button.screen().availableGeometry().adjusted(8, 8, -8, -8)
        layout = self.layout()
        header = layout.itemAt(0).sizeHint().height()
        footer = self.settings_button.sizeHint().height()
        padding = layout.contentsMargins().top() + layout.contentsMargins().bottom() + 2 * layout.spacing()
        height = min(360, header + footer + padding + max(24, self.rows.sizeHint().height()) + 4, area.height())
        self.resize(min(320, area.width()), height)
        right = anchor.x() + button.width() + 7
        left = right if right + self.width() <= area.right() + 1 else anchor.x() - self.width() - 7
        top = max(area.top(), min(anchor.y(), area.bottom() + 1) - self.height())
        self.move(max(area.left(), left), top)
        self.show()
        self.scroll.setFocus(Qt.PopupFocusReason)
        self._timer.start()

    def _dismiss(self):
        self.hide()
        self.button.setFocus(Qt.PopupFocusReason)

    def _open_settings(self):
        self._dismiss()
        self.settingsRequested.emit()

    def eventFilter(self, watched, event):
        if watched is self.button and event.type() == QEvent.Hide:
            self.hide()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if self.button.rect().contains(self.button.mapFromGlobal(event.globalPosition().toPoint())):
            self.setAttribute(Qt.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._dismiss()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        self.button.setChecked(False)
        super().hideEvent(event)
