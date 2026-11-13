"""Picture-in-picture layout selection preview."""
from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from .ui import ElidedLabel
from .pip_geometry import composition_ratio, pane_rectangles


class CompositionPreview(QFrame):
    positionsSwapped = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('PluginCard')
        self.setFixedHeight(156)
        self.labels = []
        self.columns = 0
        self.aspect = 16 / 9
        self.aspects = []
        self.primary = 0
        self.locked = set()
        self._drag = None
        self._ghost = None
        self._drop_target = None
        self.setAccessibleName('拖动预览画面交换位置')

    def set_panes(self, names, columns, aspects=None, primary=0, locked=()):
        self.cancel_drag()
        for label in self.labels:
            label.hide()
            label.deleteLater()
        self.labels = [ElidedLabel(name, self) for name in names]
        self.columns = columns
        self.primary = primary
        self.locked = set(locked)
        self.aspects = aspects or [16 / 9] * len(names)
        self.aspect = composition_ratio(self.aspects, columns, primary) if names else 16 / 9
        for index, label in enumerate(self.labels):
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName('PluginCard')
            label.setTextFormat(Qt.PlainText)
            label.setCursor(Qt.ArrowCursor if index in self.locked else Qt.OpenHandCursor)
            label.setToolTip(label.text() if index in self.locked else label.text() + '\n拖到另一画面上交换位置')
            label.installEventFilter(self)
            label.show()
        self._arrange()

    def _arrange(self):
        area = self.rect().adjusted(8, 8, -8, -8)
        width = min(area.width(), round(area.height() * self.aspect))
        canvas = QRect(0, 0, width, min(area.height(), round(width / self.aspect)))
        canvas.moveCenter(area.center())
        for label, rect in zip(self.labels, pane_rectangles(
                len(self.labels), canvas, self.columns, self.aspects, self.primary)):
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
            if (watched in self.labels and self.labels.index(watched) not in self.locked
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
                self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
                self._ghost.setPixmap(self.labels[source].grab())
                self._ghost.setFixedSize(self.labels[source].size())
                self._ghost.show()
            if self._ghost is not None:
                point = self.mapFromGlobal(position)
                self._ghost.move(point - offset)
                self._ghost.raise_()
                self._highlight(next((label for index, label in enumerate(self.labels)
                    if index != source and index not in self.locked and label.geometry().contains(point)), None))
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            source = self._drag[0]
            point = self.mapFromGlobal(event.globalPosition().toPoint())
            target = next((index for index, label in enumerate(self.labels)
                           if index not in self.locked and label.geometry().contains(point)), None)
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
