"""Compact RGB picker using the application's shared settings controls."""
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout

from .. import theme
from ..motion import AnimatedDialog
from .basics import ActionButton, page_header
from .slider import SettingsSlider


class ColorDialog(AnimatedDialog):
    colorSelected = Signal(QColor)

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.setWindowTitle('弹幕颜色')
        self.setFixedWidth(440)
        self._color = QColor(color)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addLayout(page_header('弹幕颜色', '调整 RGB 或输入 HEX 色值，确认后应用'))
        self.preview = QLabel('这是一条弹幕预览', self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(76)
        layout.addWidget(self.preview)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.sliders, self.channels = [], []
        for index, label in enumerate(('红 R', '绿 G', '蓝 B')):
            grid.addWidget(QLabel(label), index, 0)
            slider = SettingsSlider(self)
            slider.setRange(0, 255)
            slider.setAccessibleName(label)
            spin = QSpinBox(self)
            spin.setRange(0, 255)
            spin.setFixedWidth(80)
            spin.setAccessibleName(label + ' 数值')
            self.sliders.append(slider)
            self.channels.append(spin)
            for widget in (slider, spin):
                widget.valueChanged.connect(lambda value, i=index: self._set_channel(i, value))
            grid.addWidget(slider, index, 1)
            grid.addWidget(spin, index, 2)
        grid.addWidget(QLabel('HEX'), 3, 0)
        self.hex_edit = QLineEdit(self)
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setPlaceholderText('#RRGGBB')
        self.hex_edit.setAccessibleName('HEX 色值')
        self.hex_edit.textChanged.connect(self._edit_hex)
        grid.addWidget(self.hex_edit, 3, 1, 1, 2)
        layout.addLayout(grid)
        self.hint = QLabel(self)
        self.hint.setObjectName('SettingsHint')
        self.hint.setMinimumHeight(18)
        layout.addWidget(self.hint)
        buttons = QHBoxLayout()
        white = ActionButton('恢复白色', self)
        white.clicked.connect(lambda: self.setCurrentColor(QColor('#ffffff')))
        buttons.addWidget(white)
        buttons.addStretch()
        cancel = ActionButton('取消', self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.confirm = QPushButton('确定', self)
        self.confirm.setObjectName('PrimaryButton')
        self.confirm.setDefault(True)
        self.confirm.clicked.connect(self.accept)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        theme.signals().changed.connect(self._refresh_preview)
        self.setCurrentColor(self._color)

    def _set_channel(self, index, value):
        channels = list(self._color.getRgb()[:3])
        channels[index] = value
        self.setCurrentColor(QColor(*channels))

    def _edit_hex(self, text):
        valid = re.fullmatch(r'#?[0-9a-fA-F]{6}', text) is not None
        self.confirm.setEnabled(valid)
        self.hint.setText('' if valid else '请输入 6 位十六进制颜色，例如 #FFFFFF')
        if valid:
            self.setCurrentColor(QColor('#' + text.lstrip('#')))

    def setCurrentColor(self, color):
        self._color = QColor(color)
        for index, value in enumerate(self._color.getRgb()[:3]):
            for widget in (self.sliders[index], self.channels[index]):
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self.hex_edit.blockSignals(True)
        self.hex_edit.setText(self._color.name().upper())
        self.hex_edit.blockSignals(False)
        self.confirm.setEnabled(True)
        self.hint.clear()
        self._refresh_preview()

    def _refresh_preview(self):
        self.preview.setStyleSheet(f'background:{theme.BASE};color:{self._color.name()};'
                                  f'border:1px solid {theme.BORDER};border-radius:12px;'
                                  'font-size:22px;padding:12px;')

    def currentColor(self):
        return QColor(self._color)

    def accept(self):
        if self.confirm.isEnabled():
            self.colorSelected.emit(self.currentColor())
            super().accept()
