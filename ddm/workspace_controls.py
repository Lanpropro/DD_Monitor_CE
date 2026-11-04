"""Plugin workspace entries, separate from the existing account/list actions."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout
from . import theme


class WorkspaceIcon(QIconEngine):
    """Keep plugin entry glyphs legible when the host changes its appearance."""
    def __init__(self, source):
        super().__init__()
        self.source = QIcon(source)

    def clone(self):
        return WorkspaceIcon(self.source)

    def pixmap(self, size, mode, state):
        result = QPixmap(size)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return result

    def paint(self, painter, rect, mode, state):
        pixmap = self.source.pixmap(rect.size(), mode, state)
        tint = QPainter(pixmap)
        tint.setCompositionMode(QPainter.CompositionMode_SourceIn)
        tint.fillRect(pixmap.rect(), theme.qcolor(theme.TEXT2))
        tint.end()
        painter.drawPixmap(rect, pixmap)


class WorkspaceControls(QFrame):
    def __init__(self, sidebar):
        super().__init__(sidebar)
        self.sidebar = sidebar
        self.entries = {}
        self.setObjectName('WorkspacePanel')
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(6, 7, 6, 7)
        self.box.setSpacing(5)
        self.label = QLabel('工作区', self)
        self.label.setObjectName('SectionLabel')
        self.box.addWidget(self.label)
        self.row = QFrame(self)
        self.row.setObjectName('WorkspaceEntries')
        self.buttons = QHBoxLayout(self.row)
        self.buttons.setContentsMargins(0, 0, 0, 0)
        self.buttons.setSpacing(6)
        self.box.addWidget(self.row)
        self.hide()

    def add(self, owner, key, widget, priority=0):
        identity = (owner, str(key))
        if not key or identity in self.entries or not isinstance(widget, QToolButton):
            raise ValueError('workspace control needs a unique ID and QToolButton')
        self.entries[identity] = (int(priority), widget)
        icon = QIcon(WorkspaceIcon(widget.icon()))
        if widget.defaultAction() is not None:
            widget.defaultAction().setIcon(icon)
        else:
            widget.setIcon(icon)
        widget.setParent(self.row)
        # The plugin owns action state and click behavior; the host owns placement.
        self.sync_layout()

    def remove(self, owner, key):
        entry = self.entries.pop((owner, str(key)), None)
        if entry is not None:
            widget = entry[1]
            self.buttons.removeWidget(widget)
            widget.hide()
            widget.setParent(self.sidebar)
            widget.deleteLater()
        self.sync_layout()

    def remove_owner(self, owner):
        for identity in tuple(self.entries):
            if identity[0] == owner:
                self.remove(*identity)

    def sync_layout(self):
        sidebar = self.sidebar
        top = sidebar.side == 'top'
        compact = top or sidebar.collapsed
        if top and getattr(sidebar, '_bar_row_box', None) is not None:
            parent, box = sidebar._bar_row, sidebar._bar_row_box
            index = box.indexOf(sidebar.toggle_button)
        else:
            parent, box = sidebar.footer.body, sidebar.footer_box
            index = box.indexOf(sidebar.account_row)
        if self.parentWidget() is not parent or box.indexOf(self) < 0 or box.indexOf(self) != index - 1:
            old = self.parentWidget().layout()
            if old is not None:
                old.removeWidget(self)
            self.setParent(parent)
            box.insertWidget(box.indexOf(sidebar.toggle_button) if top else box.indexOf(sidebar.account_row), self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.label.hide()
        self.buttons.setDirection(QBoxLayout.TopToBottom if sidebar.collapsed and not top else QBoxLayout.LeftToRight)
        ordered = sorted(self.entries.items(), key=lambda item: (item[1][0], item[0]))
        for index, (_identity, (_priority, widget)) in enumerate(ordered):
            if self.buttons.indexOf(widget) != index:
                self.buttons.removeWidget(widget)
                self.buttons.insertWidget(index, widget, 1)
            name = 'BarIcon' if compact else 'WorkspaceEntry'
            if widget.objectName() != name:
                widget.setObjectName(name)
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            widget.setToolButtonStyle(Qt.ToolButtonIconOnly if compact else Qt.ToolButtonTextBesideIcon)
            widget.setIconSize(QSize(16, 16))
            widget.setMinimumSize(QSize(30, 30) if compact else QSize(0, 30))
            widget.setMaximumSize(QSize(30, 30) if compact else QSize(16777215, 16777215))
            widget.setSizePolicy(QSizePolicy.Fixed if compact else QSizePolicy.Expanding, QSizePolicy.Fixed)
            widget.show()
        self.setVisible(bool(ordered))
        sidebar.footer.title.setText('工作区' if ordered else '常用操作')
        sidebar.footer.title.setVisible(not sidebar.collapsed)
        sidebar.footer.restore_button.setToolButtonStyle(
            Qt.ToolButtonIconOnly if sidebar.collapsed else Qt.ToolButtonTextBesideIcon)
        sidebar.footer.setVisible(not top)
        sidebar.footer.refresh()
        box.activate()
        self.box.activate()
        self.buttons.activate()
