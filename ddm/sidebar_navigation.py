"""Global tool rail and compact follow controls, using the existing sidebar actions."""
from PySide6.QtCore import (QAbstractAnimation, QByteArray, QEvent, QObject, QPoint, QRectF, QSize, Qt,
                           Signal, QVariantAnimation)
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                              QSizePolicy, QVBoxLayout, QWidget)
from shiboken6 import isValid

from . import motion, theme
from .dock_feedback import active, attach, icon_color


RAIL_WIDTH = 48
PATHS = {
    'follow': '<path d="M12 21 3.5 12.5C-2 6 7 0 12 7c5-7 14-1 8.5 5.5Z"/>',
    'functions': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    'layout': '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M14 3v18M14 12h7"/>',
    'clear': '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    'wall_settings': '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M6 10h12M6 15h12M9 8v4M15 13v4"/>',
    'pip': '<rect x="2" y="4" width="20" height="16" rx="2"/><rect x="11" y="11" width="8" height="6" rx="1"/>',
    'settings': '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    'import': '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
    'import_follows': '<circle cx="8" cy="7" r="3"/><path d="M2 20v-2a6 6 0 0 1 12 0v2m8-8h-7m3-3-3 3 3 3"/>',
    'tv': '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="m8 3 4 4 4-4"/>',
    'open_folder': '<path d="M3 19V6a1 1 0 0 1 1-1h5l2 3h8a1 1 0 0 1 1 1v2M3 19l3-8h16l-3 8Z"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'more': '<circle cx="5" cy="12" r=".8"/><circle cx="12" cy="12" r=".8"/><circle cx="19" cy="12" r=".8"/>',
    'collapse': '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18m7-12-3 3 3 3"/>',
    'expand': '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M9 3v18m4-12 3 3-3 3"/>',
    'folders_expand': '<path d="m6 4 6 5 6-5M6 14l6 5 6-5"/>',
    'folders_collapse': '<path d="m6 9 6-5 6 5M6 19l6-5 6 5"/>',
    'multiselect': '<rect x="3.5" y="8" width="12.5" height="12.5" rx="2"/><path d="M8 4h12v12m-14-2 2 2 5-5"/>',
    'filter_all': '<path d="M6 3h12"/><rect x="3" y="7" width="18" height="14" rx="2"/><path d="m10 11 6 3-6 3Z"/>',
    'filter_live': '<path d="M8 8a6 6 0 0 0 0 8m8-8a6 6 0 0 1 0 8M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>',
    'pin': '<path d="m9 3 6 0-1 7 4 4v2H6v-2l4-4ZM12 16v6"/>',
    'rename': '<path d="m5 15.5 10.6-10.6a2.1 2.1 0 0 1 3 3L8 18.5 4 20zM13.6 6.9l3 3"/>',
    'external_link': '<path d="M13 4h7v7m0-7-9 9m6 0v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1h6"/>',
    'close': '<path d="m6 6 12 12M18 6 6 18"/>',
}


class NavigationButton(QPushButton):
    def __init__(self, text, kind, parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self._label = text
        self._navigation_mode = False
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        attach(self)
        self.set_navigation_mode(True)

    def setText(self, text):
        self._label = text
        super().setText('' if self._navigation_mode else text)

    def set_navigation_mode(self, enabled):
        if (enabled and self._navigation_mode and self.objectName() == 'NavigationButton'
                and getattr(self, '_navigation_dock_rail', None) == self.property('dockRail')
                and self.minimumSize() == self.maximumSize() == QSize(34, 34)
                and self.sizePolicy().horizontalPolicy() == QSizePolicy.Fixed
                and self.sizePolicy().verticalPolicy() == QSizePolicy.Fixed
                and not self.text()):
            return
        self._navigation_mode = enabled
        self.setObjectName('NavigationButton' if enabled else 'IconButton')
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        if enabled:
            self.setFixedSize(34, 34)
        self.setSizePolicy(QSizePolicy.Fixed if enabled else QSizePolicy.Preferred, QSizePolicy.Fixed)
        super().setText('' if enabled else self._label)
        self.style().unpolish(self)
        self.style().polish(self)
        self._navigation_dock_rail = self.property('dockRail')

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._navigation_mode:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width()/2, self.height()/2)
        self._dock_feedback.transform(painter)
        if self.kind in ('folders_expand', 'folders_collapse') and self.property('horizontalFolderIcon'):
            painter.rotate(-90)
        self._paint_icon(painter)

    def _paint_icon(self, painter):
        color = icon_color(self)
        fill = color.name() if self.kind in ('follow', 'functions') and active(self) else 'none'
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'fill="{fill}" stroke="{color.name()}" stroke-opacity="{color.alphaF()}" '
               'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
               + PATHS[self.kind]
               + (f'<circle cx="12" cy="12" r="3" fill="{theme.PINK}" stroke="none"/>'
                  if self.kind == 'filter_live' else '') + '</svg>')
        QSvgRenderer(QByteArray(svg.encode())).render(
            painter, QRectF(-9, -9, 18, 18))


