"""Inline accent and installed-font choices using the shared settings controls."""
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QWidget

from .appearance_preferences import normalize
from .ui import SelectControl, StepperControl


class _SwatchButton(QAbstractButton):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.setText('默认' if not color else '')
        self.setProperty('customControlSurface', True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 3, -2, -3)
        if not self.color.isValid():
            from . import theme
            from .settings_material import base_color
            painter.setPen(QPen(theme.qcolor(theme.ACCENT if self.isChecked() else theme.BORDER), 1))
            painter.setBrush(theme.qcolor(base_color(self, 'control', theme.CONTENT)))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(theme.qcolor(theme.ACCENT if self.isChecked() else theme.TEXT2))
            painter.drawText(rect, Qt.AlignCenter, self.text())
            return
        diameter = min(rect.width(), rect.height())
        rect = QRectF(rect.center().x() - diameter / 2, rect.center().y() - diameter / 2, diameter, diameter)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(rect)
        if self.isChecked() or self.hasFocus():
            painter.setPen(QPen(self.palette().text().color(), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(rect.adjusted(-1, -1, 1, 1))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange:
            self.setFixedHeight(max(34, self.fontMetrics().height() + 6))
            if self.text():
                self.setFixedWidth(max(56, self.fontMetrics().horizontalAdvance(self.text()) + 20))


class SettingsThemeEditor(QWidget):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel('主题色'), 0, 0)
        swatches = QHBoxLayout()
        swatches.setSpacing(5)
        self.group = QButtonGroup(self)
        self.swatches = {}
        for color, label in (('', '默认'), ('#00a1d6', '蓝'), ('#20b976', '绿'),
                             ('#8866ee', '紫'), ('#ef638e', '粉'), ('#f58b32', '橙')):
            button = _SwatchButton(color)
            button.setCheckable(True)
            button.setFixedSize(56 if not color else 24, 34)
            button.setAccessibleName('主题色：' + label)
            button.setCursor(Qt.PointingHandCursor)
            self.group.addButton(button)
            self.swatches[color] = button
            button.clicked.connect(lambda _checked=False, value=color: self.set_accent(value))
            swatches.addWidget(button)
        grid.addLayout(swatches, 0, 1, Qt.AlignRight)
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
        grid.addWidget(QLabel('界面字号'), 3, 0)
        self.font_size = QSpinBox()
        self.font_size.setRange(11, 20)
        self.font_size.setSuffix(' px')
        self.font_size.setAccessibleName('界面字号')
        self.font_size.valueChanged.connect(self._font_changed)
        grid.addWidget(StepperControl(self.font_size), 3, 1, Qt.AlignRight)
        hint = QLabel('字体与字号用于主界面、设置、按钮和列表；弹幕及视频内文字仍由各自设置控制。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        grid.addWidget(hint, 4, 0, 1, 2)
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
        self._sync_swatches()

    def values(self):
        return {**self._values, 'appearance_font': self.font.currentData() or '',
                'appearance_font_size': self.font_size.value()}

    def _sync_swatches(self):
        self.group.setExclusive(False)
        for color, button in self.swatches.items():
            button.setChecked(color == self._values['appearance_accent'])
        self.group.setExclusive(True)

    def set_accent(self, color):
        self._values['appearance_accent'] = color
        self.accent.setText(color)
        self._sync_swatches()
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
