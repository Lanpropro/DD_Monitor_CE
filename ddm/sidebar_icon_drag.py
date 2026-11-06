"""Reorder icons within their existing rail groups without invoking their actions."""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget
from shiboken6 import isValid

from . import theme


class SidebarIconDrag(QObject):
    def __init__(self, navigation):
        super().__init__(navigation)
        self.navigation = navigation
        self.source = None
        self.ghost = None
        self.marker = None
        QApplication.instance().installEventFilter(self)

    def groups(self):
        sidebar = self.navigation.sidebar
        if sidebar.side != 'left' or not self.navigation.rail.isVisible():
            return []
        controls = sidebar.workspace_controls
        return [[controls.entries[key][1] for key in controls.pinned()],
                self.navigation.movable_tools()]

    def destination(self, position):
        rail = self.navigation.rail
        point = rail.mapFromGlobal(position)
        if not rail.rect().contains(point):
            return None
        if self.group not in self.groups() or not all(isValid(button) for button in self.group):
            return None
        bounds = [button.mapTo(rail, QPoint()) for button in self.group]
        if not bounds or not bounds[0].y() - 3 <= point.y() <= bounds[-1].y() + self.group[-1].height() + 3:
            return None
        others = [button for button in self.group if button is not self.source]
        index = sum(point.y() > button.mapTo(rail, button.rect().center()).y() for button in others)
        return index

    def begin(self):
        rail = self.navigation.rail
        self.ghost = QLabel(rail)
        self.ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.source.setDown(False)
        feedback = self.source._dock_feedback
        feedback.transition(1, animate=False)
        feedback.hover(animate=False)
        self.ghost.setPixmap(self.source.grab())
        self.ghost.setFixedSize(self.source.size())
        self.ghost.show()
        self.marker = QFrame(rail)
        self.marker.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.marker.setFixedSize(30, 2)
        self.marker.setStyleSheet(f'background: {theme.ACCENT}; border: none;')
        self.source.grabMouse(Qt.ClosedHandCursor)

    def update_position(self, position):
        rail = self.navigation.rail
        point = rail.mapFromGlobal(position)
        self.ghost.move((rail.width() - self.ghost.width()) // 2,
                        max(0, min(point.y() - self.offset.y(), rail.height() - self.ghost.height())))
        self.ghost.raise_()
        index = self.destination(position)
        self.marker.setVisible(index is not None)
        if index is not None:
            others = [button for button in self.group if button is not self.source]
            before = others[index] if index < len(others) else None
            y = (before.mapTo(rail, QPoint()).y() - 4 if before is not None else
                 others[-1].mapTo(rail, QPoint()).y() + others[-1].height() + 2)
            self.marker.move((rail.width() - self.marker.width()) // 2, y)
            self.marker.raise_()

    def cancel(self, *_args):
        source, self.source = self.source, None
        if source is not None and isValid(source):
            source.destroyed.disconnect(self.cancel)
            source.setDown(False)
            if QWidget.mouseGrabber() is source:
                source.releaseMouse()
            source._dock_feedback.transition(1, animate=False)
        for widget in (self.ghost, self.marker):
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self.ghost = self.marker = None

    def eventFilter(self, watched, event):
        kind = event.type()
        if self.source is None:
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                group = next((group for group in self.groups() if watched in group), None)
                if group is not None and len(group) > 1 and watched.isEnabled():
                    self.source, self.group = watched, group
                    self.press = event.globalPosition().toPoint()
                    self.offset = event.position().toPoint()
                    watched.destroyed.connect(self.cancel)
            return False
        if kind == QEvent.MouseMove:
            if not event.buttons() & Qt.LeftButton:
                self.cancel()
                return False
            position = event.globalPosition().toPoint()
            if self.ghost is None and (position - self.press).manhattanLength() >= QApplication.startDragDistance():
                self.begin()
            if self.ghost is not None:
                self.update_position(position)
                return True
        elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            dragging = self.ghost is not None
            index = self.destination(event.globalPosition().toPoint()) if dragging else None
            source, group = self.source, self.group
            if not dragging:
                self.source.destroyed.disconnect(self.cancel)
                self.source = None
                return False
            self.cancel()
            if index is not None:
                ordered = [button for button in group if button is not source]
                ordered.insert(index, source)
                self.navigation.reorder_group(group, ordered)
            return True
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel()
            return True
        elif (kind == QEvent.ApplicationDeactivate or
              watched is self.source and kind in (QEvent.Hide, QEvent.UngrabMouse) or
              watched is self.navigation.sidebar.window() and kind in (QEvent.Hide, QEvent.WindowDeactivate) or
              watched is self.navigation.rail and kind in (QEvent.Hide, QEvent.Resize)):
            self.cancel()
        return False
