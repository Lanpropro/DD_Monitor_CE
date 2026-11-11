"""Consistent settings slider length and readable numeric readouts."""
from PySide6.QtCore import QEvent, Qt
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
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._sync_width()

    def _sync_width(self):
        self.setFixedWidth(max(40, self.fontMetrics().horizontalAdvance('100%') + 4,
                               self.fontMetrics().horizontalAdvance(self.text()) + 4))

    def setText(self, text):
        super().setText(text)
        self._sync_width()

    def setNum(self, value):
        super().setNum(value)
        self._sync_width()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            self._sync_width()
