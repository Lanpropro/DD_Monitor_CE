"""Mutually exclusive plugin pages inside the host's existing content area."""
from PySide6.QtCore import QEvent, QObject, Qt, Signal


class WorkspacePages(QObject):
    changed = Signal()

    def __init__(self, container):
        super().__init__(container)
        self.container = container
        self.active = None
        self.hidden = {}
        container.installEventFilter(self)

    def show_page(self, owner, widget, *, manages_content=False):
        if self.active is not None and self.active[1] is not widget:
            if not self.close_active():
                return False
        if self.active is None:
            self.active = (owner, widget, manages_content)
            if widget.parentWidget() is not self.container or widget.isWindow():
                widget.setParent(self.container, Qt.Widget)
            widget.installEventFilter(self)
            if not manages_content:
                layout = self.container.layout()
                if layout is not None:
                    for index in range(layout.count()):
                        base = layout.itemAt(index).widget()
                        if base is not None and base is not widget:
                            self.hidden[base] = not base.isHidden()
                            base.installEventFilter(self)
                            base.hide()
            widget.setGeometry(self.container.rect())
        widget.show()
        widget.raise_()
        self.changed.emit()
        return True

    def close_active(self):
        current = self.active
        if current is not None:
            if not current[1].close():
                return False
            if self.active is current:
                self._restore()
        return True

    def close_owner(self, owner):
        if self.active is not None and self.active[0] == owner:
            self.active[1].close()
            if self.active is not None:
                self._restore()

    def _restore(self):
        if self.active is not None:
            self.active[1].removeEventFilter(self)
        self.active = None
        hidden, self.hidden = self.hidden, {}
        for base, visible in hidden.items():
            base.removeEventFilter(self)
            base.setVisible(visible)
        self.changed.emit()

    def eventFilter(self, watched, event):
        if self.active is not None:
            page = self.active[1]
            if watched is self.container and event.type() == QEvent.Resize:
                page.setGeometry(self.container.rect())
            elif watched is page and event.type() == QEvent.Hide and page.isHidden():
                self._restore()
            elif watched in self.hidden and event.type() == QEvent.Show:
                self.hidden[watched] = True
                watched.hide()
        return super().eventFilter(watched, event)
