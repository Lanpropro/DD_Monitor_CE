"""Update byte details beside the settings library progress bar."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QStackedLayout, QWidget
from . import theme
from .download_progress import progress_text
from .ui import ElidedLabel, SettingsProgressBar


class UpdateProgress(QWidget):
    def __init__(self, parent=None, *, button=None):
        super().__init__(parent)
        self.button = button
        self._idle_icon = button.icon() if button is not None else QIcon()
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.track = QWidget(self)
        layout = QHBoxLayout(self.track)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.bar = SettingsProgressBar(self)
        self.bar.setMinimumWidth(120)
        layout.addWidget(self.bar, 1)
        self.details = ElidedLabel(parent=self)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setObjectName('SettingsHint')
        layout.addWidget(self.details)
        if button is not None:
            idle = QWidget(self)
            actions = QHBoxLayout(idle)
            actions.setContentsMargins(0, 0, 0, 0)
            actions.addStretch(1)
            actions.addWidget(button)
            self.stack.addWidget(idle)
            self.stack.addWidget(self.track)
            self.setMinimumHeight(theme.CONTROL_HEIGHT)
        else:
            self.stack.addWidget(self.track)
            self.hide()

    def set_state(self, state):
        self.bar.setValue(state.get('percent', 0))
        text = progress_text(state)
        self.details.setText(text)
        self.details.setToolTip(text)
        self.bar.setAccessibleDescription(text)
        active = state.get('phase') in ('downloading', 'verifying')
        if self.button is not None:
            self.stack.setCurrentIndex(1 if active else 0)
            self.button.setToolTip(text)
            self.button.setAccessibleDescription(text)
            ready = state.get('phase') == 'ready'
            if self.button.property('updateReady') != ready:
                self.button.setProperty('updateReady', ready)
                if ready:
                    pixmap = QPixmap(32, 32)
                    pixmap.setDevicePixelRatio(2)
                    pixmap.fill(Qt.transparent)
                    painter = QPainter(pixmap)
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setPen(QPen(theme.qcolor(theme.SUCCESS), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    painter.drawLine(3, 8, 6, 11)
                    painter.drawLine(6, 11, 13, 4)
                    painter.end()
                    icon = QIcon()
                    icon.addPixmap(pixmap, QIcon.Normal)
                    icon.addPixmap(pixmap, QIcon.Disabled)
                    self.button.setIcon(icon)
                else:
                    self.button.setIcon(self._idle_icon)
                self.button.style().unpolish(self.button)
                self.button.style().polish(self.button)
                self.button.update()
            if state.get('phase') == 'failed':
                self.button.setText('重试')
        self.show()
