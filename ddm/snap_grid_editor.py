"""Grid-aligned video shapes in the existing wall editor."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from . import layouts, snap_grid, theme
from .corner_geometry import continuous_path
from .layout_preset_editor import LayoutDraftPreview


class SnapGridPreview(LayoutDraftPreview):
    def __init__(self, wall, base, ratios, parent):
        self.count = layouts.snap_grid_size(base)
        defaults = layouts.even_cells(self.count, self.count)
        bindings = wall.pane_danmaku.settings.get(base, {})
        count = self.count * self.count
        self.occupied = {index for index, tile in enumerate(wall.tiles[:count])
                         if tile.room.get('room_id')} | set(bindings)
        self.chat_cells = set(bindings)
        draft = snap_grid.with_occupied(ratios.get('grid', defaults), self.occupied)
        super().__init__(wall, base, draft, defaults, parent)
        self.setAccessibleName('拖动格子移动，按住 Ctrl 滚动鼠标滚轮调整直播格大小')
        self.setToolTip(self.accessibleName())

    def ratios(self):
        return {'grid': self.draft} if self.draft != self.defaults else {}

    def _rectangles(self, cells):
        return snap_grid.geometry(self.count, cells, self.wall._corner_area(), self.wall.grid.spacing())

    def _hit(self, point):
        for index, rect in self._rectangles(self.draft).items():
            if index in self.occupied and rect.contains(point):
                return index
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for index, rect in self._rectangles(self.draft).items():
            if index not in self.occupied:
                continue
            frame = QRectF(rect).adjusted(1, 1, -1, -1)
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(QColor(13, 22, 34, 115))
            painter.drawPath(continuous_path(frame, 8))
            painter.setPen(QColor('#ffffff'))
            painter.drawText(frame, Qt.AlignCenter, '弹幕' if index in self.chat_cells else str(index + 1))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(227, 237, 249, 122), 1, Qt.DashLine))
        for rect in self._rectangles(self.defaults).values():
            painter.drawRect(rect.adjusted(3, 3, -3, -3))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and (hit := self._hit(event.position().toPoint())) is not None:
            self.drag = hit, event.position(), self.draft
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag is None:
            hit = self._hit(event.position().toPoint())
            self.setCursor(Qt.SizeAllCursor if hit is not None else Qt.ArrowCursor)
            return
        index, start, original = self.drag
        row, col, height, width = original[index]
        area = self.wall._corner_area()
        gap = self.wall.grid.spacing()
        delta = event.position() - start
        dx = round(delta.x() * self.count / max(1, area.width() + gap))
        dy = round(delta.y() * self.count / max(1, area.height() + gap))
        row = max(0, min(self.count - height, row + dy))
        col = max(0, min(self.count - width, col + dx))
        self.draft = snap_grid.place(self.count, original, index, (row, col, height, width), self.occupied)
        self.update()

    def wheelEvent(self, event):
        index = self._hit(event.position().toPoint())
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if (self.drag is not None or event.modifiers() != Qt.ControlModifier or not delta
                or index is None or index in self.chat_cells):
            return super().wheelEvent(event)
        previous = self.draft
        target = snap_grid.resize(self.count, previous[index], 1 if delta > 0 else -1)
        self.draft = snap_grid.place(self.count, previous, index, target, self.occupied)
        self._remember(previous)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.drag is not None and event.button() == Qt.LeftButton:
            previous = self.drag[2]
            self.mouseMoveEvent(event)
            self.drag = None
            self._remember(previous)
            event.accept()
            return
        super().mouseReleaseEvent(event)
