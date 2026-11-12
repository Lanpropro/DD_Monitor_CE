"""Release an editor's focus when a pointer chooses another settings surface."""
from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QComboBox,
                               QScrollArea, QSlider, QWidget)


class SettingsInputFocus(QObject):
    def __init__(self, root):
        super().__init__(root)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        root = self.parent()
        if (event.type() == QEvent.Wheel and isinstance(watched, QWidget) and root.isVisible()
                and (watched is root or root.isAncestorOf(watched))):
            return self._wheel(watched, event)
        if event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget):
            if root.isVisible() and (watched is root or root.isAncestorOf(watched)):
                focus = QApplication.focusWidget()
                if (focus is not None and root.isAncestorOf(focus) and focus is not watched
                        and not focus.isAncestorOf(watched)):
                    focus.clearFocus()
        return False

    def _wheel(self, watched, event):
        popup = QApplication.activePopupWidget()
        if popup is not None and (watched is popup or popup.isAncestorOf(watched)):
            return False
        owner, blocked = watched, False
        delta = event.pixelDelta().y() or event.angleDelta().y()
        while owner is not None and owner is not self.parent():
            if isinstance(owner, QSlider):
                if owner.orientation() == Qt.Horizontal and owner.isEnabled():
                    return False
                blocked = True
            elif isinstance(owner, (QComboBox, QAbstractSpinBox)):
                blocked = True
            elif isinstance(owner, QAbstractItemView):
                bar = owner.verticalScrollBar()
                can_scroll = delta > 0 and bar.value() > bar.minimum() or delta < 0 and bar.value() < bar.maximum()
                if not blocked and can_scroll:
                    return False
                blocked = True  # Chain to the page at either end of a nested list.
            elif isinstance(owner, QScrollArea):
                bar = owner.verticalScrollBar()
                if bar.maximum() <= bar.minimum():
                    return True
                amount = abs(delta)
                step = bar.singleStep() * max(1, round(amount / 120)) if amount else bar.singleStep()
                bar.setValue(bar.value() - step if delta > 0 else bar.value() + step)
                event.accept()
                return True
            owner = owner.parentWidget()
        return blocked
