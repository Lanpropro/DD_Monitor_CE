"""Compact audio controls for the selected PiP panes."""
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSlider, QVBoxLayout, QWidget

from . import theme
from .ui import Avatar, VolumeButton
from .widgets import VolumePopup


class AudioRow(QWidget):
    def __init__(self, name, index, change_volume, change_mute, parent):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.avatar = Avatar(name, index, size=28, parent=self)
        self.avatar.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.avatar.setToolTip(name)
        self.avatar.setAccessibleName(name)
        self._face_key = None
        self.mute = VolumeButton(self, size=theme.TILE_CONTROL_HEIGHT)
        self.mute.setAccessibleName(name + '静音')
        self.mute.clicked.connect(lambda: change_mute(not self.mute.muted))
        self.mute.volumeChanged.connect(change_volume)
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setMinimumWidth(60)
        self.slider.setAccessibleName(name + '音量')
        self.slider.valueChanged.connect(change_volume)
        self.value = QLabel(self)
        self.value.setFixedWidth(34)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for widget in (self.avatar, self.mute, self.slider, self.value):
            layout.addWidget(widget, 1 if widget is self.slider else 0)

    def set_avatar(self, pixmap):
        if pixmap is not None and not pixmap.isNull() and pixmap.cacheKey() != self._face_key:
            self._face_key = pixmap.cacheKey()
            self.avatar.set_pixmap_image(pixmap)

    def sync(self, volume, muted, channel):
        self.slider.blockSignals(True)
        self.slider.setValue(volume)
        self.slider.blockSignals(False)
        self.mute.set_state(muted, volume, channel)
        self.mute.setToolTip('点击取消静音，滚轮调音量' if muted else '点击静音，滚轮调音量')
        self.value.setText(str(volume) + '%')


class PictureInPictureAudio(VolumePopup):
    def __init__(self, owner):
        super().__init__(owner, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.owner = owner
        self.controller = owner.controller
        self.setAttribute(Qt.WA_NoMouseReplay)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName('TileVolumePopup')
        theme.refresh_theme_properties(self)
        self.setFixedWidth(300)
        self.setStyleSheet('''
            #TileVolumePopup QScrollArea, #TileVolumePopup QScrollArea > QWidget,
            #TileVolumePopup QScrollArea > QWidget > QWidget { background: transparent; border: none; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel('分路音量', self))
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.scroll)
        self.rows = {}
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)

    def rebuild(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        self.rows = {}
        for index in self.controller.selection:
            tile = self.controller.host.wall.tiles[index]
            name = str(tile.room.get('uname') or tile.room.get('room_id'))
            row = AudioRow(name, index, lambda value, tile=tile: self._tile_volume(tile, value),
                           lambda muted, tile=tile: self._tile_mute(tile, muted), content)
            self.rows[tile] = row
            layout.addWidget(row)
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroll.setWidget(content)
        self.refresh()

    def _tile_volume(self, tile, value):
        tile.set_volume(value)
        self.refresh()

    def _tile_mute(self, tile, muted):
        tile.set_muted(muted)
        self.refresh()

    def refresh(self):
        items = {str(item.room.get('room_id')): item for item in self.controller.host.sidebar._items}
        for tile, row in self.rows.items():
            row.sync(tile.volume, tile.muted, tile.audio_channel)
            item = items.get(str(tile.room.get('room_id')))
            if item is not None:
                row.set_avatar(item.thumb.face_pixmap())

    def _position(self):
        screen = self.owner.screen().availableGeometry().adjusted(6, 6, -6, -6)
        self.ensurePolished()
        content_height = self.scroll.widget().sizeHint().height() if self.scroll.widget() is not None else 0
        self.scroll.setFixedHeight(min(260, max(60, screen.height() - 220), content_height + 4))
        self.layout().activate()
        self.adjustSize()
        anchor = self.owner.audio_tools.geometry()
        x = max(screen.left(), min(anchor.right() - self.width(), screen.right() - self.width() + 1))
        y = max(screen.top(), min(anchor.top() - self.height() - 6, screen.bottom() - self.height() + 1))
        self.move(x, y)

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.rebuild()
            self._position()
            self.show()
            self.owner.audio_button.setChecked(True)
            self.raise_()
            next(iter(self.rows.values())).slider.setFocus(Qt.PopupFocusReason)

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        self.owner.audio_button.setChecked(False)
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)


class AudioFeedback(QLabel):
    def __init__(self, owner):
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus
        super().__init__(owner, flags)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet('background: rgba(0,0,0,190); color: #fff; border-radius: 8px; padding: 8px;')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def display(self, tile):
        owner = self.parentWidget()
        text = '已静音' if tile.muted else str(tile.volume) + '%'
        name = str(tile.room.get('uname') or tile.room.get('room_id'))
        self.setText(name[:16] + '  ' + text)
        self.adjustSize()
        self.move(owner.mapToGlobal(QPoint((owner.width() - self.width()) // 2, max(0, owner.height() - self.height() - 12))))
        self.show()
        self.raise_()
        self.timer.start(1200)