class AddRoomButton(NavigationButton):
    openRequested = Signal()
    closeRequested = Signal()
    _OPEN_ANGLE = 45.0

    def __init__(self, parent):
        super().__init__('添加与导入', 'plus', parent)
        self._pointer_click = False
        self._opening = False
        self.panel_open = False
        self._angle = 0.0
        self._turn = QVariantAnimation(self)
        self._turn.setDuration(motion.CONTROL_FEEDBACK_MS)
        self._turn.setEasingCurve(motion.THEME_WAVE_EASING)
        self._turn.valueChanged.connect(self._set_angle)
        self._turn.finished.connect(self._finish_open)
        self.clicked.connect(self._toggle_panel)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._opening:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pointer_click = event.button() == Qt.LeftButton
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._pointer_click = False

    def _toggle_panel(self):
        if self.panel_open:
            self.closeRequested.emit()
            return
        if self._opening and self._pointer_click:
            return
        self._opening = True
        self._rotate_to(self._OPEN_ANGLE, animate=self._pointer_click)
        if self._turn.state() == QAbstractAnimation.Stopped:
            self._finish_open()

    def _finish_open(self):
        if not self._opening:
            return
        self._opening = False
        self.panel_open = True
        self.openRequested.emit()

    def _set_angle(self, angle):
        self._angle = angle
        self.update()

    def _rotate_to(self, angle, *, animate):
        self._turn.stop()
        if animate and self.isVisible() and motion.enabled() and self._angle != angle:
            self._turn.setStartValue(self._angle)
            self._turn.setEndValue(angle)
            self._turn.start()
        else:
            self._set_angle(angle)

    def cancel_open(self):
        if self._opening:
            self._opening = False
            self._rotate_to(0.0, animate=False)

    def panel_dismissed(self):
        if self.panel_open:
            self.panel_open = False
            self._rotate_to(0.0, animate=True)

    def hideEvent(self, event):
        self._opening = False
        self._rotate_to(self._OPEN_ANGLE if self.panel_open else 0.0, animate=False)
        super().hideEvent(event)

    def _paint_icon(self, painter):
        painter.rotate(self._angle)
        super()._paint_icon(painter)


