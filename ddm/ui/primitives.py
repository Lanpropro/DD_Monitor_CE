"""Shared labels and toolbar buttons; no player or aggregate-widget imports."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from ..corner_geometry import continuous_path
from ..playback_controls import _icon_color


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ElidedLabel(QLabel):
    """超出宽度自动省略的标签。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        super().setText(self._full_text)
        self._apply_elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def sizeHint(self) -> QSize:
        """用完整文本计算期望宽度，否则省略后的文本会让标签越缩越窄。"""
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._full_text) + 2, metrics.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.fontMetrics().height())

    def _apply_elide(self) -> None:
        if not self._full_text:
            return
        # 隐藏或还没排版时宽度是 0，省略后文本会变成空串（下一条状态读出来就是 ""），
        # 所以先保留原文，等真正有宽度再按实际宽度省略。
        if self.width() <= 0:
            if super().text() != self._full_text:
                super().setText(self._full_text)
            return
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(0, self.width()))
        # 宽度比省略号还窄时 Qt 也给空串：这时文本是被裁掉而不是没有，
        # 保留原文，别让状态读出来变成 ""。
        if not elided:
            elided = self._full_text
        if elided != super().text():
            super().setText(elided)


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
