"""Update byte details beside the settings library progress bar."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QStackedLayout, QWidget
from . import theme
from .download_progress import progress_text
from .ui import ElidedLabel, SettingsProgressBar


class UpdateProgress(QWidget):
    def __init__(self, parent=None, *, button=None):
        super().__init__(parent)
        self.button = button
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
            if state.get('phase') == 'failed':
                self.button.setText('重试')
        self.show()
