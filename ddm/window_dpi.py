"""Defer repeated QWidget DPI notifications until native geometry has caught up."""
from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


class DpiEventBatch(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self._widgets = set()
        self._events = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.flush)

    def begin(self):
        if self._timer.isActive():
            return
        root = self.parent()
        self._widgets = {root, *root.findChildren(QWidget)}
        # The last installed application filter runs first, ahead of plugin filters.
        QApplication.instance().installEventFilter(self)
        self._timer.start(0)

    def eventFilter(self, watched, event):
        if watched in self._widgets:
            kind = event.type()
            if kind in (QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange):
                self._events[watched, kind] = None
                return True
        return False

    def cancel(self):
        self._timer.stop()
        QApplication.instance().removeEventFilter(self)
        self._events = {}
        self._widgets.clear()

    def flush(self):
        events = self._events
        self.cancel()
        # Native QWindow handling has already updated screens and geometry.
        # Keep the first-seen order and deliver each widget/type pair once.
        for widget, kind in events:
            if isValid(widget):
                QApplication.sendEvent(widget, QEvent(kind))