class SidebarNavigation(QObject):
    orderChanged = Signal()

    def __init__(self, sidebar, root_box):
        super().__init__(sidebar)
        self.sidebar = sidebar
        self.in_rail = False
        self._pointer_button = None
        self._tool_order = []
        self.rail = QFrame(sidebar)
        self.rail.setObjectName('SidebarRail')
        self.rail.setFixedWidth(RAIL_WIDTH)
        rail_box = QVBoxLayout(self.rail)
        rail_box.setContentsMargins(7, 12, 7, 12)
        rail_box.setSpacing(6)
        self.top = QVBoxLayout()
        self.top.setSpacing(6)
        self.follow_button = NavigationButton('关注直播', 'follow', self.rail)
        self.follow_button.setProperty('dockRail', True)
        self.active_button = self.follow_button
        self.follow_button.setProperty('dockActive', True)
        self.follow_button.clicked.connect(self.show_follow)
        self.top.addWidget(self.follow_button)
        rail_box.addLayout(self.top)
        self.divider = QFrame(self.rail)
        self.divider.setObjectName('NavigationDivider')
        self.divider.setFixedSize(24, 2)
        rail_box.addWidget(self.divider, 0, Qt.AlignHCenter)
        self.pin_scroll = QScrollArea(self.rail)
        self.pin_scroll.setFrameShape(QFrame.NoFrame)
        self.pin_scroll.setWidgetResizable(True)
        self.pin_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pin_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pin_holder = QWidget()
        self.pin_box = QVBoxLayout(self.pin_holder)
        self.pin_box.setContentsMargins(0, 0, 0, 0)
        self.pin_box.setSpacing(0)
        self.pin_box.setAlignment(Qt.AlignTop)
        self.pin_scroll.setWidget(self.pin_holder)
        rail_box.addWidget(self.pin_scroll, 1)
        self.tools_divider = QFrame(self.rail)
        self.tools_divider.setObjectName('NavigationDivider')
        self.tools_divider.setFixedSize(24, 2)
        rail_box.addWidget(self.tools_divider, 0, Qt.AlignHCenter)
        self.fixed_divider = QFrame(self.rail)
        self.fixed_divider.setObjectName('NavigationDivider')
        self.fixed_divider.setFixedSize(24, 2)
        self.bottom = QVBoxLayout()
        self.bottom.setSpacing(6)
        rail_box.addLayout(self.bottom)
        root_box.insertWidget(0, self.rail)

        self.header = QWidget(sidebar)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.title = QLabel('关注', self.header)
        self.title.setObjectName('AppTitle')
        self.count = QLabel(self.header)
        self.count.setObjectName('SectionLabel')
        header.addWidget(self.title)
        header.addWidget(self.count)
        header.addStretch(1)
        self.add_button = AddRoomButton(self.header)
        self.add_button.openRequested.connect(self.open_add_menu)
        self.collapsed_add_button = NavigationButton('添加与导入', 'plus', self.rail)
        self.collapsed_add_button.clicked.connect(lambda: self.open_add_menu(anchor=self.collapsed_add_button))
        self.top.addWidget(self.collapsed_add_button, 0, Qt.AlignHCenter)
        self.collapsed_add_button.setFixedSize(24, 24)
        self.collapsed_add_button.hide()
        self.manage_button = NavigationButton('关注管理', 'more', self.header)
        self.manage_button.clicked.connect(self.open_manage_menu)
        for button in (self.add_button, self.manage_button):
            button.setFixedSize(26, 26)
            header.addWidget(button)
        header.addStretch(0)
        self._header_tail = header.itemAt(header.count() - 1)
        sidebar._layout.insertWidget(1, self.header)

        self.filters = QWidget(sidebar)
        filters = QHBoxLayout(self.filters)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(5)
        self.all_button = NavigationButton('全部直播间', 'filter_all', self.filters)
        self.live_button = NavigationButton('仅显示直播中', 'filter_live', self.filters)
        for button in (self.all_button, self.live_button):
            button.setFixedSize(26, 26)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            filters.addWidget(button)
        self.all_button.clicked.connect(lambda: self.set_live_only(False))
        self.live_button.clicked.connect(lambda: self.set_live_only(True))
        for button in (self.all_button, self.live_button):
            button.clicked.connect(lambda: sidebar.plugin_pages.select())
        filters.addStretch(1)
        self.folder_toggle_button = NavigationButton('全部折叠文件夹', 'folders_collapse', self.filters)
        self.folder_toggle_button.setFixedSize(26, 26)
        self.folder_toggle_button.clicked.connect(sidebar.toggle_all_folders)
        filters.addWidget(self.folder_toggle_button)
        sidebar._layout.insertWidget(sidebar._layout.indexOf(sidebar.search)+1, self.filters)
        from .sidebar_icon_drag import SidebarIconDrag
        self.icon_drag = SidebarIconDrag(self)
        QApplication.instance().installEventFilter(self)

    def sync_pointer_hover(self):
        hit = None
        if (self.rail.isVisible() and not QApplication.activePopupWidget()
                and not QApplication.activeModalWidget() and not QApplication.mouseButtons()):
            point = QCursor.pos()
            if self.rail.rect().contains(self.rail.mapFromGlobal(point)):
                # A missing Qt Enter can leave underMouse false even on a hit.
                hit = QApplication.widgetAt(point)
        button = (hit if isinstance(hit, QAbstractButton) and self.rail.isAncestorOf(hit)
                  and hit.property('dockRail') and hit.isEnabled() else None)
        previous, self._pointer_button = self._pointer_button, button
        if previous is not button and previous is not None and isValid(previous):
            if previous.property('dockHovered') is True:
                previous.setProperty('dockHovered', False)
                previous.update()
        if button is not None and button.property('dockHovered') is not True:
            button.setProperty('dockHovered', True)
            button.update()

    def movable_tools(self):
        fixed = (self.fixed_divider, self.sidebar.notification_button,
                 self.sidebar.appearance_button, self.sidebar.settings_button,
                 self.sidebar.wall_settings_button)
        return [self.bottom.itemAt(index).widget() for index in range(self.bottom.count())
                if self.bottom.itemAt(index).widget() not in fixed]

    def tool_key(self, button):
        return button.kind

    def order_state(self):
        return list(self._tool_order)

    def restore_order(self, value):
        self._tool_order = list(dict.fromkeys(key for key in value
            if isinstance(key, str) and key in ('layout', 'clear', 'pip'))) if isinstance(value, list) else []
        self._sort_tools()

    def _sort_tools(self):
        if not self.in_rail:
            return
        tools = {self.tool_key(button): button for button in self.movable_tools()}
        keys = [key for key in self._tool_order if key in tools]
        keys.extend(key for key in tools if key not in keys)
        ordered = [tools[key] for key in keys] + [self.fixed_divider, self.sidebar.notification_button,
                                                self.sidebar.appearance_button, self.sidebar.settings_button]
        ordered.insert(ordered.index(self.sidebar.picture_in_picture_button), self.sidebar.wall_settings_button)
        for index, widget in enumerate(ordered):
            if self.bottom.indexOf(widget) != index:
                # Explicit removal invalidates PySide's old QWidgetItem wrapper.
                # insertWidget's implicit removal leaves a stale binding on 6.11.2.
                self.bottom.removeWidget(widget)
                self.bottom.insertWidget(index, widget, 0, Qt.AlignHCenter)
        self.fixed_divider.show()

    def reorder_group(self, before, after):
        if before == after:
            return
        controls = self.sidebar.workspace_controls
        pinned = controls.pinned()
        if before == [controls.entries[key][1] for key in pinned]:
            identities = {widget: key for key, (_priority, widget) in controls.entries.items()}
            controls.reorder_pins([identities[button] for button in after])
        elif before == self.movable_tools():
            self._tool_order = [self.tool_key(button) for button in after]
            self._sort_tools()
            self.orderChanged.emit()

    def buttons(self):
        return [self.follow_button, self.sidebar.workspace_controls.launcher,
                *[widget for _priority, widget in self.sidebar.workspace_controls.entries.values()]]

    def activate(self, button, *, animate=False):
        if button is self.follow_button:
            button = self.sidebar.workspace_controls.page_button() or button
        changed = button is not self.active_button
        self.active_button = button
        for entry in self.buttons():
            selected = entry is button
            if entry.property('dockActive') != selected:
                entry.setProperty('dockActive', selected)
                entry.style().unpolish(entry)
                entry.style().polish(entry)
                entry.update()
        if changed and animate:
            attach(button).pulse()

    def show_follow(self):
        self.sidebar.plugin_pages.select()
        controls = self.sidebar.workspace_controls
        controls.popup.hide()
        if controls.pages is not None and not controls.pages.close_active():
            controls._sync_page_selection()
            return
        self.sidebar.focus_search()
        self.activate(self.follow_button)

    def eventFilter(self, watched, event):
        kind = event.type()
        pointer = kind == QEvent.MouseButtonPress
        escape = kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and event.key() == Qt.Key_Escape
        if (pointer and watched is not self.add_button) or escape:
            self.add_button.cancel_open()
        keyboard = kind == QEvent.FocusIn and event.reason() in (
            Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)
        if (pointer or keyboard) and isinstance(watched, QWidget):
            column = self.sidebar._column
            if watched is column or column.isAncestorOf(watched):
                self.activate(self.follow_button, animate=pointer)
        return False

    def sync_count(self):
        sidebar = self.sidebar
        self.count.setText(str(len(sidebar._items)))
        expand = sidebar.folder_control.bulk_action_is_expand()
        previous = sidebar.folder_collapse_mode == 'previous' and bool(sidebar._bulk_fold_previous)
        label = ('全部展开文件夹' if expand else
                 '恢复展开前收起的文件夹' if previous else '全部折叠文件夹')
        self.folder_toggle_button.setText(label)
        self.folder_toggle_button.setAccessibleName(label)
        self.folder_toggle_button.setToolTip(label + '（保留当前筛选）')
        self.folder_toggle_button.kind = 'folders_expand' if expand else 'folders_collapse'
        self.folder_toggle_button.setEnabled(not sidebar._folder_drag_previous)
        self.folder_toggle_button.update()
        live_count = sum(bool(i.room.get('live')) for i in sidebar._items)
        self.all_button.setToolTip(f'全部直播间（{len(sidebar._items)}）')
        self.live_button.setToolTip(f'仅显示直播中（{live_count}）')
        self.all_button.setChecked(not sidebar.live_only)
        self.live_button.setChecked(sidebar.live_only)
        if hasattr(sidebar, 'plugin_pages'):
            sidebar.plugin_pages.sync()

    def set_live_only(self, live_only):
        self.sidebar.live_only = live_only
        self.sidebar.refresh_filter()

    def toggle_density(self):
        sidebar = self.sidebar
        enabled = not sidebar.card_mode
        sidebar.set_compact_policy(enabled, False, sidebar.compact_threshold)
        sidebar.cardModeChanged.emit(enabled)
        self.sync_count()

    def _menu(self, button):
        menu = motion.AnimatedMenu(self.sidebar)
        menu.setAttribute(Qt.WA_DeleteOnClose)
        menu.aboutToHide.connect(lambda: button.setDown(False))
        return menu

    def open_add_menu(self, _checked=False, *, anchor=None):
        self.sidebar.addRoomClicked.emit()

    def open_manage_menu(self):
        sidebar = self.sidebar
        menu = self._menu(self.manage_button)
        if sidebar.side != 'top':
            density = menu.addAction('切换为列表' if sidebar.card_mode else '切换为封面卡片')
            density.setEnabled(sidebar.plugin_pages.current is None)
            density.triggered.connect(self.toggle_density)
            menu.addAction('全部展开文件夹').triggered.connect(lambda: sidebar.set_all_folders_collapsed(False))
            fold = menu.addAction('恢复展开前收起的文件夹' if sidebar.folder_collapse_mode == 'previous' and sidebar._bulk_fold_previous
                                  else '全部折叠文件夹')
            fold.triggered.connect(lambda: sidebar.set_all_folders_collapsed(True))
            menu.addSeparator()
        sorting = menu.addMenu('默认分组排序')
        sidebar.add_folder_sort_menu(sorting, sidebar.default_folder())
        menu.popup(self.manage_button.mapToGlobal(QPoint(0, self.manage_button.height()+4)))
        self.menu = menu

    def release(self):
        """Return original controls before the portrait header adopts them."""
        sidebar = self.sidebar
        sidebar.plugin_pages.select()
        self.icon_drag.cancel()
        self.rail.hide()
        self.header.hide()
        self.filters.hide()
        if not self.in_rail:
            return
        sidebar._detach_from_rows(sidebar.workspace_controls.launcher)
        for button in (sidebar.layout_button, sidebar.wall_settings_button, sidebar.picture_in_picture_button,
                       sidebar.settings_button):
            sidebar._detach_from_rows(button)
            button.setProperty('dockRail', False)
            button.set_navigation_mode(False)
            button.setParent(sidebar.tool_row)
            sidebar.tool_row.layout().addWidget(button)
            button.show()
        for button in (sidebar.notification_button, sidebar.appearance_button):
            sidebar._detach_from_rows(button)
            button.setProperty('dockRail', False)
        sidebar.clear_wall_button.setProperty('dockRail', False)
        sidebar._restore_side_children()
        sidebar._restore_toggle_to_header()
        self.in_rail = False

    def sync(self):
        sidebar = self.sidebar
        self.icon_drag.cancel()
        left = sidebar.side == 'left'
        self.rail.setVisible(left)
        add = self.collapsed_add_button
        holder = sidebar._column if left else sidebar._bar_row
        if holder is not None and add.parentWidget() is not holder:
            self.top.removeWidget(add)
            previous = add.parentWidget()
            if previous is not None and previous.layout() is not None:
                previous.layout().removeWidget(add)
            add.setParent(holder)
            (sidebar._layout if left else sidebar._bar_row_box).addWidget(add)
        add.setVisible(holder is not None and sidebar.collapsed)
        self.header.setVisible(left)
        self.filters.setVisible(not sidebar.collapsed and (left or not sidebar.select_mode))
        self.folder_toggle_button.setVisible(left or (not sidebar.collapsed and not sidebar.select_mode))
        self.divider.setVisible(left and bool(sidebar.workspace_controls.pinned()))
        self.tools_divider.setVisible(left and bool(sidebar.workspace_controls.pinned()))
        if not left:
            self.manage_button.setToolTip('关注与常用操作')
            self.manage_button.setAccessibleName('关注与常用操作')
            return
        self.manage_button.setToolTip('关注管理')
        self.manage_button.setAccessibleName('关注管理')
        if sidebar._layout.indexOf(self.header) != 0:
            sidebar._layout.removeWidget(self.header)
            sidebar._layout.insertWidget(0, self.header)
        sidebar._layout.removeWidget(self.filters)
        sidebar._layout.insertWidget(sidebar._layout.indexOf(sidebar.search)+1, self.filters)
        for button in (sidebar.batch_button, sidebar.refresh_button):
            if self.filters.layout().indexOf(button) < 0:
                sidebar._detach_from_rows(button)
                self.filters.layout().addWidget(button)
            button.setVisible(not sidebar.collapsed)
        if not self.in_rail:
            for button in (sidebar.layout_button, sidebar.clear_wall_button, sidebar.wall_settings_button,
                           sidebar.picture_in_picture_button,
                           sidebar.notification_button, sidebar.appearance_button, sidebar.settings_button):
                sidebar._detach_from_rows(button)
                button.setParent(self.rail)
                self.bottom.addWidget(button, 0, Qt.AlignHCenter)
            self.in_rail = True
        if sidebar.toggle_button.parentWidget() is not self.header:
            sidebar._detach_from_rows(sidebar.toggle_button)
            sidebar.toggle_button.setParent(self.header)
            self.header.layout().insertWidget(self.header.layout().count() - 1, sidebar.toggle_button)
        for button in (sidebar.layout_button, sidebar.clear_wall_button, sidebar.wall_settings_button,
                       sidebar.picture_in_picture_button, sidebar.settings_button):
            button.setProperty('dockRail', True)
            button.set_navigation_mode(True)
            button.show()
        for button in (sidebar.notification_button, sidebar.appearance_button):
            motion_kind = 'notification' if button is sidebar.notification_button else 'appearance'
            style_changed = (button.property('dockMotion') != motion_kind
                             or button.property('dockRail') is not True
                             or button.objectName() != 'NavigationButton'
                             or button.property('sidebarCompact') is not False)
            attach(button)
            button.setProperty('dockMotion', motion_kind)
            button.setProperty('dockRail', True)
            button.setObjectName('NavigationButton')
            button.setProperty('sidebarCompact', False)
            if style_changed:
                button.style().unpolish(button)
                button.style().polish(button)
            button.setFixedSize(34, 34)
            button.show()
        for widget in (sidebar._header_row, sidebar.status_row, sidebar.tool_row, sidebar.normal_bar):
            widget.hide()
        for widget in (self.title, self.count, self.add_button, self.manage_button):
            widget.setVisible(not sidebar.collapsed)
        sidebar.toggle_button.show()
        sidebar._layout.removeWidget(add)
        header = self.header.layout()
        for control in (self.add_button, self.manage_button, sidebar.toggle_button):
            header.removeWidget(control)
            tail = next(index for index in range(header.count()) if header.itemAt(index) is self._header_tail)
            header.insertWidget(tail, control)
        header.setStretch(header.count() - 1, 1 if sidebar.collapsed else 0)
        sidebar._layout.insertWidget(sidebar._layout.indexOf(self.header) + 1, add, 0,
                                     Qt.AlignHCenter if sidebar.collapsed else Qt.AlignRight)
        self._sort_tools()
        self.sync_count()
