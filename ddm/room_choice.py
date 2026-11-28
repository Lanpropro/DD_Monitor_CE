"""Avatar and name card shared by room pickers."""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout

from . import theme
from .avatar_widgets import AVATAR_COLORS, circular_pixmap
from .ui import Avatar, ElidedLabel


class PreviewAvatar(Avatar):
    def __init__(self, name, index, pixmap, parent):
        super().__init__(name, index, size=20, parent=parent)
        self.set_pixmap_image(pixmap)

    def center_in(self, rect):
        size = min(38, rect.width() - 6, rect.height() - 6)
        self.setVisible(size >= 8)
        if size >= 8:
            self.set_size(size)
            self.move(rect.x() + (rect.width() - size) // 2, rect.y() + (rect.height() - size) // 2)


class RoomChoice(QPushButton):
    def __init__(self, room, name, index, pixmap, parent, *, platform_label='', compact=False):
        super().__init__(parent)
        self.preview_name = name
        self.avatar_index = index
        self.face = pixmap
        self.compact = compact
        self.setObjectName('PipRoomChoice')
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(80 if platform_label else 64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(' · '.join(part for part in (name, str(room['room_id']), platform_label) if part))
        self.setAccessibleName(self.toolTip())
        display = str(room.get('uname') or room['room_id'])
        if compact:
            self.setMinimumHeight(54)
            self.display_name = display
            self._portrait = None
            return
        box = QVBoxLayout(self)
        box.setContentsMargins(5, 5, 5, 4)
        box.setSpacing(3)
        self.avatar = Avatar(display, index, size=28, parent=self)
        self.avatar.set_pixmap_image(pixmap)
        box.addWidget(self.avatar, 0, Qt.AlignHCenter)
        label = ElidedLabel(display, self)
        label.setStyleSheet(f'color: {theme.TEXT1};')
        label.setAlignment(Qt.AlignCenter)
        label.setTextFormat(Qt.PlainText)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        box.addWidget(label)
        if platform_label:
            from .room_artwork import platform_icon, room_platform

            platform = QLabel(self, objectName='RoomChoicePlatform')
            platform.setAlignment(Qt.AlignCenter)
            platform.setPixmap(platform_icon(room_platform(room)).pixmap(16, 16))
            platform.setAccessibleName(platform_label)
            platform.setAttribute(Qt.WA_TransparentForMouseEvents)
            box.addWidget(platform, 0, Qt.AlignHCenter)
        self.badge = QLabel('✓', self)
        self.badge.setObjectName('PipChoiceBadge')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.badge.setFixedSize(16, 16)
        self.badge.hide()
        self.toggled.connect(self.badge.setVisible)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.compact:
            self.badge.move(self.width() - 20, 4)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.compact:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        avatar = QRect((self.width() - 28) // 2, 5, 28, 28)
        if self.face is not None and not self.face.isNull():
            ratio = self.devicePixelRatioF()
            if self._portrait is None or self._portrait.devicePixelRatioF() != ratio:
                self._portrait = circular_pixmap(self.face, round(28 * ratio))
                self._portrait.setDevicePixelRatio(ratio)
            painter.drawPixmap(avatar.topLeft(), self._portrait)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(AVATAR_COLORS[self.avatar_index % len(AVATAR_COLORS)]))
            painter.drawEllipse(avatar)
            painter.setPen(QColor(theme.TEXT1))
            painter.drawText(avatar, Qt.AlignCenter, self.display_name[:1])
        label = self.rect().adjusted(5, avatar.bottom() + 3, -5, -2)
        painter.setPen(QColor(theme.TEXT1))
        painter.drawText(label, Qt.AlignCenter, self.fontMetrics().elidedText(
            self.display_name, Qt.ElideRight, label.width()))
        if self.isChecked():
            badge = QRect(self.width() - 20, 4, 16, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawEllipse(badge)
            painter.setPen(Qt.white)
            painter.drawText(badge, Qt.AlignCenter, '✓')
