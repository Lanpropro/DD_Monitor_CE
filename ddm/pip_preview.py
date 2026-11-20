"""Picture-in-picture layout selection preview."""
from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from .pip_composition import FREE_LAYOUT
from .pip_placement import fit_placement, snap_position
from .ui import ElidedLabel
from .pip_geometry import composition_ratio, pane_rectangles


class CompositionPreview(QFrame):
    positionsSwapped = Signal(int, int)
    positionChanged = Signal(int, tuple)
    SNAP_DISTANCE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(156)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9
        self.aspects = []
        self.primary = 0
        self.placement = ()
        self._scale = 1
        self._drag = None
        self._ghost = None
        self._drop_target = None
        self.setAccessibleName('拖动画面并吸附到目标位置')

    def set_panes(self, names, columns, aspects=None, primary=0, *, placement=()):
        self.cancel_drag()
        for label in self.labels:
            label.hide()
            label.deleteLater()
        self.labels = [ElidedLabel(name, self) for name in names]
        self.columns = columns
        self.primary = primary
        self.placement = placement
        self.aspects = aspects or [16 / 9] * len(names)
        self.aspect = composition_ratio(self.aspects, columns, primary, placement=placement) if names else 16 / 9
        for label in self.labels:
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName('PluginCard')
            label.setTextFormat(Qt.PlainText)
            label.setCursor(Qt.OpenHandCursor if len(names) > 1 else Qt.ArrowCursor)
            guide = '拖动以自由摆放和对齐' if placement else '靠近其他画面可吸附换位'
            label.setToolTip(label.text() + '\n' + guide if len(names) > 1 else label.text())
            label.installEventFilter(self)
            label.show()
        self._arrange()

    def _arrange(self):
        area = self.rect().adjusted(8, 8, -8, -8)
        if self.columns == FREE_LAYOUT and self.placement:
            rects, self._scale = fit_placement(self.placement, area.adjusted(22, 17, -22, -17))
        else:
            rects = pane_rectangles(len(self.labels), area, self.columns, self.aspects, self.primary)
        for label, rect in zip(self.labels, rects):
            label.setGeometry(rect)

    def resizeEvent(self, event):
        self.cancel_drag()
        super().resizeEvent(event)
        self._arrange()

    def _highlight(self, target):
        if target is self._drop_target:
            return
        previous, self._drop_target = self._drop_target, target
        for label in (previous, target):
            if label is not None:
                label.setProperty('pipDropTarget', label is target)
                label.style().unpolish(label)
                label.style().polish(label)
                label.update()

    def _snap_target(self, point, source):
        hits = [index for index, label in enumerate(self.labels) if label.geometry().contains(point)]
        if hits:
            target = hits[0]
            return target if target != source else None
        candidates = []
        for index, label in enumerate(self.labels):
            if index == source:
                continue
            bounds = label.geometry()
            x = max(bounds.left() - point.x(), point.x() - bounds.right(), 0)
            y = max(bounds.top() - point.y(), point.y() - bounds.bottom(), 0)
            distance = x * x + y * y
            if distance <= self.SNAP_DISTANCE ** 2:
                candidates.append((distance, index))
        return min(candidates)[1] if candidates else None

    def _free_position(self, source, pressed, position):
        if not self.rect().contains(self.mapFromGlobal(position)):
            return None
        delta = position - pressed
        original = QRect(*self.placement[source])
        moved = original.translated(round(delta.x() / self._scale), round(delta.y() / self._scale))
        neighbors = [QRect(*rect) for index, rect in enumerate(self.placement) if index != source]
        return snap_position(moved, neighbors, round(self.SNAP_DISTANCE / self._scale))

    def cancel_drag(self):
        self._drag = None
        QApplication.instance().removeEventFilter(self)
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        if self._ghost is not None:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None
        self._highlight(None)

    def eventFilter(self, watched, event):
        kind = event.type()
        if self._drag is None:
            if (len(self.labels) > 1 and watched in self.labels
                    and kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton):
                position = event.globalPosition().toPoint()
                self._drag = (self.labels.index(watched), position, watched.mapFromGlobal(position))
                self.grabMouse(Qt.ClosedHandCursor)
                QApplication.instance().installEventFilter(self)
                return True
            return False
        if kind == QEvent.MouseMove:
            if not event.buttons() & Qt.LeftButton:
                self.cancel_drag()
                return True
            source, pressed, offset = self._drag
            position = event.globalPosition().toPoint()
            if self._ghost is None and (position - pressed).manhattanLength() >= QApplication.startDragDistance():
                self._ghost = QLabel(self)
                self._ghost.setObjectName('PluginCard')
                self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._ghost.setPixmap(self.labels[source].grab())
                self._ghost.setScaledContents(True)
                if self.placement:
                    self._ghost.setContentsMargins(2, 2, 2, 2)
                self._ghost.show()
            if self._ghost is not None:
                point = self.mapFromGlobal(position)
                if self.placement:
                    placed = self._free_position(source, pressed, position)
                    if placed is None:
                        ghost = QRect(point - offset, self.labels[source].size())
                    else:
                        x, y, _width, _height = self.placement[source]
                        ghost = self.labels[source].geometry().translated(
                            round((placed.x() - x) * self._scale), round((placed.y() - y) * self._scale))
                    self._ghost.setGeometry(ghost)
                    self._ghost.raise_()
                    self._highlight(self._ghost if placed is not None else None)
                    return True
                target = self._snap_target(point, source)
                label = self.labels[target] if target is not None else None
                if label is not None:
                    self._ghost.setGeometry(label.geometry().adjusted(2, 2, -2, -2))
                else:
                    self._ghost.setGeometry(QRect(point - offset, self.labels[source].size()))
                self._ghost.raise_()
                self._highlight(label)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            source, pressed, _offset = self._drag
            position = event.globalPosition().toPoint()
            if self.placement:
                placed = self._free_position(source, pressed, position) if self._ghost is not None else None
                self.cancel_drag()
                if placed is not None and placed.getRect() != self.placement[source]:
                    self.positionChanged.emit(source, placed.getRect())
                return True
            point = self.mapFromGlobal(position)
            target = self._snap_target(point, source)
            moved = self._ghost is not None
            self.cancel_drag()
            if moved and target is not None and target != source:
                self.positionsSwapped.emit(source, target)
            return True
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel_drag()
            return True
        if (kind == QEvent.ApplicationDeactivate or
                watched is self and kind in (QEvent.Hide, QEvent.UngrabMouse) or
                watched is self.window() and kind in (QEvent.Hide, QEvent.WindowDeactivate)):
            self.cancel_drag()
        return False
