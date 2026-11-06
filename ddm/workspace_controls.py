"""Bounded plugin rail and searchable function center; plugins own their actions."""
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QActionGroup, QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
                              QPushButton, QScrollArea, QSizePolicy, QToolButton,
                              QVBoxLayout, QWidget)
from . import theme
from .sidebar_navigation import NavigationButton
from .dock_feedback import attach


class WorkspaceIcon(QIconEngine):
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
    pinsChanged = Signal()

    def __init__(self, sidebar):
        super().__init__(sidebar)
        self.sidebar = sidebar
        self.entries = {}
        self.actions = QActionGroup(self)
        self.actions.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self._pin_ids = None
        self._rows = {}
        self._before_center = None
        self.pages = None
        self.setObjectName('WorkspacePanel')
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        self.row = QFrame(self)
        self.row.setObjectName('WorkspaceEntries')
        self.buttons = QVBoxLayout(self.row)
        self.buttons.setContentsMargins(0, 0, 0, 0)
        self.buttons.setSpacing(6)
        box.addWidget(self.row)
        self.launcher = NavigationButton('功能中心', 'functions', sidebar)
        self.launcher.setCheckable(True)
        self.launcher.clicked.connect(self.toggle_popup)
        self.popup = QFrame(sidebar, Qt.Popup | Qt.FramelessWindowHint)
        self.popup.setObjectName('FunctionCenter')
        popup_box = QVBoxLayout(self.popup)
        popup_box.setContentsMargins(12, 12, 12, 12)
        popup_box.setSpacing(10)
        header = QHBoxLayout()
        label = QLabel('功能中心', self.popup)
        label.setObjectName('AppTitle')
        header.addWidget(label, 1)
        close = NavigationButton('关闭功能中心', 'close', self.popup)
        close.setFixedSize(26, 26)
        close.clicked.connect(self.popup.hide)
        header.addWidget(close)
        popup_box.addLayout(header)
        self.search = QLineEdit(self.popup)
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('搜索功能、插件')
        self.search.setAccessibleName('搜索功能、插件')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_rows)
        popup_box.addWidget(self.search)
        self.summary = QLabel(self.popup)
        self.summary.setObjectName('SectionLabel')
        self.summary.setWordWrap(True)
        popup_box.addWidget(self.summary)
        self.scroll = QScrollArea(self.popup)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.rows_box = QVBoxLayout(self.holder)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(4)
        self.rows_box.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.holder)
        popup_box.addWidget(self.scroll, 1)
        self.empty = QLabel('暂无可用功能，可前往插件商店安装', self.holder)
        self.empty.setObjectName('SettingsHint')
        self.empty.setWordWrap(True)
        self.rows_box.addWidget(self.empty)
        self.store_button = QPushButton('插件商店 / 管理插件', self.popup)
        self.store_button.setObjectName('IconButton')
        self.store_button.clicked.connect(self._open_store)
        popup_box.addWidget(self.store_button)
        self.popup.installEventFilter(self)
        sidebar.installEventFilter(self)
        self.hide()

    def add(self, owner, key, widget, priority=0):
        identity = (owner, str(key))
        if not key or identity in self.entries or not isinstance(widget, QToolButton):
            raise ValueError('workspace control needs a unique ID and QToolButton')
        self.entries[identity] = (int(priority), widget)
        icon = QIcon(WorkspaceIcon(widget.icon()))
        if widget.defaultAction() is not None:
            action = widget.defaultAction()
            action.setIcon(icon)
            if action.isCheckable():
                self.actions.addAction(action)
            action.changed.connect(lambda identity=identity: self._sync_rows())
        else:
            widget.setIcon(icon)
        widget.setParent(self.row)
        attach(widget)
        widget.installEventFilter(self)
        widget.toggled.connect(self._sync_rows)
        widget.toggled.connect(lambda checked, widget=widget: self._entry_toggled(widget, checked))
        self.sync_layout()
        self._rebuild_rows()
        if widget.isChecked():
            self._entry_toggled(widget, True)
        else:
            self.sidebar.navigation.activate(self.sidebar.navigation.active_button)
        if self.pages is not None:
            self._sync_page_selection()

    def bind_pages(self, pages):
        self.pages = pages
        pages.changed.connect(self._sync_page_selection)

    def page_button(self):
        if self.pages is not None and self.pages.active is not None:
            owner = self.pages.active[0]
            candidates = [self.entries[key][1] for key in self.ordered() if key[0] == owner]
            if candidates:
                return next((button for button in candidates if button.isChecked()), candidates[0])

    def _sync_page_selection(self):
        button = self.page_button() or self.sidebar.navigation.follow_button
        if self.popup.isVisible():
            self._before_center = button
        else:
            self.sidebar.navigation.activate(button)

    def remove(self, owner, key):
        entry = self.entries.pop((owner, str(key)), None)
        if entry is not None:
            widget = entry[1]
            if self.sidebar.navigation.active_button is widget:
                self.sidebar.navigation.activate(self.sidebar.navigation.follow_button)
            if widget.defaultAction() is not None:
                self.actions.removeAction(widget.defaultAction())
            self.buttons.removeWidget(widget)
            widget.hide()
            widget.setParent(self.sidebar)
            widget.deleteLater()
        self.sync_layout()
        self._rebuild_rows()

    def remove_owner(self, owner):
        for identity in tuple(self.entries):
            if identity[0] == owner:
                self.remove(*identity)

    def ordered(self):
        return sorted(self.entries, key=lambda identity: (self.entries[identity][0], identity))

    def pinned(self):
        return self.ordered()[:2] if self._pin_ids is None else [
            identity for identity in self._pin_ids if identity in self.entries]

    def pin_state(self):
        return None if self._pin_ids is None else [list(identity) for identity in self._pin_ids]

    def restore_pins(self, value):
        self._pin_ids = None if value is None else list(dict.fromkeys(
            tuple(entry) for entry in value if isinstance(entry, (list, tuple))
            and len(entry) == 2 and all(isinstance(part, str) for part in entry)))[:4]
        self.sync_layout()
        self._sync_rows()

    def toggle_pin(self, identity):
        pinned = self.pinned()
        if identity in pinned:
            pinned.remove(identity)
        elif len(pinned) < 4:
            pinned.append(identity)
        else:
            return
        missing = [] if self._pin_ids is None else [i for i in self._pin_ids if i not in self.entries]
        self._pin_ids = (pinned + missing)[:4]
        self.sync_layout(close_popup=False)
        self._sync_rows()
        self.pinsChanged.emit()

    def sync_layout(self, *, close_popup=True):
        navigation = getattr(self.sidebar, 'navigation', None)
        if navigation is None:
            return
        top = self.sidebar.side == 'top'
        self.launcher.setProperty('dockRail', not top)
        if close_popup:
            self.popup.hide()
        if top and self.sidebar._bar_row_box is not None:
            box = self.sidebar._bar_row_box
            self.launcher.setParent(self.sidebar._bar_row)
            box.insertWidget(max(0, box.indexOf(self.sidebar.toggle_button)), self.launcher)
        elif not top:
            if self.parentWidget() is not navigation.pin_holder:
                self.setParent(navigation.pin_holder)
                navigation.pin_box.addWidget(self)
            if self.launcher.parentWidget() is not navigation.rail:
                self.launcher.setParent(navigation.rail)
            navigation.top.addWidget(self.launcher)
        self.launcher.show()
        pinned = self.pinned()
        navigation.divider.setVisible(not top and bool(pinned))
        for identity in self.ordered():
            widget = self.entries[identity][1]
            widget.setProperty('dockRail', not top)
            self.buttons.removeWidget(widget)
            widget.hide()
        for identity in pinned:
            widget = self.entries[identity][1]
            self.buttons.addWidget(widget)
            widget.setObjectName('NavigationButton')
            widget.setToolButtonStyle(Qt.ToolButtonIconOnly)
            widget.setIconSize(QSize(18, 18))
            widget.setFixedSize(34, 34)
            widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            if not widget.toolTip():
                widget.setToolTip(widget.text())
            widget.setAccessibleName(widget.text())
            widget.setVisible(not top)
        self.setVisible(not top and bool(pinned))

    def _entry_toggled(self, widget, checked):
        navigation = self.sidebar.navigation
        if checked:
            navigation.activate(widget)
        elif navigation.active_button is widget:
            navigation.activate(navigation.follow_button)

    def _rebuild_rows(self):
        for row, _launch, _pin in self._rows.values():
            self.rows_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows.clear()
        for identity in self.ordered():
            row = QWidget(self.holder)
            box = QHBoxLayout(row)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(5)
            launch = QToolButton(row)
            launch.setObjectName('FunctionEntry')
            launch.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            launch.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            launch.setMinimumWidth(0)
            launch.setIconSize(QSize(20, 20))
            launch.setCursor(Qt.PointingHandCursor)
            launch.clicked.connect(lambda _checked=False, key=identity: self._launch(key))
            box.addWidget(launch, 1)
            pin = NavigationButton('固定为常用', 'pin', row)
            pin.setCheckable(True)
            pin.clicked.connect(lambda _checked=False, key=identity: self.toggle_pin(key))
            box.addWidget(pin)
            self.rows_box.addWidget(row)
            self._rows[identity] = (row, launch, pin)
        self._sync_rows()
        self._filter_rows()

    def _sync_rows(self, *_args):
        for identity, (_row, launch, pin) in self._rows.items():
            if identity not in self.entries:
                continue
            original = self.entries[identity][1]
            launch.setText(original.text())
            launch.setIcon(original.icon())
            launch.setToolTip(original.toolTip() or original.text())
            launch.setCheckable(original.isCheckable())
            launch.setChecked(original.isChecked())
            launch.setEnabled(original.isEnabled())
            pinned = identity in self.pinned()
            pin.setChecked(pinned)
            pin.setAccessibleName(('取消固定 ' if pinned else '固定 ') + original.text())
            pin.setToolTip('取消固定' if pinned else '固定为常用（最多 4 个）')
            pin.setEnabled(pinned or len(self.pinned()) < 4)

    def _filter_rows(self):
        query = self.search.text().strip().casefold()
        shown = 0
        for row, launch, _pin in self._rows.values():
            visible = not query or query in (launch.text() + ' ' + launch.toolTip()).casefold()
            row.setVisible(visible)
            shown += visible
        self.summary.setText(f'{shown} / {len(self.entries)} 个功能 · 可固定 4 个常用入口')
        self.empty.setText('没有匹配的功能' if self.entries else '暂无可用功能，可前往插件商店安装')
        self.empty.setVisible(not shown)

    def _launch(self, identity):
        self.popup.hide()
        self.entries[identity][1].click()
        self._sync_rows()

    def _open_store(self):
        self.popup.hide()
        self.sidebar.pluginSettingsRequested.emit()

    def toggle_popup(self):
        if self.popup.isVisible():
            self.popup.hide()
            return
        self._rebuild_rows()
        self._before_center = self.sidebar.navigation.active_button
        self.sidebar.navigation.activate(self.launcher)
        anchor = self.launcher.mapToGlobal(QPoint(self.launcher.width()+7, 0))
        screen = QApplication.screenAt(anchor) or self.launcher.screen()
        area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        height = min(560, max(240, 186 + 50*len(self.entries)), area.height())
        self.popup.resize(min(352, area.width()), height)
        self.popup.move(max(area.left(), min(anchor.x(), area.right()-self.popup.width()+1)),
                        max(area.top(), min(anchor.y(), area.bottom()-self.popup.height()+1)))
        self.popup.show()
        self.launcher.setChecked(True)
        self.search.setFocus(Qt.PopupFocusReason)

    def eventFilter(self, watched, event):
        if watched is self.popup and event.type() == QEvent.MouseButtonPress:
            point = self.launcher.mapFromGlobal(event.globalPosition().toPoint())
            if self.launcher.rect().contains(point):
                # Qt closes an outside-clicked popup before replaying the press.
                # The same press on our toggle must only close, never reopen it.
                self.popup.setAttribute(Qt.WA_NoMouseReplay)
        elif watched is self.popup and event.type() == QEvent.Hide:
            self.launcher.setChecked(False)
            navigation = self.sidebar.navigation
            if navigation.active_button is self.launcher:
                previous = self._before_center
                navigation.activate(previous if previous in navigation.buttons() else navigation.follow_button)
        elif watched is self.sidebar and event.type() in (QEvent.Hide, QEvent.Close, QEvent.Resize):
            self.popup.hide()
        elif event.type() in (QEvent.EnabledChange, QEvent.ActionChanged):
            if any(widget is watched for _priority, widget in self.entries.values()):
                self._sync_rows()
        return super().eventFilter(watched, event)
