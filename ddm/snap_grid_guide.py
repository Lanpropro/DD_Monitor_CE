"""Input-transparent drag guides drawn over the native video surfaces."""
from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .sidebar_navigation import NavigationButton


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
        self.swap_markers = tuple(NavigationButton('交换画面', 'replace', self) for _ in range(2))
        for marker in self.swap_markers:
            marker.setFixedSize(24, 24)
            marker.setCheckable(True)
            marker.setChecked(True)
            marker.setFocusPolicy(Qt.NoFocus)
            marker.setAttribute(Qt.WA_TransparentForMouseEvents)
            marker.setToolTip('')
            marker.hide()

    def present(self, units, target, *, swap_source=None):
        bounds = QRect(self.wall.mapToGlobal(QPoint()), self.wall.size())
        if self.geometry() != bounds:
            self.setGeometry(bounds)
        if (units, target, swap_source) != (self.units, self.target, self.swap_source):
            self.units, self.target, self.swap_source = units, target, swap_source
            for marker, rect in zip(self.swap_markers, (swap_source, target if swap_source is not None else None)):
                if rect is not None:
                    marker.move(rect.center() - marker.rect().center())
                marker.setVisible(rect is not None)
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
