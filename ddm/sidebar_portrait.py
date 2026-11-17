"""Portrait follow header; borrow existing controls without changing their actions."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QVBoxLayout, QWidget

from .ui.toolbar import BarIconButton


class PortraitBar(QWidget):
    resized = Signal()

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        size.setWidth(0)
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class PortraitSidebar:
    def __init__(self, host):
        self.host = host

    def ensure(self):
        host = self.host
        if host._bar_row is not None:
            return
        host._bar_row = PortraitBar(host)
        host._bar_row_box = QHBoxLayout(host._bar_row)
        host._bar_row_box.setSizeConstraint(QLayout.SetNoConstraint)
        host._bar_row.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        host._bar_row_box.setContentsMargins(0, 0, 0, 0)
        host._bar_row_box.setSpacing(4)
        host._bar_row.resized.connect(self.sync_density)
        host._bar_row2 = QWidget(host)
        host._bar_row2_box = QHBoxLayout(host._bar_row2)
        host._bar_row2_box.setContentsMargins(0, 0, 0, 0)
        # Retained for selection/account compatibility; the new header has no
        # separate right column stealing width from the horizontal follow strip.
        host._bar_right = QWidget(host._bar_row2)
        host._bar_right_box = QVBoxLayout(host._bar_right)
        host._bar_gaps = ()  # Legacy spacing delegates have no portrait spacers to adjust.
        host._bar_right.hide()

    def adopt(self):
        host, nav = self.host, self.host.navigation
        self.ensure()
        if not host._bar_in_use:
            for widget in (host._header_row, host.search, host._head_scroll, host.batch_bar,
                           *host._bar_icons(), host.layout_button, host.picture_in_picture_button,
                           host.settings_button, host.account_row, host.toggle_button,
                           nav.filters, nav.add_button, nav.manage_button):
                host._detach_from_rows(widget)
                widget.setParent(host._bar_row)
            for widget in (host.search, host._head_scroll, host.batch_bar):
                host._bar_row_box.addWidget(widget, 1)
            for widget in (nav.filters, nav.add_button, nav.manage_button, host.batch_button,
                           host.notification_button, host.appearance_button, host.refresh_button,
                           host.clear_wall_button, host.layout_button, host.picture_in_picture_button,
                           host.settings_button, host.account_row, host.toggle_button):
                host._bar_row_box.addWidget(widget)
            nav.filters.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            host.search.setMinimumWidth(96)
            host._detach_from_rows(host.scroll)
            host.scroll.setParent(host._bar_row2)
            host._bar_row2_box.addWidget(host.scroll)
            host._layout.insertWidget(0, host._bar_row)
            host._layout.insertWidget(1, host._bar_row2)
            host._bar_in_use = True
        host._bar_row.show()

    def sync_density(self):
        host = self.host
        if host.side != 'top' or not host._bar_in_use:
            return
        nav = host.navigation
        width = host.width()
        select = host.select_mode
        for button in (host.layout_button, host.picture_in_picture_button, host.settings_button,
                       host.clear_wall_button):
            button.set_navigation_mode(True)
            button.setProperty('dockRail', False)
        for button in (host.batch_button, host.notification_button, host.appearance_button,
                       host.refresh_button):
            button.setObjectName('NavigationButton')
            button.setProperty('sidebarCompact', False)
            button.setFixedSize(30, 30)
            if isinstance(button, BarIconButton):
                button.set_icon_mode(True)
        for button in (host.layout_button, host.picture_in_picture_button,
                       host.batch_button, host.clear_wall_button):
            button.setVisible(width >= 800 and not select)
        for button in (nav.add_button, host.appearance_button, host.refresh_button):
            button.setVisible(width >= 640 and not select)
        for button in (nav.manage_button, host.notification_button, host.settings_button,
                       host.workspace_controls.launcher, host.toggle_button):
            button.show()
        nav.filters.setVisible(not select)
        nav.folder_toggle_button.hide()
        nav.density_button.hide()
        host.account_row.setVisible(host._account_row_should_show())
        height = max(34, host.search.sizeHint().height(), host.batch_bar.sizeHint().height())
        host._bar_row.setFixedHeight(height)
        host.toggle_button.setObjectName('BarToggle')
        host.toggle_button.setFixedSize(22, 22)

    def sync(self):
        host = self.host
        if host.side != 'top':
            host._sync_appearance_row()
            return
        self.adopt()
        select = host.select_mode
        host._head_scroll.setVisible(host.collapsed and not select)
        host.search.setVisible(not host.collapsed and not select)
        host.batch_bar.setVisible(select)
        host._bar_row2.setVisible(not host.collapsed)
        host.scroll.setVisible(not host.collapsed)
        for widget in (host._header_row, host.status_row, host.normal_bar, host.tool_row):
            widget.hide()
        host._sync_account_row_shape()
        host._sync_account_row_width()
        host._sync_toggle_arrow()
        if host.collapsed:
            host.refresh_strip()
        else:
            host._apply_scroll_axis()
        host._sync_appearance_row()
        self.sync_density()

    def release(self):
        host, nav = self.host, self.host.navigation
        if not host._bar_in_use:
            return
        for row in (host._bar_row, host._bar_row2):
            host._layout.removeWidget(row)
            row.hide()
        for widget in host._column_order:
            host._detach_from_rows(widget)
            host._layout.addWidget(widget)
        for button in (host.layout_button, host.picture_in_picture_button, host.settings_button):
            button.setParent(host.tool_row)
            host.tool_row.layout().addWidget(button)
            button.setSizePolicy(host._tool_button_policies[button])
        nav.filters.setParent(host._column)
        nav.filters.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        for button in (nav.add_button, nav.manage_button):
            button.setParent(nav.header)
            nav.header.layout().addWidget(button)
        host.search.setMinimumWidth(0)
        host.account_row.setSizePolicy(host._account_policy)
        host._bar_in_use = False
        host._sync_account_row_shape()
        host._sync_account_row_width()
