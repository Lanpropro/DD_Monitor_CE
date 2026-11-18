"""Compact layout cards for the video count in the PiP picker."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QSizePolicy, QToolButton, QWidget

from . import theme
from .corner_geometry import continuous_path
from .pip_composition import FOCUS_LAYOUT, FREE_LAYOUT, GRID_LAYOUT, MAIN_LAYOUT
from .pip_geometry import pane_rectangles


class PipArrangements(QWidget):
    changed = Signal()

    def __init__(self, mode, parent):
        super().__init__(parent)
        self._preference = mode
        self.mode = mode
        self._context = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for value, name in ((0, '自动'), (16, '并排'), (1, '上下'), (GRID_LAYOUT, '均分'),
                            (MAIN_LAYOUT, '一主多辅'), (FOCUS_LAYOUT, '六格组合'),
                            (2, '两列'), (3, '三列'), (FREE_LAYOUT, '自定义')):
            button = QToolButton(self)
            button.setText(name)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setObjectName('LayoutCard')
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setIconSize(QSize(40, 26))
            row.addWidget(button)
            self.group.addButton(button)
            button.clicked.connect(lambda _checked=False, mode=value: self.select(mode))
            self.buttons[value] = button
        theme.signals().changed.connect(self._refresh_icons)

    def select(self, mode):
        if mode != self._preference:
            self._preference = mode
            self.changed.emit()

    def update_context(self, count):
        context = (count, self._preference)
        if context == self._context:
            return self.mode
        self._context = context
        modes = [0, 16, 1, FREE_LAYOUT] if count == 2 else (
            [0, GRID_LAYOUT, MAIN_LAYOUT, FREE_LAYOUT] if count >= 3 else [])
        if count == 6:
            modes.append(FOCUS_LAYOUT)
        if self._preference in (16, 1, 2, 3) and count > 1 and self._preference not in modes:
            modes.append(self._preference)
        self.mode = self._preference if self._preference in modes else 0
        for value, button in self.buttons.items():
            button.setVisible(value in modes)
            button.setChecked(value == self.mode)
        self.setVisible(bool(modes))
        self._refresh_icons()
        return self.mode

    def _refresh_icons(self, *_args):
        if self._context is None:
            return
        count = max(1, min(16, self._context[0]))
        scale = self.devicePixelRatioF()
        for value, button in self.buttons.items():
            if button.isHidden():
                continue
            canvas = QPixmap(round(40 * scale), round(26 * scale))
            canvas.setDevicePixelRatio(scale)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.Antialiasing)
            if value == FREE_LAYOUT:
                rectangles = [QRect(1, 8, 24, 15), QRect(25, 3, 13, 20)]
            else:
                rectangles = pane_rectangles(6 if value == FOCUS_LAYOUT else count, QRect(1, 1, 38, 24), value)
            for index, rect in enumerate(rectangles):
                color = theme.ACCENT if index == 0 and value in (MAIN_LAYOUT, FOCUS_LAYOUT) else theme.TEXT2
                painter.setPen(QPen(theme.qcolor(color), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(continuous_path(QRectF(rect).adjusted(.75, .75, -.75, -.75), 2))
            painter.end()
            button.setIcon(QIcon(canvas))
