"""Interactive viewport-height / content-size curve for SC and video danmaku."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..corner_geometry import continuous_path
from ..viewport_scale import scale_curve_points, viewport_scale
from .basics import ActionButton
from .curve_surface import paint_curve_surface


class ScaleCurveGraph(QWidget):
    curveChanged = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = scale_curve_points()
        self.selected = None
        self._dragging = False
        self.setMinimumSize(220, 185)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName('缩放曲线：横轴画面高度，纵轴内容大小；拖动节点或线条调整')
        self.setToolTip('拖动节点调整；拖动线条新增节点；右键删除节点。720 px / 100% 基准点固定，端点可上下拖动。')

    def plot_rect(self):
        left = max(42, self.fontMetrics().horizontalAdvance('200%') + 8)
        right = max(24, self.fontMetrics().horizontalAdvance('1440') / 2 + 4)
        top = max(24, self.fontMetrics().height() + 4)
        bottom = max(34, self.fontMetrics().height() + 12)
        return QRectF(left, top, self.width() - left - right, self.height() - top - bottom)

    def point_position(self, point):
        rect = self.plot_rect()
        return QPointF(rect.left() + point[0]/2*rect.width(), rect.bottom() - point[1]/2*rect.height())

    def set_points(self, points=None, strength=35):
        values = scale_curve_points(points, strength)
        if self.points == values:
            return
        self.points = values
        self.selected = None
        self._dragging = False
        self.update()

    def _hit(self, position):
        return next((i for i, point in enumerate(self.points)
                     if (self.point_position(point)-position).manhattanLength() <= 12), None)

    def _values_at(self, position):
        rect = self.plot_rect()
        return [max(0, min(2, (position.x()-rect.left()) / rect.width()*2)),
                max(.1, min(2, (rect.bottom()-position.y()) / rect.height()*2))]

    def _changed(self):
        self.update()
        self.curveChanged.emit([list(point) for point in self.points])

    def _move_selected(self, position):
        index = self.selected
        if index is None or self.points[index] == [1, 1]:
            return
        x, y = self._values_at(position)
        if index in (0, len(self.points)-1):
            x = self.points[index][0]
        else:
            x = max(self.points[index-1][0]+.02, min(self.points[index+1][0]-.02, x))
        self.points[index] = [round(x, 4), round(y, 4)]
        self._changed()

    def mousePressEvent(self, event):
        index = self._hit(event.position())
        if event.button() == Qt.RightButton:
            if index is not None and index not in (0, len(self.points)-1) and self.points[index] != [1, 1]:
                self.points.pop(index)
                self.selected = None
                self._changed()
            return
        if event.button() != Qt.LeftButton:
            return
        self.setFocus(Qt.MouseFocusReason)
        if index is None and self.plot_rect().contains(event.position()):
            x, y = self._values_at(event.position())
            line_y = viewport_scale(720*x, points=self.points)
            if abs(y-line_y) * self.plot_rect().height()/2 <= 10:
                index = next((i for i, p in enumerate(self.points) if p[0] > x), None)
                if (index is not None and x-self.points[index-1][0] >= .02
                        and self.points[index][0]-x >= .02):
                    self.points.insert(index, [round(x, 4), round(line_y, 4)])
                    self._changed()
                else:
                    index = None
        self.selected = index
        self._dragging = index is not None
        self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._move_selected(event.position())
        else:
            self.setCursor(Qt.PointingHandCursor if self._hit(event.position()) is not None else Qt.CrossCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._dragging:
            self._move_selected(event.position())
            self._dragging = False

    def keyPressEvent(self, event):
        if self.selected is not None:
            index = self.selected
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                if index not in (0, len(self.points)-1) and self.points[index] != [1, 1]:
                    self.points.pop(index)
                    self.selected = None
                    self._changed()
                return
            delta = {Qt.Key_Left: (-2, 0), Qt.Key_Right: (2, 0),
                     Qt.Key_Up: (0, -2), Qt.Key_Down: (0, 2)}.get(event.key())
            if delta:
                self._move_selected(self.point_position(self.points[index])+QPointF(*delta))
                return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.plot_rect()
        paint_curve_surface(painter, self, rect)
        if not self.isEnabled():
            painter.setOpacity(.45)
        painter.setClipPath(continuous_path(QRectF(self.rect()), theme.RADIUS_LG))
        painter.setPen(theme.qcolor(theme.TEXT3))
        label_height = max(20, self.fontMetrics().height() + 2)
        for ratio in (0, 1, 2):
            y = rect.bottom()-rect.height()*ratio/2
            painter.drawText(QRectF(0, y-label_height/2, rect.left()-8, label_height),
                             Qt.AlignRight | Qt.AlignVCenter, f'{ratio*100}%')
        for x, text in ((0, '0'), (1, '720'), (2, '1440')):
            center = rect.left()+x/2*rect.width()
            width = max(50, self.fontMetrics().horizontalAdvance(text) + 4)
            painter.drawText(QRectF(center-width/2, rect.bottom()+5, width, label_height), Qt.AlignCenter, text)
        path = QPainterPath()
        path.moveTo(self.point_position(self.points[0]))
        for point in self.points[1:]:
            path.lineTo(self.point_position(point))
        painter.setPen(QPen(theme.qcolor(theme.ACCENT), 2.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        for i, point in enumerate(self.points):
            painter.setBrush(theme.qcolor(theme.ACCENT if i == self.selected else '#ffffff'))
            painter.setPen(QPen(theme.qcolor(theme.TEXT2 if point == [1, 1] else theme.ACCENT), 2))
            painter.drawEllipse(self.point_position(point), 5, 5)
        if self.selected is not None:
            x, y = self.points[self.selected]
            painter.setPen(theme.qcolor(theme.TEXT1))
            painter.drawText(QRectF(rect.left(), 1, rect.width(), label_height), Qt.AlignRight, f'{x*720:.0f} px · {y:.0%}')


class ScaleCurveControl(QWidget):
    curveChanged = Signal(list)

    def __init__(self, points=None, parent=None, *, strength=35):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.graph = ScaleCurveGraph(self)
        self.graph.set_points(points, strength)
        box.addWidget(self.graph)
        hint = QLabel('横轴为画面高度（px），纵轴为相对大小。拖动线条新增节点，右键删除；720 px / 100% 固定。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        box.addWidget(hint)
        row = QHBoxLayout()
        self.example = QLabel()
        self.example.setObjectName('SettingsHint')
        self.example.setWordWrap(True)
        row.addWidget(self.example, 1)
        self.reset_button = ActionButton('重置曲线')
        self.reset_button.clicked.connect(self.reset)
        row.addWidget(self.reset_button)
        box.addLayout(row)
        self.graph.curveChanged.connect(self._changed)
        self._update_example()

    def curve(self):
        return [list(point) for point in self.graph.points]

    def set_curve(self, points=None, strength=35):
        self.graph.set_points(points, strength)
        self._update_example()

    def reset(self):
        self.set_curve()
        self.curveChanged.emit(self.curve())

    def _update_example(self):
        self.example.setText('180 / 360 / 720 px：' + ' / '.join(
            f'{viewport_scale(height, points=self.graph.points):.0%}' for height in (180, 360, 720)))

    def _changed(self, points):
        self._update_example()
        self.curveChanged.emit(points)
