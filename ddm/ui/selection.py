"""Shared painted selection controls; Qt owns input, focus and checked state."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QCheckBox, QHBoxLayout, QSizePolicy, QWidget

from .. import theme


class ToggleSwitch(QCheckBox):
    def __init__(self, label='', parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        self.setFixedSize(theme.SWITCH_WIDTH, theme.SWITCH_HEIGHT)
        self.setAccessibleName(label)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        theme.signals().changed.connect(self.update)

    def hitButton(self, position):
        return self.rect().contains(position)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.75, .75, -.75, -.75),
                                    self.height() / 2, self.height() / 2)
        track = QRectF(1, (self.height() - theme.SWITCH_TRACK_HEIGHT) / 2,
                       self.width() - 2, theme.SWITCH_TRACK_HEIGHT)
        color = theme.qcolor(theme.ACCENT if self.isChecked() else theme.CONTENT_HOVER)
        if self.isEnabled() and self.underMouse():
            color = color.darker(110) if self.isDown() else color.lighter(110)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if self.isChecked() else theme.BORDER_STRONG), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        inset = (track.height() - theme.SWITCH_THUMB_SIZE) / 2
        left = track.right() - inset - theme.SWITCH_THUMB_SIZE if self.isChecked() else track.left() + inset
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor('#ffffff' if self.isChecked() else theme.TEXT2))
        painter.drawEllipse(QRectF(left, track.top() + inset, theme.SWITCH_THUMB_SIZE, theme.SWITCH_THUMB_SIZE))


class _SegmentButton(QAbstractButton):
    def __init__(self, text, parent):
        super().__init__(parent)
        self.setText(text)
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setProperty('customControlSurface', True)
        theme.signals().changed.connect(self.update)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2 * theme.SEGMENT_ITEM_PADDING,
                     theme.CONTROL_HEIGHT - 2 * theme.SEGMENT_PADDING)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -2)
        if self.isChecked() or self.underMouse() or self.isDown():
            painter.setPen(Qt.NoPen)
            if self.isChecked():
                for offset, alpha in ((2, 12), (1, 26)):
                    painter.setBrush(QColor(0, 0, 0, alpha))
                    painter.drawRoundedRect(rect.translated(0, offset), rect.height() / 2, rect.height() / 2)
                color = theme.qcolor(theme.mix(theme.CONTENT, theme.ACCENT, .20))
                if self.isDown():
                    color = color.darker(110)
                fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                fill.setColorAt(0, color.lighter(108))
                fill.setColorAt(1, color.darker(108))
                painter.setBrush(fill)
            else:
                painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
            if self.isChecked():
                edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                edge.setColorAt(0, QColor(255, 255, 255, 28))
                edge.setColorAt(.5, QColor(255, 255, 255, 0))
                edge.setColorAt(1, QColor(0, 0, 0, 20))
                painter.setPen(QPen(edge, 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setPen(theme.qcolor(theme.ACCENT if self.isChecked() else theme.TEXT2))
        painter.drawText(rect, Qt.AlignCenter, self.fontMetrics().elidedText(
            self.text(), Qt.ElideRight, max(0, self.width() - 2 * theme.SEGMENT_ITEM_PADDING)))


class SegmentedControl(QWidget):
    valueChanged = Signal(str)

    def __init__(self, options, value=None, parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        self.setFixedHeight(theme.CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        box = QHBoxLayout(self)
        box.setContentsMargins(*([theme.SEGMENT_PADDING] * 4))
        box.setSpacing(theme.SEGMENT_GAP)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, label in options:
            button = _SegmentButton(label, self)
            self.buttons[key] = button
            self.group.addButton(button)
            box.addWidget(button, 1)
        self.setValue(value if value is not None else next(iter(self.buttons)))
        self.group.buttonToggled.connect(self._selection_changed)
        theme.signals().changed.connect(self.update)

    def sizeHint(self):
        width = max(button.sizeHint().width() for button in self.buttons.values()) * len(self.buttons)
        return QSize(width + 2 * theme.SEGMENT_PADDING + (len(self.buttons) - 1) * theme.SEGMENT_GAP,
                     theme.CONTROL_HEIGHT)

    def minimumSizeHint(self):
        return QSize(min(180, self.sizeHint().width()), theme.CONTROL_HEIGHT)

    def _selection_changed(self, button, checked):
        if checked:
            self.valueChanged.emit(self.value())

    def value(self):
        return next(key for key, button in self.buttons.items() if button.isChecked())

    def setValue(self, value):
        self.buttons[value].setChecked(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, theme.qcolor(theme.BG).darker(112))
        fill.setColorAt(1, theme.qcolor(theme.BG))
        edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        edge.setColorAt(0, QColor(0, 0, 0, 45))
        edge.setColorAt(1, theme.qcolor(theme.BORDER))
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
