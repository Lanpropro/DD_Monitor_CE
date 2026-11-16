"""Follow sidebar coordination and appearance toggle; cards and account rows stay separate."""
import os
import sys

from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QCursor, QKeySequence, QPainter, QPen, QPixmap, QRegion, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QVBoxLayout, QWidget
)

from . import follow_folders, layouts, motion, theme, version as version_module
from .account_widgets import AccountPopupMenu, AccountRow
from .avatar_widgets import RoomStrip
from .dock_feedback import icon_color
from .folder_icons import create_folder_dialog
from .playback_controls import RefreshButton, SidebarToggleButton
from .sidebar_item import NavItem
from .sidebar_list import CarouselScroll, RoomListBox
from .sidebar_folders import FollowFolderButton, SmartFolderCard, SmartFolderDialog
from .sidebar_drag import SidebarDrag
from .sidebar_navigation import NavigationButton, RAIL_WIDTH, SidebarNavigation
from .ui.toolbar import BarIconButton
from .watch_history import WatchHistory
from .widget_support import (
    BRAND_ASSETS_DIR, NAV_ITEM_GAP, NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT, _repolish
)
from .workspace_controls import WorkspaceControls
from .sidebar_filter import SidebarFilter
from .sidebar_folder_control import SidebarFolderControl
from .sidebar_selection import SidebarSelection
from .sidebar_sort import SidebarSort
from .sidebar_account_control import SidebarAccountControl
from .sidebar_presentation import SidebarPresentation
from .sidebar_items import SidebarItems
from .sidebar_interaction import SidebarInteraction


class AppearanceButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChipButton")
        self.setFixedSize(22, 22)
        self.setStyleSheet("padding: 0;")
        self.setCursor(Qt.PointingHandCursor)
        self.refresh_theme()

    def refresh_theme(self):
        current = "浅色" if theme.is_light() else "深色"
        target = "深色" if theme.is_light() else "浅色"
        following = "，跟随系统" if theme.mode() == "system" else ""
        self.setToolTip("切换为" + target + "（当前：" + current + following + "）")

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width()/2, self.height()/2)
        if hasattr(self, '_dock_feedback'):
            self._dock_feedback.transform(painter)
        rect = QRectF(-7, -7, 14, 14)
        color = icon_color(self)
        painter.setPen(QPen(color, 1.4))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPie(rect, 90*16, 180*16)


