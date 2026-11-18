"""Avatar and name card shared by room pickers."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy, QVBoxLayout

from . import theme
from .ui import Avatar, ElidedLabel


class RoomChoice(QPushButton):
    def __init__(self, room, name, index, pixmap, parent, *, platform_label=''):
        super().__init__(parent)
        self.preview_name = name
        self.setObjectName('PipRoomChoice')
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(80 if platform_label else 64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(' · '.join(part for part in (name, str(room['room_id']), platform_label) if part))
        self.setAccessibleName(self.toolTip())
        box = QVBoxLayout(self)
        box.setContentsMargins(5, 5, 5, 4)
        box.setSpacing(3)
        display = str(room.get('uname') or room['room_id'])
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
        self.badge.move(self.width() - 20, 4)
