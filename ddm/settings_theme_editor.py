"""Inline accent and installed-font choices using the shared settings controls."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QSpinBox, QWidget

from . import theme
from .appearance_preferences import normalize
from .settings_material import segment_motion_enabled
from .ui import SelectControl, StepperControl
from .ui.color_dialog import ColorPalette


class SettingsThemeEditor(QWidget):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel('主题色'), 0, 0)
        self.swatch_palette = ColorPalette((
            ('', '默认蓝色', lambda: '#007ba8' if theme.is_light() else '#00a1d6'),
            ('#20b976', '绿色', '#20b976'), ('#8866ee', '紫色', '#8866ee'),
            ('#ef638e', '粉色', '#ef638e'), ('#f58b32', '橙色', '#f58b32')), self)
        self.swatch_palette.selected.connect(self.set_accent)
        grid.addWidget(self.swatch_palette, 0, 1, Qt.AlignRight)
        grid.addWidget(QLabel('自定义色值'), 1, 0)
        self.accent = QLineEdit()
        self.accent.setFixedWidth(180)
        self.accent.setMaxLength(7)
        self.accent.setPlaceholderText('#RRGGBB（空为默认）')
        self.accent.setAccessibleName('自定义主题色')
        self.accent.editingFinished.connect(self._edit_accent)
        grid.addWidget(self.accent, 1, 1, Qt.AlignRight)
        grid.addWidget(QLabel('界面字体'), 2, 0)
        self.font = SelectControl()
        self.font.setFixedWidth(180)
        self.font.setAccessibleName('界面字体')
        self.font.addItem('系统默认', '')
        for family in QFontDatabase.families():
            self.font.addItem(family, family)
        self.font.currentIndexChanged.connect(self._font_changed)
        grid.addWidget(self.font, 2, 1, Qt.AlignRight)
        font_size_label = QLabel('界面字号')
        font_size_hint = '字体与字号用于主界面、设置、按钮和列表；弹幕及视频内文字仍由各自设置控制。'
        font_size_label.setToolTip(font_size_hint)
        grid.addWidget(font_size_label, 3, 0)
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 20)
        self.font_size.setSuffix(' px')
        self.font_size.setAccessibleName('界面字号')
        self.font_size.setToolTip(font_size_hint)
        self.font_size.valueChanged.connect(self._font_changed)
        grid.addWidget(StepperControl(self.font_size), 3, 1, Qt.AlignRight)
        self.set_values(settings)

    def set_values(self, settings):
        self._values = normalize(settings)
        self.accent.setText(self._values['appearance_accent'])
        index = self.font.findData(self._values['appearance_font'])
        previous = self.font.blockSignals(True)
        self.font.setCurrentIndex(max(0, index))
        self.font.blockSignals(previous)
        previous = self.font_size.blockSignals(True)
        self.font_size.setValue(self._values['appearance_font_size'])
        self.font_size.blockSignals(previous)
        self.swatch_palette.set_current(self._values['appearance_accent'])

    def values(self):
        return {**self._values, 'appearance_font': self.font.currentData() or '',
                'appearance_font_size': self.font_size.value()}

    def set_accent(self, color, pointer=False):
        self._values['appearance_accent'] = color
        self.accent.setText(color)
        self.swatch_palette.set_current(color, animate=pointer and segment_motion_enabled(self))
        self.changed.emit()

    def _edit_accent(self):
        value = self.accent.text().strip()
        parsed = normalize({'appearance_accent': value})['appearance_accent']
        if value and not parsed:
            self.accent.setToolTip('请输入六位十六进制颜色，例如 #00a1d6')
            return
        self.set_accent(parsed)

    def _font_changed(self, *_args):
        self.changed.emit()
