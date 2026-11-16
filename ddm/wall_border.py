"""Pane-border widgets and one wall's hover/drag session; layout models stay with the wall."""
import sys

from PySide6.QtCore import QObject, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from . import resize_layout
from .badge_surface import BadgeSurface
from .corner_geometry import continuous_path


class WallPaneBorder(BadgeSurface):
    """A masked native border keeps resize hits above VLC without covering its centre."""

    BAND = 3
    CORNER = 18
    RADIUS = 10

    def __init__(self, pane, wall):
        super().__init__(pane)
        self.wall = wall
        self.targets = {}
        self.hover_edges = {}
        self.highlights = []
        self._outline_path = QPainterPath()
        self._mask_path = QPainterPath()
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setToolTip("拖动边框调整大小；拖动角落等比例缩放；双击恢复相邻区域比例")
        self.hide()

    def sync(self, targets):
        self.targets = targets
        if not self.underMouse():
            self.hover_edges = {}
        self.setGeometry(self.parentWidget().rect())
        region = QRegion()
        for edge in targets:
            region |= QRegion(self._edge_rect(edge))
        outer, inner = QPainterPath(), QPainterPath()
        outer.addPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.RADIUS - .5))
        inner.addPath(continuous_path(QRectF(self.rect()).adjusted(
            self.BAND + .5, self.BAND + .5, -self.BAND - .5, -self.BAND - .5), self.RADIUS - self.BAND - .5))
        self._outline_path = outer.subtracted(inner)
        # 原生遮罩只负责命中；向外留出抗锯齿像素，由逐像素透明绘制轮廓。
        stroker = QPainterPathStroker()
        stroker.setWidth(2)
        outline = QRegion(self._outline_path.united(stroker.createStroke(
            self._outline_path)).toFillPolygon().toPolygon())
        region &= outline
        if region.isEmpty():
            self.hide()
            return
        self.setMask(region)
        self.show()
        self.raise_()

    def _edge_rect(self, edge):
        width, height = self.width(), self.height()
        return {"left": QRect(0, 0, self.RADIUS, height),
                "right": QRect(width - self.RADIUS, 0, self.RADIUS, height),
                "top": QRect(0, 0, width, self.RADIUS),
                "bottom": QRect(0, height - self.RADIUS, width, self.RADIUS)}[edge]

    def edges_at(self, point):
        horizontal = "left" if point.x() < self.CORNER else (
            "right" if point.x() >= self.width() - self.CORNER else None)
        vertical = "top" if point.y() < self.CORNER else (
            "bottom" if point.y() >= self.height() - self.CORNER else None)
        return {edge: self.targets[edge] for edge in (horizontal, vertical) if edge in self.targets}

    def set_highlights(self, rectangles):
        if self.highlights != rectangles:
            self.highlights = rectangles
            self.update()

    def mouseMoveEvent(self, event):
        if self.wall._border_drag is not None and self.wall._border_drag["border"] is self:
            self.wall._move_border_drag(event.globalPosition().toPoint())
        else:
            self.hover_edges = self.edges_at(event.position().toPoint())
            self.wall._set_hover_border(self, self.hover_edges)
            horizontal = next((edge for edge in self.hover_edges if edge in ("left", "right")), None)
            vertical = next((edge for edge in self.hover_edges if edge in ("top", "bottom")), None)
            if horizontal and vertical:
                cursor = Qt.SizeFDiagCursor if (horizontal == "left") == (vertical == "top") else Qt.SizeBDiagCursor
            else:
                cursor = Qt.SizeHorCursor if horizontal else Qt.SizeVerCursor
            self.setCursor(cursor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edges = self.edges_at(event.position().toPoint())
            self.wall._begin_border_drag(self, edges, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.wall._finish_border_drag(self, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.wall._reset_border(self, self.edges_at(event.position().toPoint()))
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self.hover_edges = {}
        self.wall._set_hover_border()
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.wall._cancel_border_drag()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self._schedule_layered_paint()
        else:
            painter = QPainter(self)
            self._render_badge(painter)

    def refresh_theme(self):
        self.update()

    def _layered_render_key(self):
        return tuple(rect.getRect() for rect in self.highlights)

    def _render_badge(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        # Windows 透明像素会穿透鼠标；极低 alpha 保留未高亮边缘的拖动命中。
        painter.fillPath(self._outline_path, QColor(56, 189, 248, 1))
        selected = QRegion()
        for rect in self.highlights:
            selected |= QRegion(rect)
        painter.setClipRegion(selected)
        painter.fillPath(self._outline_path, QColor('#38bdf8'))


class WallResizePreview(QWidget):
    """Masked native guides stay above VLC while the video windows remain still."""

    LINE = 2
    DASH = 6
    GAP = 5
    COLOR = QColor("#b7c1c4")

    def __init__(self, wall):
        super().__init__(wall)
        self.rectangles = {}
        self.guides = {}
        self._outline = QRegion()
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def show_guides(self, rectangles, dividers, originals):
        self.rectangles = {cell: QRect(rect) for cell, rect in rectangles.items()}
        self.guides = {}
        self.setGeometry(self.parentWidget().rect())
        outline = QRegion()
        for key, rect in dividers.items():
            previous = originals.get(key)
            vertical = rect.width() < rect.height()
            if previous is None or (rect.left() if vertical else rect.top()) == (
                    previous.left() if vertical else previous.top()):
                continue
            self.guides[key] = QRect(rect)
            length = rect.height() if vertical else rect.width()
            for offset in range(0, length, self.DASH + self.GAP):
                dash = min(self.DASH, length - offset)
                x = rect.center().x() - self.LINE // 2 if vertical else rect.left() + offset
                y = rect.top() + offset if vertical else rect.center().y() - self.LINE // 2
                outline |= QRegion(QRect(x, y,
                                         self.LINE if vertical else dash,
                                         dash if vertical else self.LINE))
        previous_outline, self._outline = self._outline, outline
        if outline.isEmpty():
            self.hide()
        else:
            self.setMask(outline)
            self.show()
            self.raise_()
            self.update()
        self.parentWidget()._repaint_preview_damage(previous_outline.subtracted(outline))

    def clear(self):
        self.hide()
        previous_outline, self._outline = self._outline, QRegion()
        self.rectangles = {}
        self.guides = {}
        self.parentWidget()._repaint_preview_damage(previous_outline)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setClipRegion(self._outline)
        painter.fillRect(event.rect(), self.COLOR)


class WallBorderInteraction(QObject):
    """Own one hover/drag session, coalescing timer and preview for a wall."""

    def __init__(self, wall):
        super().__init__(wall)
        self.wall = wall
        self.hover_border = None
        self.hover_edges = {}
        self.drag = None
        self.pending = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(32)
        self.timer.timeout.connect(self.flush)
        self.preview = WallResizePreview(wall)

    def set_hover(self, border=None, edges=None):
        if (self.drag is not None or border is None or
                border not in self.wall._pane_borders.values() or not border.isVisible()):
            border, edges = None, {}
        else:
            edges = {edge: key for edge, key in (edges or {}).items()
                     if border.targets.get(edge) == key and key in self.wall._divider_rects}
        self.hover_border, self.hover_edges = border, edges
        # A corner names the pane as a whole; an edge names only that side.
        displayed = border.targets if border is not None and len(edges) > 1 else edges
        for candidate in self.wall._pane_borders.values():
            candidate.set_highlights([candidate._edge_rect(edge) for edge in displayed]
                                     if candidate is border else [])

    def begin(self, border, edges, position):
        if not edges or self.wall.fullscreen_tile is not None:
            return
        self.cancel()
        tree, weights, widgets, minimum, defaults = self.wall._border_model()
        cell = next(cell for cell, pane in widgets.items() if pane is border.parentWidget())
        minimums = {index: minimum(index) for index in widgets}
        geometry_weights = {key: list(values) for key, values in weights.items()}
        if self.wall.layout_id == "corner" and any(key[0] == "root/1" for key in edges.values()):
            # Match cumulative corner rounding so the untouched bottom boundary stays fixed.
            widths = [pane.width() for pane in self.wall.tiles[3:6]]
            geometry_weights["root/1"] = [width / sum(widths) for width in widths]
        self.drag = dict(border=border, edges=edges, origin=position,
                                 rect=QRect(border.parentWidget().geometry()), cell=cell,
                                 tree=tree, weights={key: list(values) for key, values in weights.items()},
                                 geometry_weights=geometry_weights,
                                 dividers={key: QRect(rect) for key, rect in self.wall._divider_rects.items()},
                                 minimum=minimums.__getitem__, defaults=defaults, area=self.wall._corner_area(),
                                 before=self.wall.corner_ratios() if self.wall.layout_id == "corner" else self.wall.layout_ratios(),
                                 preview_weights=None)
        border.setFocus(Qt.MouseFocusReason)
        self.set_hover()
        border.update()

    def move(self, position):
        if self.drag is None:
            return
        self.pending = position
        if not self.timer.isActive():
            self.timer.start()

    def flush(self):
        position, self.pending = self.pending, None
        state = self.drag
        if state is None or position is None or self.wall.fullscreen_tile is not None:
            return
        if position == state["origin"]:
            state["preview_weights"] = None
            self.preview.clear()
            return
        weights = resize_layout.resize_borders(
            state["tree"], state["area"], self.wall.grid.spacing(), state["minimum"],
            state["geometry_weights"], state["defaults"], state["cell"], state["edges"],
            state["rect"], position - state["origin"])
        state["preview_weights"] = weights
        if self.wall.layout_id == "corner":
            rectangles, dividers = self.wall._corner_rectangles(weights, state["area"])
        else:
            rectangles, divider_items = resize_layout.geometry(
                state["tree"], state["area"], self.wall.grid.spacing(), state["minimum"],
                weights, state["defaults"])
            dividers = {(node.key, index): rect
                        for node, index, rect, _area, _sizes in divider_items}
        self.preview.show_guides(rectangles, dividers, state["dividers"])

    def finish(self, border, position):
        state = self.drag
        if state is None or state["border"] is not border:
            return
        self.pending = position
        self.timer.stop()
        self.flush()
        before = state["before"]
        self.drag = None
        self.preview.clear()
        border.update()
        if state["preview_weights"] is not None:
            self.wall._apply_border_weights(state["preview_weights"])
        if self.wall.layout_id == "corner":
            if before != self.wall.corner_ratios():
                self.wall.cornerRatiosChanged.emit()
        elif before != self.wall.layout_ratios():
            self.wall.layoutRatiosChanged.emit()

    def cancel(self):
        self.timer.stop()
        self.pending = None
        self.preview.clear()
        state, self.drag = self.drag, None
        if state is not None:
            border = state["border"]
            if QWidget.mouseGrabber() is border:
                border.releaseMouse()
            border.update()
        self.set_hover()
