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
        self.swap_source = None

    def present(self, units, target, *, swap_source=None):
        bounds = QRect(self.wall.mapToGlobal(QPoint()), self.wall.size())
        if self.geometry() != bounds:
            self.setGeometry(bounds)
        if (units, target, swap_source) != (self.units, self.target, self.swap_source):
            self.units, self.target, self.swap_source = units, target, swap_source
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
            accent = theme.qcolor(theme.ACCENT)
            painter.setPen(QPen(accent, 2))
            fill = QColor(accent)
            fill.setAlpha(56)
            painter.setBrush(fill)
            for rect in (self.target, self.swap_source):
                if rect is not None:
                    painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), 8, 8)
            if self.swap_source is not None:
                font = painter.font()
                font.setPixelSize(19)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(accent)
                painter.setBrush(theme.qcolor(theme.BG))
                for rect in (self.target, self.swap_source):
                    badge = QRectF(0, 0, 32, 28)
                    badge.moveCenter(QRectF(rect).center())
                    painter.drawRoundedRect(badge, 7, 7)
                    painter.drawText(badge, Qt.AlignCenter, '↔')
