"""Dismissal, bounds and pointer gestures for the toolbar's PiP panel."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QWidget


def resize_edges(widget, point):
    edges = Qt.Edge(0)
    if point.x() < 8:
        edges |= Qt.LeftEdge
    elif point.x() >= widget.width() - 8:
        edges |= Qt.RightEdge
    if point.y() < 8:
        edges |= Qt.TopEdge
    elif point.y() >= widget.height() - 8:
        edges |= Qt.BottomEdge
    return edges


class ToolbarPipPanel(QObject):
    def __init__(self, dialog, anchor, *, below):
        super().__init__(dialog)
        self.dialog = dialog
        self.host = dialog.controller.host
        self.anchor = anchor
        self.below = below
        self.position = None
        self._gesture = None

    def attach(self):
        if not self._fit():
            return False
        self.dialog.setMouseTracking(True)
        QApplication.instance().installEventFilter(self)
        self.dialog.finished.connect(self._detach)
        return True

    def _detach(self, _result):
        QApplication.instance().removeEventFilter(self)
        self._end_gesture()

    def _available(self):
        area = QRect(self.host.mapToGlobal(QPoint()), self.host.size())
        screen = QApplication.screenAt(self.anchor.mapToGlobal(self.anchor.rect().center()))
        visible = area.intersected(screen.availableGeometry()) if screen is not None else area
        return visible if visible.isValid() else area

    def _fit(self):
        dialog = self.dialog
        available = self._available()
        area = available.adjusted(8, 8, -8, -8)
        dialog.layout().activate()
        minimum = dialog.minimumSizeHint()
        if not area.isValid() or minimum.boundedTo(area.size()) != minimum:
            dialog.reject()
            return False
        saved = dialog.controller.picker_size
        preferred = QSize(*saved) if saved else dialog.COMPACT_SIZE
        dialog.resize(preferred.boundedTo(area.size()))
        if self.position is None:
            rect = QRect(self.anchor.mapToGlobal(QPoint()), self.anchor.size())
            dialog.place_near(rect, available, below=self.below)
        else:
            dialog.move(dialog._clamp_position(self.host.mapToGlobal(self.position), area))
        return True

    def _belongs_to_panel(self, widget):
        if isinstance(widget, QWindow):
            handle = self.dialog.windowHandle()
            while widget is not None:
                if widget is handle:
                    return True
                widget = widget.transientParent()
            return False
        while isinstance(widget, QWidget):
            if widget is self.dialog:
                return True
            widget = widget.parentWidget()
        return False

    def _dismiss_if_inactive(self):
        if self.dialog.isVisible() and not (self.dialog.isActiveWindow()
                or self._belongs_to_panel(QApplication.activePopupWidget())):
            self.dialog.reject()

    def _set_resize_cursor(self, edges):
        if edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
            cursor = Qt.SizeFDiagCursor
        elif edges in (Qt.TopEdge | Qt.RightEdge, Qt.BottomEdge | Qt.LeftEdge):
            cursor = Qt.SizeBDiagCursor
        elif edges & (Qt.LeftEdge | Qt.RightEdge):
            cursor = Qt.SizeHorCursor
        elif edges:
            cursor = Qt.SizeVerCursor
        else:
            self.dialog.unsetCursor()
            return
        self.dialog.setCursor(cursor)

    def _begin_gesture(self, widget, edges, point):
        self._gesture = (widget, edges, point, self.dialog.geometry())
        widget.grabMouse()

    def _end_gesture(self):
        if self._gesture is None:
            return
        widget, edges, _pressed, original = self._gesture
        self._gesture = None
        if QWidget.mouseGrabber() is widget:
            widget.releaseMouse()
        if edges and self.dialog.size() != original.size():
            self.dialog.controller.remember_picker_size(self.dialog.size())
        self.dialog.unsetCursor()

    def _move_gesture(self, point):
        _widget, edges, pressed, original = self._gesture
        delta = point - pressed
        area = self._available().adjusted(8, 8, -8, -8)
        if not edges:
            position = self.dialog._clamp_position(original.topLeft() + delta, area)
            self.dialog.move(position)
        else:
            minimum = self.dialog.minimumSizeHint()
            result = QRect(original)
            if edges & Qt.LeftEdge:
                result.setLeft(max(area.left(), min(original.left() + delta.x(), original.right() - minimum.width() + 1)))
            elif edges & Qt.RightEdge:
                result.setRight(min(area.right(), max(original.right() + delta.x(), original.left() + minimum.width() - 1)))
            if edges & Qt.TopEdge:
                result.setTop(max(area.top(), min(original.top() + delta.y(), original.bottom() - minimum.height() + 1)))
            elif edges & Qt.BottomEdge:
                result.setBottom(min(area.bottom(), max(original.bottom() + delta.y(), original.top() + minimum.height() - 1)))
            self.dialog.setGeometry(result)
        self.position = self.host.mapFromGlobal(self.dialog.pos())

    def eventFilter(self, watched, event):
        dialog = self.dialog
        if not dialog.isVisible():
            return False
        kind = event.type()
        if watched is self.host:
            if kind in (QEvent.Move, QEvent.Resize):
                self._end_gesture()
                self._fit()
            elif kind == QEvent.Hide or (kind == QEvent.WindowStateChange and self.host.isMinimized()):
                dialog.reject()
        elif watched is dialog and kind == QEvent.WindowDeactivate:
            QTimer.singleShot(0, self, self._dismiss_if_inactive)
        if self._gesture is not None:
            if kind == QEvent.MouseMove and event.buttons() & Qt.LeftButton:
                self._move_gesture(event.globalPosition().toPoint())
                return True
            if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._end_gesture()
                return True
            if kind == QEvent.UngrabMouse and watched is self._gesture[0]:
                self._end_gesture()
        elif kind in (QEvent.MouseButtonPress, QEvent.NonClientAreaMouseButtonPress):
            if not self._belongs_to_panel(watched):
                dialog.reject()
                # The dismissing click should not also activate a control under the panel.
                return True
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                if watched is dialog.titlebar:
                    self._begin_gesture(watched, Qt.Edge(0), event.globalPosition().toPoint())
                    return True
                if watched is dialog and (edges := resize_edges(dialog, event.position().toPoint())):
                    self._begin_gesture(watched, edges, event.globalPosition().toPoint())
                    return True
        elif kind == QEvent.MouseMove and watched is dialog:
            self._set_resize_cursor(resize_edges(dialog, event.position().toPoint()))
        elif kind == QEvent.Leave and watched is dialog:
            dialog.unsetCursor()
        return False
