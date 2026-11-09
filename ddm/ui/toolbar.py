"""Shared toolbar icon button without aggregate-widget or player imports."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton

from ..corner_geometry import continuous_path
from ..playback_controls import _icon_color


class BarIconButton(QPushButton):
    """竖屏横栏里的小图标按钮：横屏是文字按钮，竖屏自己画图标。

    为什么不用字形：雅黑下 `↑↓` 的墨迹明显偏左（实测图标框中心比按钮中心
    左 5px），`✓` 又偏小；自己画两个箭头 / 一个勾，位置和粗细都可控，
    也和 `RefreshButton` 那个手绘圆环是一个路子。
    """

    KINDS = ("check", "sort")

    def __init__(self, text: str, kind: str, parent=None):
        super().__init__(text, parent)
        assert kind in self.KINDS, kind
        self._plain_text = text
        self._kind = kind
        self._icon_mode = False

    def set_icon_mode(self, on: bool) -> None:
        self._icon_mode = bool(on)
        self.setText("" if self._icon_mode else self._plain_text)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._icon_mode:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = _icon_color(self)
        center = self.rect().center()
        if self._kind == "check":
            pen = QPen(color, 1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(continuous_path(QRectF(center.x() - 6, center.y() - 3, 10, 10), 2))
            painter.drawLine(QPointF(center.x() - 2, center.y() - 6),
                             QPointF(center.x() + 7, center.y() - 6))
            painter.drawLine(QPointF(center.x() + 7, center.y() - 6),
                             QPointF(center.x() + 7, center.y() + 3))
            path = QPainterPath()
            path.moveTo(center.x() - 4.0, center.y() + 1.5)
            path.lineTo(center.x() - 2.2, center.y() + 3.4)
            path.lineTo(center.x() + 2.2, center.y() - 0.5)
            painter.drawPath(path)
        else:
            # 上箭头 + 下箭头 = 「排序」。两根杆子要拉开、箭头别画太宽，
            # 否则两个箭头的三角会和旁边那根杆子叠在一起（用户报过重叠）。
            pen = QPen(color, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for offset, up in ((-4.0, True), (4.0, False)):
                x = center.x() + offset
                top = center.y() - 5.5
                bottom = center.y() + 5.5
                painter.drawLine(QPointF(x, top), QPointF(x, bottom))
                tip = top if up else bottom
                base = top + 3.4 if up else bottom - 3.4
                painter.drawLine(QPointF(x, tip), QPointF(x - 2.2, base))
                painter.drawLine(QPointF(x, tip), QPointF(x + 2.2, base))
