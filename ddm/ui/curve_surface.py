"""Shared contrast and fine grid for editable settings graphs."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPen

from .. import theme
from ..corner_geometry import continuous_path
from ..settings_material import base_color


def paint_curve_surface(painter, widget, plot):
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.qcolor(base_color(widget, 'control', theme.CONTENT_HOVER)))
    painter.drawPath(continuous_path(QRectF(widget.rect()).adjusted(.5, .5, -.5, -.5), theme.RADIUS_LG))
    painter.fillRect(plot, theme.qcolor(base_color(widget, 'card', theme.CONTENT)))
    for index in range(11):
        color = theme.qcolor(theme.TEXT1)
        color.setAlpha(32 if index % 5 == 0 else 16)
        painter.setPen(QPen(color, 1))
        x = plot.left() + plot.width() * index / 10
        y = plot.top() + plot.height() * index / 10
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
    painter.restore()
