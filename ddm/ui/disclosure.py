"""Inline disclosure with one painted surface in every input state."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from .. import theme


class DisclosureButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setStyleSheet(f'min-height: {theme.CONTROL_HEIGHT}px; max-height: {theme.CONTROL_HEIGHT}px; '
                          'padding: 0px; border: none; background: transparent;')
        self.setFixedHeight(theme.CONTROL_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        theme.signals().changed.connect(self.update)

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
            painter.setOpacity(.45)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self.isChecked() or self.hasFocus()
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if active else theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor(theme.ACCENT_SOFT if self.isChecked() else
                                     theme.CONTENT_HOVER if self.underMouse() else theme.CONTENT))
        painter.drawRoundedRect(rect, theme.RADIUS_MD, theme.RADIUS_MD)
        painter.setPen(theme.qcolor(theme.ACCENT if self.isChecked() else theme.TEXT2))
        painter.drawText(rect.adjusted(12, 0, -36, 0), Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self.text(), Qt.ElideRight, max(0, self.width() - 50)))
        x, y = self.width() - 18, self.height() / 2
        arrow = QPainterPath()
        arrow.moveTo(x - 4, y + (2 if self.isChecked() else -2))
        arrow.lineTo(x, y + (-2 if self.isChecked() else 2))
        arrow.lineTo(x + 4, y + (2 if self.isChecked() else -2))
        painter.setPen(QPen(theme.qcolor(theme.TEXT2), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(arrow)
