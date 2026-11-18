"""Bottom-anchored removal feedback for the streamer settings page."""
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .corner_geometry import continuous_path
from .ui import ActionButton, Avatar, ElidedLabel


class StreamerRemovalNotice(QWidget):
    undo_requested = Signal()
    expired = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 12, 10)
        row.setSpacing(16)
        self.pile = QWidget(self)
        self.pile.setFixedHeight(34)
        row.addWidget(self.pile)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        self.title = ElidedLabel('', self)
        self.title.setTextFormat(Qt.PlainText)
        texts.addWidget(self.title)
        self.message = QLabel(self)
        self.message.setTextFormat(Qt.PlainText)
        texts.addWidget(self.message)
        row.addLayout(texts, 1)
        self.undo_button = ActionButton('撤回', self)
        self.undo_button.setAutoDefault(False)
        self.undo_button.clicked.connect(self.undo_requested)
        row.addWidget(self.undo_button)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._expire)
        parent.installEventFilter(self)
        theme.signals().changed.connect(self.update)
        self.hide()

    def present(self, rooms):
        for avatar in self.pile.findChildren(Avatar):
            avatar.hide()
            avatar.deleteLater()
        faces = rooms[-3:]
        self.pile.setFixedWidth(34 + 20 * (len(faces) - 1))
        self.pile.show()
        for index, room in enumerate(faces):
            avatar = Avatar(room['name'], index, size=34, parent=self.pile)
            if room.get('avatar'):
                avatar.set_pixmap_image(QPixmap(room['avatar']))
            avatar.move(index * 20, 0)
            avatar.show()
        single = len(rooms) == 1
        self.title.setText(rooms[0]['name'] if single else '')
        self.title.setVisible(single)
        self.message.setText('已移除主播设置' if single else f'已移除 {len(rooms)} 位主播的设置')
        self.setAccessibleName(self.message.text())
        self.undo_button.setText('撤回' if single else '全部撤回')
        self.undo_button.show()
        self.reposition()
        self.show()
        self.raise_()
        self.timer.start(10000)

    def confirm(self, count):
        if count == 0:
            self.hide()
            self.timer.stop()
            return
        self.title.hide()
        self.pile.hide()
        self.undo_button.hide()
        self.message.setText(f'已恢复 {count} 位主播的设置')
        self.setAccessibleName(self.message.text())
        self.reposition()
        self.timer.start(3000)

    def _expire(self):
        focus = QApplication.focusWidget()
        if (self.isVisible() and not self.undo_button.isHidden()
                and (self.underMouse() or focus is not None and self.isAncestorOf(focus))):
            self.timer.start(1000)
            return
        self.hide()
        self.expired.emit()

    def reposition(self):
        parent = self.parentWidget()
        width = max(1, min(640, parent.width() - 48))
        height = max(56, self.sizeHint().height())
        self.setGeometry((parent.width() - width) // 2, parent.height() - height - 24, width, height)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.reposition()
        return super().eventFilter(watched, event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor('#ffffff' if theme.is_light() else '#3c4044'))
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12))
