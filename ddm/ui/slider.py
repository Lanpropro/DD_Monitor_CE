"""Consistent settings slider length and readable numeric readouts."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider

from .. import theme


class SettingsSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.setFixedWidth(theme.SETTINGS_SLIDER_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class SettingsValueLabel(QLabel):
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setObjectName('SettingsValue')
        self.setFixedWidth(40)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
