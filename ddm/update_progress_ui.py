"""Update byte details beside the settings library progress bar."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget
from .download_progress import progress_text
from .ui import SettingsProgressBar


class UpdateProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.bar = SettingsProgressBar(self)
        self.bar.setMinimumWidth(48)
        layout.addWidget(self.bar, 1)
        self.details = QLabel(self)
        self.details.setTextFormat(Qt.PlainText)
        self.details.setObjectName('SettingsHint')
        self.details.setWordWrap(True)
        layout.addWidget(self.details, 2)
        self.hide()

    def set_state(self, state):
        self.bar.setValue(state.get('percent', 0))
        text = progress_text(state)
        self.details.setText(text)
        self.bar.setAccessibleDescription(text)
        self.show()
