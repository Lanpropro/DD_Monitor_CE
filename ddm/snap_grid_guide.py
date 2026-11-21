"""Input-transparent drag guides drawn over the native video surfaces."""
from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class SnapGridGuide(QWidget):
    def __init__(self, wall):
        super().__init__(wall.window(), Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.wall = wall
        self.units = ()
        self.target = None

    def present(self, units, target):
        bounds = QRect(self.wall.mapToGlobal(QPoint()), self.wall.size())
        if self.geometry() != bounds:
            self.setGeometry(bounds)
        if (units, target) != (self.units, self.target):
            self.units, self.target = units, target
            self.update()
        if not self.isVisible():
            self.show()

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            for color, width in ((QColor(0, 0, 0, 150), 3), (QColor(238, 245, 255, 220), 1)):
                pen = QPen(color, width)
                pen.setDashPattern([6 / width, 4 / width])
                painter.setPen(pen)
                for rect in self.units:
                    painter.drawRect(QRectF(rect).adjusted(2, 2, -2, -2))
            if self.target is not None:
                accent = theme.qcolor(theme.ACCENT)
                painter.setPen(QPen(accent, 2))
                accent.setAlpha(56)
                painter.setBrush(accent)
                painter.drawRoundedRect(QRectF(self.target).adjusted(1, 1, -1, -1), 8, 8)
