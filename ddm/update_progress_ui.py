"""Update byte details beside the settings library progress bar."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QStackedLayout, QLabel, QSizePolicy, QWidget
from . import theme
from .download_progress import progress_text
from .ui import ElidedLabel, SettingsProgressBar


class UpdateProgress(QWidget):
    def __init__(self, parent=None, *, button=None, alignment=Qt.AlignRight):
        super().__init__(parent)
        self.button = button
        self._idle_icon = button.icon() if button is not None else QIcon()
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.bar = None
        if button is not None:
            idle = QWidget(self)
            actions = QHBoxLayout(idle)
            actions.setContentsMargins(0, 0, 0, 0)
            if alignment == Qt.AlignLeft:
                actions.addWidget(button)
            actions.addStretch(1)
            if alignment == Qt.AlignRight:
                actions.addWidget(button)
            self.stack.addWidget(idle)
            self.setMinimumHeight(theme.CONTROL_HEIGHT)
        else:
            self.hide()

    def _create_feedback(self):
        track = QWidget(self)
        layout = QHBoxLayout(track)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.bar = SettingsProgressBar(track)
        self.bar.setMinimumWidth(120)
        layout.addWidget(self.bar, 1)
        self.details = ElidedLabel(parent=track)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setObjectName('SettingsHint')
        layout.addWidget(self.details)
        self.stack.addWidget(track)
        self.failure = QLabel(self)
        self.failure.setTextFormat(Qt.PlainText)
        self.failure.setObjectName('SettingsHint')
        self.failure.setWordWrap(True)
        self.failure.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if self.button is None:
            self.stack.addWidget(self.failure)
        else:
            actions = self.stack.widget(0).layout()
            index = 1 - actions.indexOf(self.button)
            actions.takeAt(index)
            actions.insertWidget(index, self.failure, 1)
            # Reserve the space opposite the button while the failure label is hidden.
            policy = self.failure.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            self.failure.setSizePolicy(policy)

    def set_state(self, state):
        if self.bar is None:
            self._create_feedback()
        self.bar.setValue(state.get('percent', 0))
        text = progress_text(state)
        self.details.setText(text)
        self.details.setToolTip(text)
        self.bar.setAccessibleDescription(text)
        failed = state.get('phase') == 'failed'
        self.failure.setText(text if failed else '')
        self.failure.setVisible(failed)
        if self.button is None:
            self.stack.setCurrentIndex(1 if failed else 0)
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
