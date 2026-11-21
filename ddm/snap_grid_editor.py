"""Grid-aligned video shapes in the existing wall editor."""
from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from . import layouts, snap_grid, theme
from .corner_geometry import continuous_path
from .layout_preset_editor import LayoutDraftPreview


class SnapGridPreview(LayoutDraftPreview):
    def __init__(self, wall, base, ratios, parent):
        self.count = layouts.snap_grid_size(base)
        defaults = layouts.even_cells(self.count, self.count)
        super().__init__(wall, base, ratios.get('grid', defaults), defaults, parent)
        bindings = wall.pane_danmaku.settings.get(base, {})
        self.protected = {index for index, tile in enumerate(wall.tiles) if tile.room.get('room_id')} | set(bindings)
        self.setAccessibleName('拖动画面移动，拖动右下角调整占格，松开后吸附到网格')
        self.setToolTip(self.accessibleName())

    def ratios(self):
        return {'grid': self.draft} if self.draft != self.defaults else {}

    def _rectangles(self, cells):
        return snap_grid.geometry(self.count, cells, self.wall._corner_area(), self.wall.grid.spacing())

    @staticmethod
    def _grip(rect):
        return QRect(rect.right() - 17, rect.bottom() - 17, 12, 12)

    def _hit(self, point):
        for index, rect in self._rectangles(self.draft).items():
            if rect.contains(point):
                return index, self._grip(rect).adjusted(-5, -5, 5, 5).contains(point)
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rects = self._rectangles(self.draft)
        for index, rect in rects.items():
            frame = QRectF(rect).adjusted(1, 1, -1, -1)
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(QColor(13, 22, 34, 115))
            painter.drawPath(continuous_path(frame, 8))
            painter.setPen(QColor('#ffffff'))
            painter.drawText(frame, Qt.AlignCenter, str(index + 1))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(227, 237, 249, 122), 1, Qt.DashLine))
        for rect in self._rectangles(self.defaults).values():
            painter.drawRect(rect.adjusted(3, 3, -3, -3))
        painter.setBrush(QColor(235, 246, 255, 210))
        painter.setPen(Qt.NoPen)
        for rect in rects.values():
            painter.drawRoundedRect(self._grip(rect), 3, 3)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (hit := self._hit(event.position().toPoint())):
            self.drag = hit, event.position(), self.draft
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is None:
            hit = self._hit(event.position().toPoint())
            self.setCursor((Qt.SizeFDiagCursor if hit[1] else Qt.SizeAllCursor) if hit else Qt.ArrowCursor)
            return
        (index, resize), start, original = self.drag
        row, col, height, width = original[index]
        area = self.wall._corner_area()
        gap = self.wall.grid.spacing()
        delta = event.position() - start
        dx = round(delta.x() * self.count / max(1, area.width() + gap))
        dy = round(delta.y() * self.count / max(1, area.height() + gap))
        if resize:
            height = max(1, min(self.count - row, height + dy))
            width = max(1, min(self.count - col, width + dx))
        else:
            row = max(0, min(self.count - height, row + dy))
            col = max(0, min(self.count - width, col + dx))
        self.draft = snap_grid.place(self.count, original, index, (row, col, height, width), self.protected)
        self.update()

    def mouseReleaseEvent(self, event):
        if self.drag is not None and event.button() == Qt.LeftButton:
            previous = self.drag[2]
            self.mouseMoveEvent(event)
            self.drag = None
            self._remember(previous)
            event.accept()
            return
        super().mouseReleaseEvent(event)
