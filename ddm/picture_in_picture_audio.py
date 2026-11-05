"""Compact audio controls for the selected PiP panes."""
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget

from .ui import ElidedLabel


class AudioSlider(QSlider):
    def __init__(self, parent):
        super().__init__(Qt.Horizontal, parent)
        self.setRange(0, 100)
        self.setSingleStep(5)
        self.setPageStep(10)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta:
            self.setValue(self.value() + (5 if delta > 0 else -5))
        event.accept()


class AudioRow(QWidget):
    def __init__(self, name, change_volume, change_mute, parent):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.name = ElidedLabel(name, self)
        self.name.setTextFormat(Qt.PlainText)
        layout.addWidget(self.name)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.mute = QPushButton(self)
        self.mute.setCheckable(True)
        self.mute.setFixedWidth(62)
        self.mute.setAccessibleName(name + '静音')
        self.mute.clicked.connect(change_mute)
        self.slider = AudioSlider(self)
        self.slider.setMinimumWidth(60)
        self.slider.setAccessibleName(name + '音量')
        self.slider.valueChanged.connect(change_volume)
        self.value = QLabel(self)
        self.value.setFixedWidth(34)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for widget in (self.mute, self.slider, self.value):
            controls.addWidget(widget, 1 if widget is self.slider else 0)
        layout.addLayout(controls)

    def sync(self, volume, muted):
        self.slider.blockSignals(True)
        self.slider.setValue(volume)
        self.slider.blockSignals(False)
        self.mute.setChecked(muted)
        self.mute.setText('已静音' if muted else '静音')
        self.value.setText(str(volume) + '%')


class PictureInPictureAudio(QFrame):
    def __init__(self, owner):
        super().__init__(owner, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.owner = owner
        self.controller = owner.controller
        self.setAttribute(Qt.WA_NoMouseReplay)
        self.setObjectName('PipAudioPanel')
        self.setFixedWidth(300)
        self.setStyleSheet('''
            #PipAudioPanel { background: #202328; color: #e7ebf0; border: 1px solid #41454c; border-radius: 10px; }
            #PipAudioPanel QLabel { color: #e7ebf0; background: transparent; }
            #PipAudioPanel QPushButton { background: #30343b; color: #dce1e8; border: none; border-radius: 6px; padding: 5px; min-height: 20px; }
            #PipAudioPanel QPushButton:hover { background: #414751; }
            #PipAudioPanel QPushButton:checked { background: #16495b; color: #55c9ef; }
            #PipAudioPanel QScrollArea { background: transparent; border: none; }
            #PipAudioPanel QScrollArea > QWidget > QWidget { background: #202328; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self.master = AudioRow('画中画总音量', self._volume, self._mute, self)
        layout.addWidget(self.master)
        self.expand = QPushButton('分路音量 +', self)
        self.expand.setCheckable(True)
        self.expand.toggled.connect(self._expand)
        layout.addWidget(self.expand)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.hide()
        layout.addWidget(self.scroll)
        shortcuts = self.controller.host.shortcuts
        hint = QLabel(f"鼠标指向画面：↑↓ 音量 · {shortcuts.get('mute', 'M')} 静音 · {shortcuts.get('solo', 'Alt+M')} 独听", self)
        hint.setWordWrap(True)
        hint.setStyleSheet('font-size: 11px; color: #aab1bc;')
        layout.addWidget(hint)
        self.rows = {}
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)

    def _volume(self, value):
        self.controller.set_master_audio(volume=value)
        self.refresh()

    def _mute(self, value):
        self.controller.set_master_audio(muted=value)
        self.refresh()

    def rebuild(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        self.rows = {}
        for index in self.controller.selection:
            tile = self.controller.host.wall.tiles[index]
            name = str(tile.room.get('uname') or tile.room.get('room_id'))
            row = AudioRow(name, lambda value, tile=tile: self._tile_volume(tile, value),
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
        self.master.sync(self.controller.master_volume, self.controller.master_muted)
        for tile, row in self.rows.items():
            row.sync(tile.volume, tile.muted)

    def _expand(self, expanded):
        self.expand.setText('收起分路音量 −' if expanded else '分路音量 +')
        self.scroll.setVisible(expanded)
        self._position()

    def _position(self):
        screen = self.owner.screen().availableGeometry().adjusted(6, 6, -6, -6)
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
            self.master.slider.setFocus(Qt.PopupFocusReason)

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
        if owner.controller.master_muted:
            text += ' · 总静音'
        elif owner.controller.master_volume == 0:
            text += ' · 总音量 0%'
        name = str(tile.room.get('uname') or tile.room.get('room_id'))
        self.setText(name[:16] + '  ' + text)
        self.adjustSize()
        self.move(owner.mapToGlobal(QPoint((owner.width() - self.width()) // 2, max(0, owner.height() - self.height() - 12))))
        self.show()
        self.raise_()
        self.timer.start(1200)
