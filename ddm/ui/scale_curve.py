"""Shared control for the video danmaku and SC scaling curves."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from ..viewport_scale import viewport_scale


class ScaleCurveControl(QWidget):
    valueChanged = Signal(int)

    def __init__(self, value=35, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setAccessibleName('随画面缩放强度')
        self.slider.setToolTip('0：保持手动大小；100：完全随画面等比缩放。值越小，小格子里的内容越大')
        self.label = QLabel()
        self.label.setMinimumWidth(28)
        row.addWidget(self.slider, 1)
        row.addWidget(self.label)
        box.addLayout(row)
        self.example = QLabel()
        self.example.setObjectName('SettingsHint')
        self.example.setWordWrap(True)
        box.addWidget(self.example)
        self.slider.valueChanged.connect(self._changed)
        self.setValue(value)
        self._changed(self.value())

    def value(self):
        return self.slider.value()

    def setValue(self, value):
        self.slider.setValue(value)

    def _changed(self, value):
        self.label.setText(str(value))
        self.example.setText('画面高 180 / 360 / 720 px 时：' + ' / '.join(
            f'{viewport_scale(height, value):.0%}' for height in (180, 360, 720)))
        self.valueChanged.emit(value)
