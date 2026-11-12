"""Shared settings controls using the application's existing QSS roles."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout


class ActionButton(QPushButton):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setObjectName('IconButton')
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)


class TitleLabel(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setObjectName('SettingsTitle')


class HintLabel(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setObjectName('SettingsHint')
        self.setWordWrap(True)


def page_header(title: str, hint: str) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(4)
    box.addWidget(TitleLabel(title))
    if hint:
        box.addWidget(HintLabel(hint))
    return box


def step_button(text: str, tooltip: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName('StepButton')
    button.setFixedSize(28, 28)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tooltip)
    button.clicked.connect(slot)
    return button
