"""Release an editor's focus when a pointer chooses another settings surface."""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget


class SettingsInputFocus(QObject):
    def __init__(self, root):
        super().__init__(root)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget):
            root = self.parent()
            if root.isVisible() and (watched is root or root.isAncestorOf(watched)):
                focus = QApplication.focusWidget()
                if (focus is not None and root.isAncestorOf(focus) and focus is not watched
                        and not focus.isAncestorOf(watched)):
                    focus.clearFocus()
        return False