class Sidebar(QFrame):
    """左侧房间列表：可收起、可批量选择删除。"""

    SORT_MODES = follow_folders.SORT_MODES

    #: 竖屏横栏里账号条的宽度上限（昵称太长就省略，别把搜索框挤没）
    ACCOUNT_PILL_MAX = 220

    roomSelected = Signal(dict)
    addRoomClicked = Signal()
    importFollowsClicked = Signal()
    addToWallRequested = Signal(dict)
    removeRequested = Signal(dict)
    openBrowserRequested = Signal(str)
    deleteRequested = Signal(list)
    collapsedChanged = Signal(bool)
    collapseAnimationChanged = Signal(bool)
    logoutRequested = Signal()
    platformLogoutRequested = Signal(str)
    loginRequested = Signal()
    pinChanged = Signal(list)
    sortChanged = Signal(str)
    orderChanged = Signal()
    foldersChanged = Signal()
    refreshRequested = Signal()
    previewHovered = Signal(dict)       # 鼠标停在某个直播间上
    previewUnhovered = Signal(dict)
    layoutChosen = Signal(str)
    pictureInPictureRequested = Signal()
    clearWallRequested = Signal()
    layoutResetRequested = Signal()
    settingsRequested = Signal()
    pluginSettingsRequested = Signal()
    cardModeChanged = Signal(bool)
    appearanceChanged = Signal(str)
    # 注意：菜单项要走**已经接好的**信号 —— addRoomClicked / importFollowsClicked
    # 才是 MainWindow 连了槽的那两个；另起名字会是「发了没人听」的空信号
    # （用户报的「登录按钮点了没反应」就是踩了这个）。

    def __init__(self, rooms: list[dict], parent=None, card_mode: bool = True,
                 auto_compact: bool = True, compact_threshold: int = 18,
                 compact_background: bool = True):
        super().__init__(parent)
        self.items_control = SidebarItems(self)
        self.interaction_control = SidebarInteraction(self)
        self.folder_control = SidebarFolderControl(self)
        self.filter_control = SidebarFilter(self)
        self.selection_control = SidebarSelection(self)
        self.sort_control = SidebarSort(self)
        self.account_control = SidebarAccountControl(self)
        self.presentation_control = SidebarPresentation(self)
        self.setObjectName("Sidebar")
        self.setFixedWidth(theme.SIDEBAR_WIDTH + RAIL_WIDTH)
        self._items: list[NavItem] = []
        self._drag_snapshot_ready = False
        self._drag_snapshot_timer = QTimer(self)
        self._drag_snapshot_timer.setSingleShot(True)
        self._drag_snapshot_timer.timeout.connect(self._prepare_drag_snapshot)
        self.browser_url_resolver = lambda _room: ""
        self._collapse_animating = False
        self.collapsed = False
        self.preferred_card_mode = bool(card_mode)
        self.auto_compact = bool(auto_compact)
        self.compact_threshold = max(2, int(compact_threshold))
        self.compact_background = bool(compact_background)
        self.card_mode = self.preferred_card_mode and not (
            self.auto_compact and len(rooms) >= self.compact_threshold)
        self._wall_room_ids: set[str] = set()
        self.select_mode = False
        self._sort_selected_ids: set[str] = set()
        self._sort_anchor: str | None = None
        self.side = "left"                     # left = 横屏的左栏；top = 竖屏的顶部横栏
        self.pinned: list[str] = []
        self.sort_mode = "custom"
        self.import_order: list[str] = []      # 导入/添加的先后顺序，用于「导入顺序」排序
        self.custom_order: list[str] = []      # 拖动排出来的顺序，切换排序方式也不丢
        self.watch_history = WatchHistory()
        self._frequent_scores = {}
        self._frequent_folders = set()
        self.folders: list[dict] = follow_folders.normalize_folders([])
        self._folder_assignments: dict[str, str] = {}
        self._smart_cards: dict[tuple[str, str], SmartFolderCard] = {}
        self._folder_pending: set[str] = set()
        self._entering_room_ids: set[str] = set()
        self._card_entry_timer = QTimer(self)
        self._card_entry_timer.setSingleShot(True)
        self._card_entry_timer.timeout.connect(self._reveal_added_rooms)
        self._folders_folded_by_drag: set[str] = set()
        self._folder_drag_previous: dict[str, bool] = {}
        self._folder_buttons: dict[str, FollowFolderButton] = {}
        self._layout_id = layouts.DEFAULT_LAYOUT

        self._outer_layout = QHBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._outer_layout.setSpacing(0)
        self._column = QWidget(self)
        self._outer_layout.addWidget(self._column, 1)
        layout = QVBoxLayout(self._column)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)
        self._layout = layout

        # 竖屏顶部横栏里的头像排；横屏时一直是隐藏的。
        # 外面套一个滚动区：关注多了头像排放不下，就横向滚（不显示滚动条，
        # 免得占掉头像那一行的高度；滚轮/触控板横向滚，和卡片条同一套机制）。
        self._head_strip = RoomStrip(self)
        self._head_strip.roomClicked.connect(self._on_strip_room)
        self._head_strip.roomHovered.connect(self.previewHovered.emit)
        self._head_strip.roomUnhovered.connect(self.previewUnhovered.emit)
        self._head_scroll = CarouselScroll(self)
        self._head_scroll.setWidgetResizable(True)
        self._head_scroll.setFrameShape(QFrame.NoFrame)
        self._head_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._head_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._head_scroll.horizontal_only = True
        self._head_scroll.setFixedHeight(self._head_strip.height())
        self._head_scroll.setWidget(self._head_strip)
        self._head_scroll.setVisible(False)
        layout.addWidget(self._head_scroll)

        # 标题行（做成一个容器，竖屏收起时整行收掉）
        self._header_row = QWidget(self)
        header = QHBoxLayout(self._header_row)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)
        self.logo_label = QLabel(self._header_row)
        self.logo_label.setObjectName("AppLogo")
        self.logo_label.setToolTip(version_module.DISPLAY_NAME)
        self._brand_logo = QPixmap(os.path.join(BRAND_ASSETS_DIR, "logo.png"))
        self.title_box = QVBoxLayout()
        self.title_box.setSpacing(0)
        title = QLabel(version_module.DISPLAY_NAME, self._header_row)
        title.setObjectName("AppTitle")
        subtitle = QLabel("多窗口直播监控", self._header_row)
        subtitle.setObjectName("AppSubtitle")
        #: 竖屏横栏第一行只留标题当 logo（副标题藏起来，横栏高度很紧）
        self.title_label = title
        self.subtitle_label = subtitle
        self.title_box.addWidget(title)
        self.title_box.addWidget(subtitle)
        self._set_brand_header(compact=False)
        self.batch_button = BarIconButton("多选", "check")
        self.batch_button.setObjectName("ChipButton")
        self.batch_button.setCursor(Qt.PointingHandCursor)
        self.batch_button.setToolTip("多选卡片后可一起拖动、移到最前或最后，也可批量删除")
        self.batch_button.setCheckable(True)
        self.batch_button.setAccessibleName("多选直播间")
        self.batch_button.setObjectName("BarIcon")
        self.batch_button.setProperty("sidebarCompact", True)
        self.batch_button.set_icon_mode(True)
        self.batch_button.setFixedSize(22, 22)
        self.batch_button.clicked.connect(lambda: self.set_select_mode(not self.select_mode))
        self.toggle_button = SidebarToggleButton(self)
        self.toggle_button.setToolTip("收起 / 展开房间列表")
        self.toggle_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.logo_label, 0, Qt.AlignVCenter)
        header.addLayout(self.title_box, 1)
        header.addWidget(self.toggle_button, 0, Qt.AlignTop)
        layout.addWidget(self._header_row)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索主播 / 房间号")
        self.search.setToolTip("支持中文、全拼和拼音首字母；多个词用空格分隔")
        self.search.setClearButtonEnabled(True)
        #: 当前搜索词（已去空白、转小写）；空串 = 不过滤
        self.filter_text = ""
        self.live_only = False
        self.search.textChanged.connect(self.apply_filter)      # 边打字边过滤
        # 回车不再额外「执行搜索」（本来就实时），把焦点交给列表，接着就能直接
        # 点选 / 拖动；Esc 等价于点清空按钮（清空按钮自己会走 textChanged）
        self.search.returnPressed.connect(self._focus_room_list)
        escape = QShortcut(QKeySequence(Qt.Key_Escape), self.search)
        escape.setContext(Qt.WidgetShortcut)
        escape.activated.connect(self.search.clear)
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.setContext(Qt.WindowShortcut)
        self.find_shortcut.activated.connect(self.focus_search)
        layout.addWidget(self.search)

        self.status_row = QWidget(self)
        status_box = QHBoxLayout(self.status_row)
        status_box.setContentsMargins(0, 0, 0, 0)
        status_box.setSpacing(4)
        self.count_label = QLabel(f"关注中 · {len(rooms)}")
        self.count_label.setObjectName("SectionLabel")
        self.count_label.setToolTip("右键文件夹标题可设置该文件夹的排序")
        from .notification_center import NotificationButton
        self.notification_button = NotificationButton(self)
        self.refresh_button = RefreshButton(size=22, object_name="ChipButton")
        self.appearance_button = AppearanceButton(self)
        self.appearance_button.clicked.connect(lambda: self.appearanceChanged.emit(
            "dark" if theme.is_light() else "light"))
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        status_box.addWidget(self.count_label, 1)
        status_box.addWidget(self.batch_button, 0, Qt.AlignRight)
        status_box.addWidget(self.notification_button, 0, Qt.AlignRight)
        status_box.addWidget(self.appearance_button, 0, Qt.AlignRight)
        status_box.addWidget(self.refresh_button, 0, Qt.AlignRight)
        layout.addWidget(self.status_row)

        scroll = CarouselScroll()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 固定预留滚动条宽度，展开文件夹跨过滚动阈值时卡片不缩放。
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll = scroll
        holder = RoomListBox(self)
        self.list_box = holder
        self._pointer_hover_item = None
        self._hover_sync_timer = QTimer(self)
        self._hover_sync_timer.setInterval(30)
        self._hover_sync_timer.timeout.connect(self._sync_pointer_hover)
        self.drag_session = SidebarDrag(self)
        for room in rooms:
            self._append_item(room)
        holder.relayout(animate=False)
        scroll.setWidget(holder)
        for bar in (scroll.verticalScrollBar(), scroll.horizontalScrollBar()):
            bar.valueChanged.connect(lambda _value: QTimer.singleShot(0, self._refresh_visible_covers))
            bar.valueChanged.connect(self._sync_pointer_hover)
        layout.addWidget(scroll, 1)

        # 底部：批量操作条 / 正常操作
        self.batch_bar = QWidget()
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(6)
        self.batch_label = QLabel("已选 0 个")
        self.batch_label.setObjectName("NavSub")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.clicked.connect(self._emit_delete)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("IconButton")
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(lambda: self.set_select_mode(False))
        batch_layout.addWidget(self.batch_label, 1)
        batch_layout.addWidget(self.delete_button)
        batch_layout.addWidget(self.cancel_button)
        self.batch_bar.setVisible(False)
        layout.addWidget(self.batch_bar)

        self.workspace_controls = WorkspaceControls(self)

        # 已登录账号（在底部操作之上）
        self.account_row = AccountRow(self, allow_logout=True)
        self.account_row.logoutClicked.connect(self.logoutRequested)
        self.account_row.clicked.connect(self._open_account_menu)
        # 未登录时它就是「登录」按钮，所以一开始就要露出来
        self.account_row.set_account("")
        self.account_row.setVisible(self._account_row_should_show())
        layout.addWidget(self.account_row)

        # 布局 + 设置：原来挂在右侧顶栏，现在跟着列表放左下角
        self.tool_row = QWidget(self)
        tool_box = QHBoxLayout(self.tool_row)
        tool_box.setContentsMargins(0, 0, 0, 0)
        tool_box.setSpacing(6)
        self.layout_button = NavigationButton('布局预设', 'layout')
        self.layout_button.setFocusPolicy(Qt.TabFocus)
        self.layout_button.setObjectName("IconButton")
        self.layout_button.setCursor(Qt.PointingHandCursor)
        self.layout_button.setToolTip("选择布局方式")
        self.layout_button.clicked.connect(self.open_layout_picker)
        self.clear_wall_button = NavigationButton('清空画面墙', 'clear')
        self.clear_wall_button.clicked.connect(self.clearWallRequested.emit)
        self.picture_in_picture_button = NavigationButton('画中画', 'pip')
        self.picture_in_picture_button.setObjectName('IconButton')
        self.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
        self.picture_in_picture_button.clicked.connect(self.pictureInPictureRequested.emit)
        self.settings_button = NavigationButton('设置', 'settings')
        self.settings_button.setFocusPolicy(Qt.TabFocus)
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip("打开设置")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        tool_box.addWidget(self.layout_button, 1)
        tool_box.addWidget(self.picture_in_picture_button)
        tool_box.addWidget(self.settings_button, 0)
        layout.addWidget(self.tool_row)
        self.set_layout_name(layouts.DEFAULT_LAYOUT)

        self.normal_bar = QWidget()
        normal_layout = QHBoxLayout(self.normal_bar)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(6)
        self.import_button = QPushButton("导入关注")
        self.import_button.setFocusPolicy(Qt.TabFocus)
        self.import_button.setObjectName("IconButton")
        self.import_button.setCursor(Qt.PointingHandCursor)
        self.import_button.setToolTip("从 B 站或支持关注导入的平台账号导入列表（需要先登录）")
        self.import_button.clicked.connect(self.importFollowsClicked.emit)
        self.add_button = QPushButton("+  添加直播间")
        self.add_button.setFocusPolicy(Qt.TabFocus)
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setProperty("addRoom", True)
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.addRoomClicked.emit)
        normal_layout.addWidget(self.import_button)
        normal_layout.addWidget(self.add_button, 1)
        layout.addWidget(self.normal_bar)

        # 竖屏横栏那一行（见 _adopt_bar_row）：左边搜索框/头像排，右边一块
        # 「账号头像 / 布局预设 / 设置」，中间夹着「多选 / 外观 / 刷新」三个小图标。
        # 横屏要拆回竖排，所以先把左栏的原始顺序记下来，_release_bar_row 按它还原。
        self._column_order = [self._head_scroll, self._header_row, self.search,
                              self.status_row, self.scroll, self.batch_bar,
                              self.account_row, self.tool_row, self.normal_bar]
        # 竖屏会把这两个按钮改成撑满 + 竖排，回横屏时要还原原来的策略
        self._tool_button_policies = {
            self.layout_button: self.layout_button.sizePolicy(),
            self.picture_in_picture_button: self.picture_in_picture_button.sizePolicy(),
            self.settings_button: self.settings_button.sizePolicy(),
        }
        self._account_policy = self.account_row.sizePolicy()
        self._bar_row: QWidget | None = None
        self._bar_row_box: QHBoxLayout | None = None
        self._bar_in_use = False
        self.navigation = SidebarNavigation(self, self._outer_layout)
        self.refresh_filter()
        self._sync_count()
        self._sync_appearance_row()

    # ---- 账号 ----
    def _sync_appearance_row(self):
        return self.presentation_control.sync_appearance_row()

    def set_layout_name(self, layout_id: str) -> None:
        """按钮只写「布局预设」，当前用的是哪套放在悬停提示里。"""
        return self.presentation_control.set_layout_name(layout_id)

    def open_layout_picker(self) -> None:
        # 只列当前方向能用的布局：横屏不列竖屏预设（套上去画面会变形）
        return self.presentation_control.open_layout_picker()

    def _on_layout_chosen(self, layout_id: str) -> None:
        return self.presentation_control.on_layout_chosen(layout_id)

    def set_account(self, uname: str, pixmap=None, *, platform="bilibili", uid="") -> None:
        return self.account_control.set_account(uname, pixmap, platform=platform, uid=uid)

    def clear_account(self) -> None:
        # 退出登录后**不隐藏**：这一格要当「登录」按钮继续露着（用户要求）
        return self.account_control.clear_account()

    def set_room_face(self, room_id: str, pixmap) -> None:
        """某个主播的头像下载好了：头排那一张也换掉（横屏走列表，竖屏走头排）。"""
        return self.items_control.set_room_face(room_id, pixmap)

    def account_menu(self) -> QMenu:
        """账号菜单：退出登录；放不进横栏的入口也在这里。

        竖屏横栏只有一行：导入关注 / 添加直播间收进这个菜单；「布局预设 / 设置」
        是并排摆在横栏上的按钮，只有收起时（按钮藏起来）才需要放进菜单。
        单独一个方法是为了能测——exec 一弹就是模态，自检里没法取菜单内容。
        """
        return self.account_control.account_menu(popup_type=AccountPopupMenu, row_type=AccountRow)

    def _open_account_menu(self) -> None:
        return self.account_control.open_account_menu()

    # ---- 竖屏横栏 ----
    def _on_strip_room(self, room_id: str) -> None:
        """点横栏里的头像 = 点列表里那一条（行为和横屏一致）。"""
        return self.items_control.on_strip_room(room_id)

    # ---- 搜索过滤 ----
    def apply_filter(self, text: str) -> None:
        """搜索框一有动静就过滤；批量删除的勾选状态不受影响。"""
        return self.filter_control.apply_filter(text)

    def refresh_filter(self) -> None:
        """按当前搜索词重算谁该露出来（状态刷新、增删、换排序之后都要走一遍）。"""
        return self.filter_control.refresh_filter()

    def _apply_filter_marks(self) -> None:
        """只更新「谁被过滤掉了」，不动位置 —— 由调用方决定什么时候重排。"""
        return self.filter_control.apply_filter_marks()

    def matches(self, item: NavItem, words: list[str], folder_id=None) -> bool:
        """主播名 / 房间号 / 文件夹名，大小写不敏感；多个词必须全匹配。"""
        return self.filter_control.matches(item, words, folder_id)

    def visible_items(self) -> list:
        """当前露在外面的条目（过滤掉的不算）。"""
        return self.filter_control.visible_items()

    def empty_hint_text(self) -> str:
        """列表一条都露不出来时说的话（列表区就摆它一个）。"""
        return self.filter_control.empty_hint_text()

    # ---- 关注文件夹 ----
    def _folder_create_menu(self) -> QMenu:
        return self.folder_control.folder_create_menu()

    def contextMenuEvent(self, event) -> None:
        child = self.childAt(event.pos())
        if child is None or child in (self._head_strip, self._head_scroll.viewport(), self.scroll.viewport()):
            self._folder_create_menu().exec_context(event)
            event.accept()
        else:
            super().contextMenuEvent(event)

    def folder_state(self) -> list[dict]:
        return self.folder_control.folder_state()

    def get_folder(self, folder_id: str):
        return self.folder_control.get_folder(folder_id)

    def default_folder(self):
        return self.folder_control.default_folder()

    def set_default_folder(self, folder_id, *, notify=True):
        return self.folder_control.set_default_folder(folder_id, notify=notify)

    def folder_for(self, room_id: str) -> str:
        return self.folder_control.folder_for(room_id)

    def set_folders(self, folders: list) -> None:
        return self.folder_control.set_folders(folders)

    def create_folder(self, name: str, *, rule=None, sort="custom", icon=None) -> str:
        return self.folder_control.create_folder(name, rule=rule, sort=sort, icon=icon)

    def rename_folder(self, folder_id, name):
        return self.folder_control.rename_folder(folder_id, name)

    def prompt_folder(self, room_ids=None, *, folder_id="") -> None:
        return self.folder_control.prompt_folder(room_ids, folder_id=folder_id,
            create_dialog=create_folder_dialog)

    def delete_folder(self, folder_id: str) -> None:
        return self.folder_control.delete_folder(folder_id)

    def toggle_folder(self, folder_id: str, *, animate=False) -> None:
        return self.folder_control.toggle_folder(folder_id, animate=animate)

    def move_to_folder(self, room_ids: list[str], folder_id: str) -> None:
        return self.folder_control.move_to_folder(room_ids, folder_id)

    def move_folder(self, folder_id: str, direction: int) -> None:
        return self.folder_control.move_folder(folder_id, direction)

    def start_folder_drag(self) -> None:
        """拖动标题时临时收起全部文件夹，结束后恢复原来的展开状态。"""
        return self.folder_control.start_folder_drag()

    def end_folder_drag(self) -> None:
        return self.folder_control.end_folder_drag()

    def _folder_drop_target(self, folder_id: str, global_pos):
        return self.folder_control.folder_drop_target(folder_id, global_pos)

    def hover_folder_drag(self, folder_id: str, global_pos) -> None:
        return self.folder_control.hover_folder_drag(folder_id, global_pos)

    def finish_folder_drag(self, folder_id: str, global_pos) -> None:
        return self.folder_control.finish_folder_drag(folder_id, global_pos)

    def prompt_smart_folder(self, folder_id="") -> None:
        return self.folder_control.prompt_smart_folder(folder_id, dialog_type=SmartFolderDialog)

    def _refresh_folders(self, notify: bool = True, *, animate=False) -> None:
        return self.folder_control.refresh_folders(notify, animate=animate)

    def folder_entries(self, preview_items: list | None = None,
                       dragging_ids: set[str] | None = None) -> list:
        """分组显示，不改变关注、置顶或自定义顺序的保存方式。"""
        return self.folder_control.folder_entries(preview_items, dragging_ids,
            header_type=FollowFolderButton, card_type=SmartFolderCard)

    def _focus_room_list(self) -> None:
        """回车：把焦点从搜索框让给列表，接着就能直接点选 / 拖动。"""
        return self.presentation_control.focus_room_list()

    def refresh_strip(self) -> None:
        """把当前关注列表（连已经下载好的头像）同步到顶部横栏。"""
        return self.items_control.refresh_strip()

    def focus_search(self) -> None:
        """Ctrl+F：展开关注栏并把输入焦点交给搜索框。"""
        return self.presentation_control.focus_search()

    def set_wall_rooms(self, room_ids) -> None:
        """同步画面墙占用状态，供卡片和竖屏头像条显示蓝色标记。"""
        return self.items_control.set_wall_rooms(room_ids)

    def _refresh_wall_marks(self) -> None:
        """按当前的画面墙占用，重设每张卡片的蓝框。

        列表一变（加 / 删 / 重建）就调一次。`_append_item()` 建卡片时读的是**当时**的
        `_wall_room_ids`，而 `set_wall_rooms()` 有个「没变就直接返回」的短路 ——
        两条路径一交叉，卡片就可能留着一个过期的蓝框（用户报的「刚加进关注栏就被
        标成已在画面墙」）。所以列表动过之后统一重设一遍，状态只有一个来源。
        """
        return self.items_control.refresh_wall_marks()

    # ---- 收起 / 展开 ----
    def set_side(self, side: str) -> None:
        """摆放方式：left = 横屏的左栏（默认）；top = 竖屏的顶部横栏。

        竖屏下侧栏变成一条顶部横栏：宽度撑满、搜索框变宽、列表只留一行头像
        （收起时只剩头像，展开时多一行按钮），逻辑和横屏的收起/展开一致。
        """
        return self.presentation_control.set_side(side)

    def _restore_toggle_to_header(self) -> None:
        """把「收起/展开」按钮放回标题行（竖屏时它是摘出来放在横栏右上角的）。"""
        return self.presentation_control.restore_toggle_to_header()

    # ---- 横栏那一行 ----
    def _detach_from_rows(self, widget: QWidget) -> None:
        """把控件从「竖排布局」和横栏那两个容器里都摘出来。"""
        return self.presentation_control.detach_from_rows(widget)

    def _ensure_bar_row(self) -> None:
        """建出横栏的两行容器（只建一次）。

        第一行：logo + 搜索框（收起时换成头像排）+ 多选/外观/刷新小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块（账号 / 布局预设 / 设置 竖排）。
        右侧那一块只占第二行，不侵占第一行的地方（用户要求）；高度就是卡片条
        那一行的高度，三个按钮 + 两条分割线把它正好分完。
        """
        return self.presentation_control.ensure_bar_row()

    def _bar_widgets(self) -> list:
        """竖屏时会被横栏借走的控件（横屏要按原样挂回去）。"""
        return self.presentation_control.bar_widgets()

    def _place_account(self, in_right_block: bool) -> None:
        """账号头像的位置：展开时在整块里排第一，收起时回到第一行最右端。"""
        return self.presentation_control.place_account(in_right_block)

    def _sync_bar_gaps(self) -> None:
        """算两条空白的高度。

        目标是让**最下面的按钮下沿和直播间缩略图的下沿齐平**，所以减的是缩略图
        高度（`NAV_ITEM_HEIGHT`），不是整条卡片行 —— 卡片行还含那 8px 滚动条。
        三个按钮各用横屏那套高度，两条线各 1px，剩下的**均分**给两条空白。
        """
        return self.presentation_control.sync_bar_gaps()

    def _sync_bar_density(self) -> None:
        """竖屏两种卡片密度共用账号、布局、设置的竖排位置。"""
        return self.presentation_control.sync_bar_density()

    def _apply_bar_block_stretches(self) -> None:
        """账号和工具行自己不占 stretch（高度全由按钮 + 空白算出来）。

        每次挪动账号都要重设：`insertWidget` / `removeWidget` 会让布局里其它项
        的下标平移。
        """
        return self.presentation_control.apply_bar_block_stretches()

    def _bar_icons(self) -> tuple:
        """横栏里当小图标用的三个按钮（横屏时它们各有各的文字位置）。"""
        return self.presentation_control.bar_icons()

    def _sync_bar_icons(self) -> None:
        """竖屏工具统一用图标；横屏多选仍为紧凑图标。"""
        return self.presentation_control.sync_bar_icons()

    def _restore_side_children(self) -> None:
        """回左栏：多选图标与外观、刷新一起回状态行。"""
        return self.presentation_control.restore_side_children()

    def _adopt_bar_row(self) -> None:
        """竖屏：把横栏排成两行。

        第一行：logo（圆点 + 「DD监控室CE」）+ 搜索框（收起时换成头排）
        + 多选/外观/刷新三个小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块，那块里「账号 / 布局预设 / 设置」竖排、
        中间两条 1px 分割线 —— 三个按钮 + 两条线正好把卡片条那一行的高度分完，
        不占第一行的地方（用户要求：加起来和左侧展开关注栏同高，别占用别处）。
        """
        return self.presentation_control.adopt_bar_row()

    def _release_bar_row(self) -> None:
        """回左栏：把这两行拆掉，控件按 __init__ 里的原始顺序挂回竖排布局。"""
        return self.presentation_control.release_bar_row()

    def _account_row_should_show(self) -> bool:
        """账号按钮什么时候露出来。

        用户 2026-09-18：**没登录也要露**（显示「登录」，点了弹扫码登录）；
        登录后横屏在侧栏底部、竖屏在横栏右侧那一块 / 收起态头像排旁边。
        """
        return self.presentation_control.account_row_should_show()

    def _sync_selection_controls(self):
        return self.selection_control.sync_selection_controls()

    def _sync_account_row_shape(self) -> None:
        """账号条的形状跟着「横屏/竖屏 + 收起/展开」走。

        竖屏收起时横栏只有 36px 高，账号头像要按头排头像的尺寸（34）挤进去；
        竖屏展开时它在右侧那一块里，高度就用横屏那套（34），多出来的高度留给
        两条空白；其它情况沿用原来的样子。
        """
        return self.presentation_control.sync_account_row_shape()

    def _sync_account_row_width(self) -> None:
        """横栏里的账号条宽度。

        展开时放得下昵称（否则会被挤成「A…」）；收起时它就是一个和头排头像
        一样大的小圆点 —— 不这么算的话它会一直沿用昵称的宽度，变成一条长胶囊。
        横屏时它本来就撑满侧栏，不需要这个限制。
        """
        return self.presentation_control.sync_account_row_width()

    def _sync_top_mode(self) -> None:
        """按 side + collapsed 决定顶部横栏露哪些控件。

        横栏是**一行**：左边搜索框（收起时换成头像排），中间「多选 / 外观 / 刷新」
        三个小图标，右边一块是账号头像 + 布局预设 + 设置 + 展开/收起键；
        下面只剩横向卡片条。头像排在收起时露出来（它就是关注列表）。
        """
        return self.presentation_control.sync_top_mode()

    def _show_logo_title(self) -> None:
        """竖屏横栏只挂紧凑 Logo，不改变原有第一行高度。"""
        return self.presentation_control.show_logo_title()

    def _set_brand_header(self, compact: bool) -> None:
        """横屏显示 Logo + 名称；紧凑横栏只显示 Logo。"""
        return self.presentation_control.set_brand_header(compact)

    def _apply_scroll_axis(self) -> None:
        """竖屏横栏里关注列表是横向卡片条：左右滚，只占一条高度。"""
        return self.presentation_control.apply_scroll_axis()

    def toggle_collapsed(self) -> None:
        return self.presentation_control.toggle_collapsed()

    def _sync_toggle_arrow(self) -> None:
        """收起键的箭头方向：横屏左右、竖屏上下（用户要求）。"""
        return self.presentation_control.sync_toggle_arrow()

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        """一次提交完整布局；保留 animate 参数供既有调用方使用。"""
        return self.presentation_control.set_collapsed(collapsed, animate)

    def _apply_collapsed_controls(self) -> None:
        """在暂停绘制期间对齐控件与条目的最终显示状态。"""
        return self.presentation_control.apply_collapsed_controls()

    def _finish_collapse(self, target: int) -> None:
        """恢复绘制前完成最终几何与可见封面，屏外封面滚入时再补。"""
        return self.presentation_control.finish_collapse(target)

    def _refresh_visible_covers(self) -> None:
        return self.items_control.refresh_visible_covers()

    def _set_pointer_hover(self, item) -> None:
        return self.interaction_control.set_pointer_hover(item)

    def _sync_pointer_hover(self) -> None:
        # Native child windows can omit Enter as well as Leave. Hit-test once
        # for the whole visible list, including rows without a live preview.
        return self.interaction_control.sync_pointer_hover()

    def _prepare_drag_snapshot(self) -> None:
        return self.interaction_control.prepare_drag_snapshot()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._hover_sync_timer.start()
        if not self._drag_snapshot_ready:
            self._drag_snapshot_timer.start(0)

    def hideEvent(self, event) -> None:
        self._drag_snapshot_timer.stop()
        self._hover_sync_timer.stop()
        self._set_pointer_hover(None)
        super().hideEvent(event)

    def set_card_mode(self, enabled: bool) -> None:
        """切换关注列表样式；侧栏收起时只记录选择，展开后再呈现。"""
        return self.items_control.set_card_mode(enabled)

    def set_compact_policy(self, card_mode: bool, auto_compact: bool,
                           compact_threshold: int) -> None:
        """保存用户偏好，并按当前关注数量决定实际使用哪种列表。"""
        return self.items_control.set_compact_policy(card_mode, auto_compact, compact_threshold)

    def set_compact_background(self, enabled: bool) -> None:
        return self.items_control.set_compact_background(enabled)

    def _effective_card_mode(self) -> bool:
        """横竖屏共用关注数量阈值，竖屏改为紧凑横向列表。"""
        return self.items_control.effective_card_mode()

    # ---- 批量选择 ----
    def set_select_mode(self, enabled: bool) -> None:
        return self.selection_control.set_select_mode(enabled)

    def _update_batch_label(self) -> None:
        return self.selection_control.update_batch_label()

    def _emit_delete(self) -> None:
        return self.selection_control.emit_delete()

    def selected_sort_ids(self) -> list[str]:
        return self.selection_control.selected_sort_ids()

    def _sync_sort_selection(self) -> None:
        return self.selection_control.sync_sort_selection()

    def clear_sort_selection(self) -> None:
        return self.selection_control.clear_sort_selection()

    def select_sort_item(self, room_id: str, modifiers) -> None:
        """Ctrl 增减选择，Shift 选一段；普通点击回到单卡片操作。"""
        return self.selection_control.select_sort_item(room_id, modifiers)

    def dragged_room_ids(self, room_id: str) -> list[str]:
        """从选中卡片拖动时带上整组；拖动未选中的卡片则只移动它。"""
        return self.selection_control.dragged_room_ids(room_id)

    def move_sort_selection(self, room_id: str, to_front: bool) -> bool:
        return self.selection_control.move_sort_selection(room_id, to_front)

    # ---- 列表维护 ----
    def select_room(self, room: dict) -> None:
        return self.items_control.select_room(room)

    def _append_item(self, room: dict) -> NavItem:
        return self.items_control.append_item(room, item_type=NavItem)

    def add_room(self, room: dict) -> bool:
        return self.items_control.add_room(room)

    def add_rooms(self, rooms: list[dict]) -> list[dict]:
        return self.items_control.add_rooms(rooms)

    def _reveal_added_rooms(self) -> None:
        """等批量添加与目标文件夹归类结束，只让新卡片从最终落点滑入。"""
        return self.items_control.reveal_added_rooms()

    def remove_room(self, room: dict) -> None:
        return self.items_control.remove_room(room)

    def rooms(self) -> list[dict]:
        return self.items_control.rooms()

    def items(self) -> list[NavItem]:
        return self.items_control.items()

    def drop_index_at(self, global_pos) -> int:
        """全局坐标 -> 列表里的落点下标（给 NavItem 转发拖动用）。"""
        return self.interaction_control.drop_index_at(global_pos)

    def hover_drag(self, room_id: str, global_pos) -> None:
        """拖动过程中：贴近边缘自动滚，并在落点让出一格。"""
        return self.interaction_control.hover_drag(room_id, global_pos)

    def finish_drag(self, room_id: str, global_pos) -> None:
        """松手时结算：鼠标还在列表里就按落点排序，否则只把卡片放回去。"""
        return self.interaction_control.finish_drag(room_id, global_pos)

    # ---- 拖动排序 ----
    def _full_drop_index(self, visible_index: int) -> int:
        """搜索过滤时把屏幕上的落点换算为完整列表下标。"""
        return self.sort_control.full_drop_index(visible_index)

    def _reordered_items(self, room_ids: list[str], drop_index: int) -> list[NavItem]:
        """将选中项作为一组移动；置顶和普通项分别留在自己的区域。"""
        return self.sort_control.reordered_items(room_ids, drop_index)

    def show_drop_indicator(self, room_id: str | None, drop_index: int) -> None:
        """拖动中：选中卡片藏起来，其余卡片让出整组空位。"""
        return self.interaction_control.show_drop_indicator(room_id, drop_index)

    def end_drag(self) -> None:
        """拖动结束（放下或者取消）：所有卡片恢复显示并归位。"""
        return self.interaction_control.end_drag()

    def reorder_item(self, room_id: str, drop_index: int) -> bool:
        return self.sort_control.reorder_item(room_id, drop_index)

    def reorder_items(self, room_ids: list[str], drop_index: int) -> bool:
        """按当前顺序整体移动卡片，并立即保存自定义顺序。"""
        return self.sort_control.reorder_items(room_ids, drop_index)

    # ---- 置顶 ----
    def apply_pins(self, pinned: list) -> None:
        """置顶的先显示在前面（顺序按置顶列表）。"""
        return self.sort_control.apply_pins(pinned)

    # ---- 排序 ----
    def _sync_watch_history_mode(self, *, refresh=False):
        return self.sort_control.sync_watch_history_mode(refresh=refresh)

    def refresh_frequent_order(self):
        return self.sort_control.refresh_frequent_order()

    def add_folder_sort_menu(self, menu, folder) -> None:
        return self.sort_control.add_folder_sort_menu(menu, folder)

    def freeze_current_order(self, folder_id="") -> None:
        """把当前看到的顺序保存为自定义顺序。"""
        return self.sort_control.freeze_current_order(folder_id)

    def _remember_folder_order(self, folder_id: str) -> None:
        return self.sort_control.remember_folder_order(folder_id)

    def set_folder_sort(self, folder_id: str, mode: str, notify=True) -> None:
        return self.sort_control.set_folder_sort(folder_id, mode, notify)

    def set_sort_mode(self, mode: str, notify: bool = True) -> None:
        """切排序方式：自定义 / 开播优先 / 导入顺序。"""
        return self.sort_control.set_sort_mode(mode, notify)

    def set_import_order(self, order: list | None) -> None:
        """导入顺序（配置里存的）；没存过就按当前列表顺序算。"""
        return self.sort_control.set_import_order(order)

    def set_custom_order(self, order: list | None) -> None:
        """自定义顺序（配置里存的）；没存过的房间按当前列表顺序补在后面。"""
        return self.sort_control.set_custom_order(order)

    def resort(self, animate: bool = False, *, duration=150, revealing=(), viewport_only=False) -> None:
        """每个文件夹独立排序，置顶只作用于所在文件夹。"""
        return self.sort_control.resort(animate, duration=duration, revealing=revealing, viewport_only=viewport_only)

    def play_live_alerts(self, items: list) -> None:
        """重排之后再播开播动效。

        调用方要先把 room["live"] 置位、再 resort()，卡片才会先挪到「开播优先」
        该在的位置；动效放到下一个事件循环里播，那时卡片已经就位，水滴和气泡
        才会落在卡片身上，而不是留在它挪走之前的那一行。
        """
        return self.items_control.play_live_alerts(items)

    @staticmethod
    def _play_live_alerts_now(items: list) -> None:
        return SidebarItems.play_live_alerts_now(items)

    def toggle_pin(self, room: dict) -> None:
        return self.sort_control.toggle_pin(room)

    def _sync_count(self) -> None:
        return self.items_control.sync_count()

    def set_refreshing(self, busy: bool) -> None:
        return self.items_control.set_refreshing(busy)
