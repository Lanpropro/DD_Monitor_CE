"""Global tool rail and compact follow controls, using the existing sidebar actions."""
from PySide6.QtCore import QByteArray, QPoint, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                              QSizePolicy, QVBoxLayout, QWidget)

from . import motion, theme


RAIL_WIDTH = 48
PATHS = {
    'follow': '<path d="M12 21 3.5 12.5C-2 6 7 0 12 7c5-7 14-1 8.5 5.5Z"/>',
    'functions': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    'layout': '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M14 3v18M14 12h7"/>',
    'pip': '<rect x="2" y="4" width="20" height="16" rx="2"/><rect x="11" y="11" width="8" height="6" rx="1"/>',
    'settings': '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'more': '<circle cx="5" cy="12" r=".8"/><circle cx="12" cy="12" r=".8"/><circle cx="19" cy="12" r=".8"/>',
    'list': '<path d="M9 6h12M9 12h12M9 18h12M3 6h1M3 12h1M3 18h1"/>',
    'pin': '<path d="m9 3 6 0-1 7 4 4v2H6v-2l4-4ZM12 16v6"/>',
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
        self.set_navigation_mode(True)

    def setText(self, text):
        self._label = text
        super().setText('' if self._navigation_mode else text)

    def set_navigation_mode(self, enabled):
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

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._navigation_mode:
            return
        color = theme.qcolor(theme.ACCENT if self.isChecked() or self.underMouse() else theme.TEXT2)
        if not self.isEnabled():
            color.setAlpha(90)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
               f'fill="none" stroke="{color.name()}" stroke-opacity="{color.alphaF()}" '
               'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
               + PATHS[self.kind] + '</svg>')
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode())).render(
            painter, QRectF((self.width()-18)/2, (self.height()-18)/2, 18, 18))


