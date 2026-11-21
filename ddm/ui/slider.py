"""Consistent settings slider length and readable numeric readouts."""
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider, QStyle, QStyleOptionSlider

from .. import theme


class SettingsSlider(QSlider):
    def __init__(self, parent=None, *, fixed_width=True):
        super().__init__(Qt.Horizontal, parent)
        self.setProperty('settingsSlider', True)
        self.setProperty('customControlSurface', True)
        self.setCursor(Qt.PointingHandCursor)
        if fixed_width:
            self.setFixedWidth(theme.SETTINGS_SLIDER_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed if fixed_width else QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(19)
        self.sliderPressed.connect(self.update)
        self.sliderReleased.connect(self.update)
        theme.signals().changed.connect(self.update)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        center = QRectF(handle).center()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(1. if self.isEnabled() else .5)
        hover = self.underMouse() and self.isEnabled()
        track = QRectF(0, center.y() - 2, self.width(), 4)
        groove = QPainterPath()
        groove.addRoundedRect(track, 2, 2)
        painter.fillPath(groove, theme.qcolor(theme.BORDER_STRONG) if hover else QColor(131, 131, 145, 77))
        painter.save()
        painter.setClipPath(groove)
        if option.upsideDown:
            track.setLeft(center.x())
        else:
            track.setRight(center.x())
        accent = theme.mix(theme.ACCENT, '#ffffff', .35) if hover else theme.ACCENT
        painter.fillRect(track, theme.qcolor(accent))
        painter.restore()
        radius = 8.5 if self.isSliderDown() else 7.
        painter.setPen(QPen(QColor(105, 116, 130, 128), 1))
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(center, radius, radius)


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
