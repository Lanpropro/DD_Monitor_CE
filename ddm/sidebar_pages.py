"""Owner-scoped plugin pages in the expanded follow sidebar."""
from PySide6.QtCore import QObject, QSize
from PySide6.QtWidgets import QToolButton


class SidebarPages(QObject):
    def __init__(self, sidebar):
        super().__init__(sidebar)
        self.sidebar = sidebar
        self.entries = {}
        self.current = None
        self.follow_query = ""
        self.queries = {}

    def add(self, owner, identity, widget, title, icon, on_filter=None):
        key = (owner, identity)
        self.remove(owner, identity)
        sidebar = self.sidebar
        button = QToolButton(sidebar.navigation.filters)
        button.setObjectName('NavigationButton')
        button.setIcon(icon)
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(26, 26)
        button.setCheckable(True)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(lambda: self.select(key))
        sidebar.navigation.filters.layout().insertWidget(2, button)
        sidebar._layout.insertWidget(sidebar._layout.indexOf(sidebar.scroll), widget, 1)
        widget.hide()
        self.entries[key] = (widget, button, title, on_filter)
        self.sync()

    def select(self, key=None):
        sidebar = self.sidebar
        new = key if key in self.entries else None
        if new != self.current:
            if self.current is None:
                self.follow_query = sidebar.search.text()
            else:
                self.queries[self.current] = sidebar.search.text()
            self.current = new
            query = self.queries.get(new, '') if new is not None else self.follow_query
            blocked = sidebar.search.blockSignals(True)
            sidebar.search.setText(query)
            sidebar.search.blockSignals(blocked)
            self.filter(query)
        self.sync()

    def filter(self, text):
        if self.current is None:
            return False
        handler = self.entries[self.current][3]
        if handler is not None:
            handler(text)
        return True

    def sync(self):
        sidebar = self.sidebar
        available = sidebar.side == 'left' and not sidebar.collapsed
        if not available:
            sidebar.batch_button.setEnabled(True)
            if self.current is not None:
                self.select()
                return
            for widget, button, _title, _handler in self.entries.values():
                widget.hide()
                button.hide()
                button.setChecked(False)
            sidebar.scroll.show()
            return
        active = self.current is not None
        for key, (widget, button, _title, _handler) in self.entries.items():
            if key == self.current:
                # Portrait restoration reseats host controls, leaving extension
                # pages at their previous index. Keep the active page inside the
                # content slot, after the host filters and before the follow list.
                layout = sidebar._layout
                if not (layout.indexOf(sidebar.navigation.filters)
                        < layout.indexOf(widget) < layout.indexOf(sidebar.scroll)):
                    layout.removeWidget(widget)
                    layout.insertWidget(layout.indexOf(sidebar.scroll), widget, 1)
            widget.setVisible(available and key == self.current)
            button.setVisible(available)
            button.setChecked(key == self.current)
        sidebar.scroll.setVisible(not active)
        nav = sidebar.navigation
        # Preserve the host header/search/filter structure; only swap content.
        for widget in (nav.folder_toggle_button, sidebar.batch_button):
            widget.setEnabled(not active)
        if active:
            sidebar.batch_bar.hide()
            nav.all_button.setChecked(False)
            nav.live_button.setChecked(False)
        else:
            nav.all_button.setChecked(not sidebar.live_only)
            nav.live_button.setChecked(sidebar.live_only)

    def remove(self, owner, identity):
        key = (owner, identity)
        if self.current == key:
            self.select()
        entry = self.entries.pop(key, None)
        self.queries.pop(key, None)
        if entry is None:
            return
        widget, button, _title, _handler = entry
        self.sidebar._layout.removeWidget(widget)
        widget.hide()
        widget.setParent(None)
        button.deleteLater()
        self.sync()

    def remove_owner(self, owner):
        for key in tuple(self.entries):
            if key[0] == owner:
                self.remove(*key)