class SidebarNavigation:
    def __init__(self, sidebar, root_box):
        self.sidebar = sidebar
        self.in_rail = False
        self.rail = QFrame(sidebar)
        self.rail.setObjectName('SidebarRail')
        self.rail.setFixedWidth(RAIL_WIDTH)
        rail_box = QVBoxLayout(self.rail)
        rail_box.setContentsMargins(7, 12, 7, 12)
        rail_box.setSpacing(6)
        self.top = QVBoxLayout()
        self.top.setSpacing(6)
        self.follow_button = NavigationButton('关注直播', 'follow', self.rail)
        self.follow_button.clicked.connect(sidebar.focus_search)
        self.top.addWidget(self.follow_button)
        rail_box.addLayout(self.top)
        self.pin_scroll = QScrollArea(self.rail)
        self.pin_scroll.setFrameShape(QFrame.NoFrame)
        self.pin_scroll.setWidgetResizable(True)
        self.pin_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pin_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pin_holder = QWidget()
        self.pin_box = QVBoxLayout(self.pin_holder)
        self.pin_box.setContentsMargins(0, 6, 0, 0)
        self.pin_box.setSpacing(0)
        self.pin_box.setAlignment(Qt.AlignTop)
        self.pin_scroll.setWidget(self.pin_holder)
        rail_box.addWidget(self.pin_scroll, 1)
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
        self.add_button = NavigationButton('添加与导入', 'plus', self.header)
        self.add_button.clicked.connect(self.open_add_menu)
        self.manage_button = NavigationButton('关注管理', 'more', self.header)
        self.manage_button.clicked.connect(self.open_manage_menu)
        for button in (self.add_button, self.manage_button):
            button.setFixedSize(26, 26)
            header.addWidget(button)
        sidebar._layout.insertWidget(1, self.header)

        self.filters = QWidget(sidebar)
        filters = QHBoxLayout(self.filters)
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(5)
        self.all_button = QPushButton('全部', self.filters)
        self.live_button = QPushButton('直播中', self.filters)
        for button in (self.all_button, self.live_button):
            button.setObjectName('SidebarFilter')
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            filters.addWidget(button)
        self.all_button.clicked.connect(lambda: self.set_live_only(False))
        self.live_button.clicked.connect(lambda: self.set_live_only(True))
        filters.addStretch(1)
        self.density_button = NavigationButton('切换卡片／列表', 'list', self.filters)
        self.density_button.setFixedSize(26, 26)
        self.density_button.clicked.connect(self.toggle_density)
        filters.addWidget(self.density_button)
        sidebar._layout.insertWidget(sidebar._layout.indexOf(sidebar.search)+1, self.filters)

    def sync_count(self):
        sidebar = self.sidebar
        self.count.setText(str(len(sidebar._items)))
        self.live_button.setText(f'直播中 {sum(bool(i.room.get("live")) for i in sidebar._items)}')
        self.all_button.setChecked(not sidebar.live_only)
        self.live_button.setChecked(sidebar.live_only)
        self.density_button.setToolTip('切换为列表' if sidebar.card_mode else '切换为封面卡片')

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

    def open_add_menu(self):
        sidebar = self.sidebar
        menu = self._menu(self.add_button)
        menu.addAction('添加直播间…').triggered.connect(sidebar.add_button.click)
        menu.addAction('导入关注…').triggered.connect(sidebar.import_button.click)
        menu.addSeparator()
        menu.addAction('新建文件夹…').triggered.connect(sidebar.prompt_folder)
        menu.popup(self.add_button.mapToGlobal(QPoint(0, self.add_button.height()+4)))
        self.menu = menu

    def open_manage_menu(self):
        sidebar = self.sidebar
        menu = self._menu(self.manage_button)
        action = menu.addAction('多选管理')
        action.setCheckable(True)
        action.setChecked(sidebar.select_mode)
        action.triggered.connect(sidebar.set_select_mode)
        menu.addAction('刷新关注状态').triggered.connect(sidebar.refresh_button.click)
        menu.addSeparator()
        sorting = menu.addMenu('默认分组排序')
        sidebar.add_folder_sort_menu(sorting, sidebar.default_folder())
        menu.popup(self.manage_button.mapToGlobal(QPoint(0, self.manage_button.height()+4)))
        self.menu = menu

    def release(self):
        """Return original controls before the portrait header adopts them."""
        sidebar = self.sidebar
        self.rail.hide()
        self.header.hide()
        self.filters.hide()
        if not self.in_rail:
            return
        for button in (sidebar.layout_button, sidebar.picture_in_picture_button, sidebar.settings_button):
            button.set_navigation_mode(False)
            button.setParent(sidebar.tool_row)
            sidebar.tool_row.layout().addWidget(button)
            button.show()
        sidebar._restore_side_children()
        sidebar._restore_toggle_to_header()
        self.in_rail = False

    def sync(self):
        sidebar = self.sidebar
        left = sidebar.side == 'left'
        self.rail.setVisible(left)
        self.header.setVisible(left)
        self.filters.setVisible(left and not sidebar.collapsed)
        if not left:
            return
        sidebar._layout.insertWidget(0, self.header)
        sidebar._layout.removeWidget(self.filters)
        sidebar._layout.insertWidget(sidebar._layout.indexOf(sidebar.search)+1, self.filters)
        if not self.in_rail:
            for button in (sidebar.layout_button, sidebar.picture_in_picture_button,
                           sidebar.notification_button, sidebar.appearance_button, sidebar.settings_button):
                button.setParent(self.rail)
                self.bottom.addWidget(button, 0, Qt.AlignHCenter)
            sidebar.toggle_button.setParent(self.header)
            self.header.layout().addWidget(sidebar.toggle_button)
            self.in_rail = True
        for button in (sidebar.layout_button, sidebar.picture_in_picture_button, sidebar.settings_button):
            button.set_navigation_mode(True)
            button.show()
        for button in (sidebar.notification_button, sidebar.appearance_button):
            button.setObjectName('NavigationButton')
            button.setProperty('sidebarCompact', False)
            button.setFixedSize(34, 34)
            button.show()
        for widget in (sidebar._header_row, sidebar.status_row, sidebar.tool_row, sidebar.normal_bar):
            widget.hide()
        for widget in (self.title, self.count, self.add_button, self.manage_button):
            widget.setVisible(not sidebar.collapsed)
        sidebar.toggle_button.show()
        self.sync_count()
