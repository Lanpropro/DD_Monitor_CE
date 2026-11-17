"""Portrait toolbar and follow strip; borrow the landscape controls and signals."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout, QWidget

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
        host._bar_row_box.setSpacing(6)
        host._bar_row.resized.connect(self.sync_density)
        self.follow_group = QWidget(host._bar_row)
        self.follow_box = QHBoxLayout(self.follow_group)
        self.follow_box.setContentsMargins(0, 0, 0, 0)
        self.follow_box.setSpacing(2)
        self.follow_label = QLabel('关注', self.follow_group)
        self.follow_label.setBuddy(host.navigation.follow_button)
        self.divider = QFrame(host._bar_row)
        self.divider.setObjectName('NavigationDivider')
        self.divider.setFixedSize(2, 18)
        self.controls = PortraitBar(host)
        self.controls.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.controls_box = QHBoxLayout(self.controls)
        self.controls_box.setSizeConstraint(QLayout.SetNoConstraint)
        self.controls_box.setContentsMargins(0, 0, 0, 0)
        self.controls_box.setSpacing(6)
        host._bar_row2 = QWidget(host)
        host._bar_row2_box = QHBoxLayout(host._bar_row2)
        host._bar_row2_box.setContentsMargins(0, 0, 0, 0)
        # Keep the old selection/spacing delegates valid; there is no right column.
        host._bar_right = QWidget(host._bar_row2)
        host._bar_right_box = QVBoxLayout(host._bar_right)
        host._bar_gaps = ()
        host._bar_right.hide()

    def _detach(self, widget):
        self.host._detach_from_rows(widget)
        self.controls_box.removeWidget(widget)
        self.follow_box.removeWidget(widget)

    def place_launcher(self):
        host = self.host
        launcher = host.workspace_controls.launcher
        if launcher.parentWidget() is not host._bar_row or host._bar_row_box.indexOf(launcher) != 1:
            host._bar_row_box.removeWidget(launcher)
            launcher.setParent(host._bar_row)
            host._bar_row_box.insertWidget(1, launcher)

    def adopt(self):
        host, nav = self.host, self.host.navigation
        self.ensure()
        if not host._bar_in_use:
            for widget in (host._header_row, host.search, host._head_scroll, host.batch_bar,
                           host.notification_button, host.layout_button, host.picture_in_picture_button,
                           host.settings_button, host.account_row, host.toggle_button,
                           nav.follow_button, nav.filters, nav.add_button, nav.manage_button):
                self._detach(widget)
                widget.setParent(host._bar_row)
            while host._bar_row_box.count():
                host._bar_row_box.takeAt(0)
            for widget in (nav.follow_button, self.follow_label, host.toggle_button):
                self.follow_box.addWidget(widget)
            host._bar_row_box.addWidget(self.follow_group)
            self.place_launcher()
            host._bar_row_box.addWidget(self.divider)
            for widget in (host.layout_button, host.picture_in_picture_button):
                host._bar_row_box.addWidget(widget)
            host._bar_row_box.addStretch(1)
            for widget in (host.notification_button, host.settings_button, host.account_row):
                host._bar_row_box.addWidget(widget)
            for widget in (host.search, host._head_scroll, host.batch_bar):
                self.controls_box.addWidget(widget, 1)
            for widget in (nav.filters, nav.add_button, nav.manage_button):
                self.controls_box.addWidget(widget)
            nav.filters.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            host.search.setMinimumWidth(96)
            self._detach(host.scroll)
            host.scroll.setParent(host._bar_row2)
            host._bar_row2_box.addWidget(host.scroll)
            host._layout.insertWidget(0, host._bar_row)
            host._layout.insertWidget(1, self.controls)
            host._layout.insertWidget(2, host._bar_row2)
            host._bar_in_use = True
        host._bar_row.show()
        self.controls.show()

    def sync_density(self):
        host = self.host
        if host.side != 'top' or not host._bar_in_use:
            return
        nav = host.navigation
        for button in (host.layout_button, host.picture_in_picture_button, host.settings_button,
                       host.clear_wall_button):
            button.set_navigation_mode(True)
            button.setProperty('dockRail', False)
        nav.follow_button.setProperty('dockRail', False)
        for button in (host.batch_button, host.notification_button, host.appearance_button,
                       host.refresh_button):
            button.setObjectName('NavigationButton')
            button.setProperty('sidebarCompact', False)
            button.setFixedSize(34, 34)
            if isinstance(button, BarIconButton):
                button.set_icon_mode(True)
        for button in (host.batch_button, host.clear_wall_button, host.appearance_button,
                       host.refresh_button):
            button.hide()
        for button in (nav.follow_button, host.layout_button, host.picture_in_picture_button,
                       host.notification_button, host.settings_button,
                       host.workspace_controls.launcher, host.toggle_button):
            button.show()
        follow_controls = not host.collapsed and not host.select_mode
        for widget in (nav.filters, nav.add_button, nav.manage_button):
            widget.setVisible(follow_controls)
        nav.folder_toggle_button.hide()
        nav.density_button.hide()
        host.account_row.setVisible(not host.select_mode)
        self.follow_label.setVisible(host.width() >= 420)
        host.toggle_button.setObjectName('BarToggle')
        host.toggle_button.setFixedSize(22, 22)
        host._bar_row.setFixedHeight(max(34, self.follow_group.sizeHint().height(), host.account_row.height()))
        self.controls.setFixedHeight(max(34, host.search.sizeHint().height(), host.batch_bar.sizeHint().height()))

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
        for row in (host._bar_row, self.controls, host._bar_row2):
            host._layout.removeWidget(row)
            row.hide()
        for widget in (nav.follow_button, host.toggle_button, nav.filters, nav.add_button,
                       nav.manage_button, *host._column_order):
            self._detach(widget)
        for widget in host._column_order:
            host._layout.addWidget(widget)
        nav.follow_button.setParent(nav.rail)
        nav.follow_button.setProperty('dockRail', True)
        nav.top.insertWidget(0, nav.follow_button)
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
