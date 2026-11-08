"""Follow sidebar coordination and appearance toggle; cards and account rows stay separate."""
import os
import sys

from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QActionGroup, QCursor, QKeySequence, QPainter, QPen, QPixmap, QRegion, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget, QWidgetAction
)

from . import follow_folders, layouts, motion, theme, version as version_module
from .account_widgets import AccountPopupMenu, AccountRow
from .avatar_widgets import RoomStrip
from .dock_feedback import icon_color
from .folder_icons import create_folder_dialog
from .playback_controls import RefreshButton, SidebarToggleButton
from .search import matches_text
from .sidebar_cards import (
    CarouselScroll, FollowFolderButton, NavItem, RoomListBox, SmartFolderCard, SmartFolderDialog
)
from .sidebar_drag import SidebarDrag
from .sidebar_navigation import NavigationButton, RAIL_WIDTH, SidebarNavigation
from .ui.toolbar import BarIconButton
from .watch_history import SORT_TIP, WatchHistory
from .widget_support import (
    BRAND_ASSETS_DIR, NAV_ITEM_GAP, NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT, _repolish
)
from .workspace_controls import WorkspaceControls
from uuid import uuid4


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
        self.workspace_controls.sync_layout()
        self._sync_selection_controls()
        self.appearance_button.setVisible(not self.collapsed)
        if self.side == "left":
            self.status_row.setVisible(not self.collapsed)
            for widget in (self.count_label, self.batch_button, self.notification_button, self.refresh_button):
                widget.setVisible(not self.collapsed)
            self.status_row.layout().setAlignment(self.appearance_button,
                Qt.AlignHCenter if self.collapsed else Qt.AlignRight)
        self.navigation.sync()

    def set_layout_name(self, layout_id: str) -> None:
        """按钮只写「布局预设」，当前用的是哪套放在悬停提示里。"""
        self._layout_id = layout_id
        layout = layouts.BY_ID.get(layout_id) or layouts.BY_ID[layouts.DEFAULT_LAYOUT]
        self.layout_button.setText("布局预设")
        self.layout_button.setToolTip(f"当前布局：{layout['name']}　（点击切换）")

    def open_layout_picker(self) -> None:
        # 只列当前方向能用的布局：横屏不列竖屏预设（套上去画面会变形）
        from .layout_picker import LayoutPicker
        picker = LayoutPicker(self._layout_id, self, portrait=self.side == "top",
                              presets_host=getattr(self, "room_presets_host", None))
        picker.chosen.connect(self._on_layout_chosen)
        picker.resetRequested.connect(self.layoutResetRequested.emit)
        # 收起时「布局预设」按钮是藏起来的，改从头像那个位置弹出来
        source = self.account_row if self.collapsed else self.layout_button
        anchor = source.mapToGlobal(source.rect().topLeft())
        picker.adjustSize()
        screen = (QApplication.screenAt(anchor)
                  or QApplication.screenAt(QCursor.pos())
                  or QApplication.primaryScreen())
        # screenAt 偶尔全落空（窗口还在屏幕外、或显示器刚改过配置），
        # 这时千万别把窗口摆到屏幕外去：退回主屏可用区域，至少还能看见。
        available = screen.availableGeometry() if screen is not None else QRect()
        if not available.isValid():
            primary = QApplication.primaryScreen()
            if primary is not None:
                available = primary.availableGeometry()
        x = anchor.x()
        if self.collapsed:
            x = anchor.x() + source.width() + 6
        y = anchor.y() - picker.height() - 6
        if available.isValid():
            x = max(available.left() + 6,
                    min(x, available.right() - picker.width() - 6))
            if y < available.top() + 6:
                y = anchor.y() + source.height() + 6
            min_y = available.top() + 6
            max_y = available.bottom() - picker.height() - 6
            if max_y < min_y:
                y = min_y
            else:
                y = max(min_y, min(y, max_y))
        else:
            # 连主屏都问不到时，至少把它压进屏幕左上角能看见的范围，
            # 别让 x 也跟着锚点跑到屏幕外去
            x = max(6, min(x, max(6, 1200 - picker.width() - 6)))
            y = max(6, y)
        picker.move(x, y)
        picker.show()
        self._picker = picker

    def _on_layout_chosen(self, layout_id: str) -> None:
        self.set_layout_name(layout_id)
        self.layoutChosen.emit(layout_id)

    def set_account(self, uname: str, pixmap=None, *, platform="bilibili", uid="") -> None:
        self.account_row.set_account(uname, pixmap, platform=platform, uid=uid)
        self._sync_account_row_shape()
        self.account_row.setVisible(self._account_row_should_show())
        self._sync_account_row_width()
        self.refresh_strip()

    def clear_account(self) -> None:
        # 退出登录后**不隐藏**：这一格要当「登录」按钮继续露着（用户要求）
        self.account_row.set_account("")
        self.account_row.setVisible(self._account_row_should_show())
        self._sync_account_row_shape()
        self._sync_account_row_width()

    def set_room_face(self, room_id: str, pixmap) -> None:
        """某个主播的头像下载好了：头排那一张也换掉（横屏走列表，竖屏走头排）。"""
        strip = getattr(self, "_head_strip", None)
        if strip is not None:
            strip.set_room_face(room_id, pixmap)

    def account_menu(self) -> QMenu:
        """账号菜单：退出登录；放不进横栏的入口也在这里。

        竖屏横栏只有一行：导入关注 / 添加直播间收进这个菜单；「布局预设 / 设置」
        是并排摆在横栏上的按钮，只有收起时（按钮藏起来）才需要放进菜单。
        单独一个方法是为了能测——exec 一弹就是模态，自检里没法取菜单内容。
        """
        menu = AccountPopupMenu(self)
        menu.setObjectName("AccountPopup")
        menu.setStyleSheet(f"""
            QMenu#AccountPopup {{ background: transparent; border: none; padding: 0; }}
            QMenu#AccountPopup::item {{ background: {theme.CONTENT}; border: 1px solid {theme.BORDER};
                           border-radius: 17px; padding: 8px 12px; margin: 3px 0; }}
            QMenu#AccountPopup::item:selected {{ background: {theme.CONTENT_HOVER}; }}
            QMenu#AccountPopup::separator {{ height: 6px; margin: 0; background: transparent; }}
        """)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        popup_width = self.account_row.width() if not self.collapsed else 240
        menu.setFixedWidth(popup_width)
        account_actions = []
        if not self.account_row.uname:
            # 未登录时这一格就是「登录」按钮（用户要求：没登录也要放出来）
            menu.addAction("登录")
            menu.addSeparator()
        else:
            action = QWidgetAction(menu)
            action.setText("登录其他平台" if getattr(self, "can_login_other", True)
                           else "所有平台均已登录")
            button = QPushButton(action.text(), menu)
            button.setCursor(Qt.PointingHandCursor)
            button.setObjectName("AccountPopupButton")
            button.setFixedSize(popup_width, self.account_row.height() if not self.collapsed else 34)
            button.setStyleSheet(f"""QPushButton {{ padding: 0; min-height: 32px; text-align: center;
                background: {theme.CONTENT}; border: 1px solid {theme.BORDER};
                border-radius: {theme.CONTROL_HEIGHT // 2}px; }}
                QPushButton:hover {{ background: {theme.CONTENT_HOVER}; border-color: {theme.ACCENT}; }}
                QPushButton:pressed {{ background: {theme.ACCENT_SOFT}; }}""")
            def activate(_checked=False):
                menu.close()
                # 等 QMenu.exec 和当前鼠标回调退出，再构造模态登录窗口。
                # 否则窗口/浏览器初始化会重入尚未收尾的原生弹出菜单。
                QTimer.singleShot(0, self, self.loginRequested.emit)
            button.clicked.connect(activate)
            action.setDefaultWidget(button)
            menu.addAction(action)
            menu.addSeparator()
            for kind, account in reversed(getattr(self, "logged_accounts", [])):
                if kind == self.account_row.platform:
                    continue
                action = QWidgetAction(menu)
                item = QWidget(menu)
                item.setObjectName("AccountPopupItem")
                item.setStyleSheet("#AccountPopupItem { background: transparent; }")
                layout = QHBoxLayout(item)
                layout.setContentsMargins(0, 3, 0, 3)
                row = AccountRow(item, allow_logout=True)
                item.setFixedSize(popup_width, self.account_row.height() + 6 if not self.collapsed else 40)
                row.setFixedHeight(self.account_row.height() if not self.collapsed else 34)
                row.set_account(account.get("uname") or str(account.get("uid") or "已登录"),
                                account.get("_pixmap"), platform=kind, uid=account.get("uid"))
                row.name.setAlignment(Qt.AlignCenter)
                row.account_id.setAlignment(Qt.AlignCenter)
                if account.get("_login_expired"):
                    row.account_id.setText("登录已失效 · 请重新登录")
                    row.account_id.setStyleSheet(f"color: {theme.PINK};")
                    row.setToolTip("登录已失效，请通过上方登录按钮重新登录")
                row.arrow.hide()
                layout.addWidget(row, 1)
                button = row.logout_button
                button.setProperty("platform", kind)
                def logout(_checked=False, k=kind):
                    menu.close()
                    self.platformLogoutRequested.emit(k)
                row.logoutClicked.connect(logout)
                action.setDefaultWidget(item)
                menu.addAction(action)
                account_actions.append(action)
        if self.side == "top":
            menu.addSeparator()
            menu.addAction("导入关注")
            menu.addAction("+ 添加直播间")
            if self.collapsed:
                menu.addSeparator()
                menu.addAction("布局预设")
                menu.addAction('画中画')
                menu.addAction("设置")
        elif self.collapsed:
            # 横屏收起后「布局预设 / 设置」那行按钮跟着藏起来了，只剩这个头像；
            # 点头像就把它们以菜单形式放出来，不用先展开侧栏。
            menu.addSeparator()
            menu.addAction("布局预设")
            menu.addAction('画中画')
            menu.addAction("设置")
        for action in account_actions:
            menu.removeAction(action)
            menu.addAction(action)
        return menu

    def _open_account_menu(self) -> None:
        if not self.account_row.uname and not self.collapsed:
            self.loginRequested.emit()
            return
        menu = self.account_menu()
        texts = [action.text() for action in menu.actions() if action.text()]
        size = menu.sizeHint()
        if self.side == "top":
            # 竖屏：贴着头排右侧那个账号头像弹（展开/收起都在）
            anchor = QRect(self.account_row.mapToGlobal(
                self.account_row.rect().topLeft()), self.account_row.size())
            position = QPoint(anchor.left(), anchor.bottom() + 6)
        elif self.collapsed:
            # 横屏收起：只剩头像，菜单贴着头像右侧展开
            anchor = self.account_row.mapToGlobal(self.account_row.rect().topRight())
            position = QPoint(anchor.x() + 6, anchor.y() - size.height() - 6)
        else:
            # 账号栏在最底部，菜单往上弹、右对齐整行
            anchor = self.account_row.mapToGlobal(self.account_row.rect().topRight())
            position = QPoint(anchor.x() - size.width(), anchor.y() - size.height() - 6)
        chosen = menu.exec(position)
        if chosen is None:
            return
        label = chosen.text()
        if label in ("退出登录", "登录", "登录其他平台", "所有平台均已登录"):
            if label != "退出登录":
                self.loginRequested.emit()
            else:
                self.logoutRequested.emit()
        elif label == "布局预设":
            self.open_layout_picker()
        elif label == '画中画':
            self.pictureInPictureRequested.emit()
        elif label == "设置":
            self.settingsRequested.emit()
        elif label == "导入关注":
            self.importFollowsClicked.emit()
        elif label == "+ 添加直播间":
            self.addRoomClicked.emit()

    # ---- 竖屏横栏 ----
    def _on_strip_room(self, room_id: str) -> None:
        """点横栏里的头像 = 点列表里那一条（行为和横屏一致）。"""
        item = next((entry for entry in self._items
                     if str(entry.room.get("room_id")) == str(room_id)), None)
        if item is not None:
            self.roomSelected.emit(item.room)

    # ---- 搜索过滤 ----
    def apply_filter(self, text: str) -> None:
        """搜索框一有动静就过滤；批量删除的勾选状态不受影响。"""
        wanted = (text or "").strip().lower()
        if wanted == self.filter_text:
            return
        self.clear_sort_selection()
        self.filter_text = wanted
        self.refresh_filter()

    def refresh_filter(self) -> None:
        """按当前搜索词重算谁该露出来（状态刷新、增删、换排序之后都要走一遍）。"""
        self._apply_filter_marks()
        self.list_box.relayout(animate=False)
        self.refresh_strip()
        self._sync_count()

    def _apply_filter_marks(self) -> None:
        """只更新「谁被过滤掉了」，不动位置 —— 由调用方决定什么时候重排。"""
        words = self.filter_text.split()
        self._folder_assignments = follow_folders.assign_folders(
            self.rooms(), self.folders, self._folder_pending)
        for item in self._items:
            folder = self.get_folder(self.folder_for(str(item.room.get("room_id"))))
            folded = folder and folder["collapsed"] and (
                not words or folder["id"] in self._folders_folded_by_drag)
            item.set_filtered_out(bool(folded) or not self.matches(item, words))
            if folded:
                self._sort_selected_ids.discard(str(item.room.get("room_id")))
                item.set_sort_selected(False)
                item.check.setChecked(False)

    def matches(self, item: NavItem, words: list[str], folder_id=None) -> bool:
        """主播名 / 房间号 / 文件夹名，大小写不敏感；多个词必须全匹配。"""
        if self.live_only and not item.room.get('live'):
            return False
        if not words:
            return True
        room = item.room
        haystack = " ".join(str(room.get(key) or "")
                            for key in ("uname", "room_id", "display_room_id")).lower()
        folder_id = folder_id or self.folder_for(str(room.get("room_id")))
        haystack += " " + next((folder["name"].lower() for folder in self.folders
                                if folder["id"] == folder_id), "")
        return all(matches_text(haystack, word) for word in words)

    def visible_items(self) -> list:
        """当前露在外面的条目（过滤掉的不算）。"""
        items = [item for item in self._items if not item.filtered_out]
        return [item for folder in self.folders for item in items
                if self.folder_for(str(item.room.get("room_id"))) == folder["id"]]

    def empty_hint_text(self) -> str:
        """列表一条都露不出来时说的话（列表区就摆它一个）。"""
        if self.filter_text:
            return f"没有匹配「{self.filter_text}」的直播间"
        if self.live_only:
            return '当前没有正在直播的关注'
        return "还没有关注任何直播间"

    # ---- 关注文件夹 ----
    def _folder_create_menu(self) -> QMenu:
        menu = motion.AnimatedMenu(self)
        menu.addAction("新建文件夹…").triggered.connect(lambda: self.prompt_folder())
        menu.addAction("新建智能文件夹…").triggered.connect(lambda: self.prompt_smart_folder())
        return menu

    def contextMenuEvent(self, event) -> None:
        child = self.childAt(event.pos())
        if child is None or child in (self._head_strip, self._head_scroll.viewport(), self.scroll.viewport()):
            self._folder_create_menu().exec_context(event)
            event.accept()
        else:
            super().contextMenuEvent(event)

    def folder_state(self) -> list[dict]:
        return follow_folders.folder_state(self.folders)

    def get_folder(self, folder_id: str):
        return next((folder for folder in self.folders if folder["id"] == folder_id), None)

    def default_folder(self):
        return follow_folders.default_folder(self.folders)

    def set_default_folder(self, folder_id, *, notify=True):
        target = self.get_folder(folder_id)
        if target is None or target["type"] != "normal":
            return
        previous = self.default_folder()
        assigned = {rid for folder in self.folders if folder["type"] != "smart"
                    for rid in folder["rooms"]}
        previous["rooms"].extend(str(room["room_id"]) for room in self.rooms()
                                 if str(room["room_id"]) not in assigned)
        previous["type"] = "normal"
        target["type"] = "unclassified"
        self._refresh_folders(notify=notify)

    def folder_for(self, room_id: str) -> str:
        return self._folder_assignments.get(room_id) or next(
            (folder["id"] for folder in self.folders if room_id in folder["rooms"]), "")

    def set_folders(self, folders: list) -> None:
        self.folders = follow_folders.normalize_folders(folders, self.sort_mode)
        self._refresh_folders(notify=False)

    def create_folder(self, name: str, *, rule=None, sort="custom", icon=None) -> str:
        name = name.strip()
        if not name or any(folder["name"] == name for folder in self.folders):
            return ""
        folder_id = uuid4().hex
        folder = {"id": folder_id, "name": name, "type": "smart" if rule is not None else "normal",
                  "collapsed": False, "rooms": [], "sort": sort}
        if rule is not None:
            folder["rule"] = rule
        if icon is not None:
            folder['icon'] = icon
        index = self.folders.index(self.default_folder())
        if rule is not None:
            folder["rule"] = dict(rule, sources=rule.get("sources", [self.default_folder()["id"]]))
        self.folders.insert(index, follow_folders.normalize_folders([folder])[0])
        self._refresh_folders()
        return folder_id

    def rename_folder(self, folder_id, name):
        folder = self.get_folder(folder_id)
        name = name.strip()
        if not name or any(item['name'] == name and item['id'] != folder_id for item in self.folders):
            return
        if name != folder['name']:
            folder['name'] = name
            self._refresh_folders()

    def prompt_folder(self, room_ids=None, *, folder_id="") -> None:
        folder = next((item for item in self.folders if item["id"] == folder_id), None)
        if folder is None:
            folder_id, _name = create_folder_dialog(self, self.create_folder,
                                                    (item['name'] for item in self.folders))
            if folder_id and room_ids:
                self.move_to_folder(room_ids, folder_id)
            return
        name, accepted = QInputDialog.getText(
            self, "重命名文件夹", "文件夹名称：", text=folder["name"])
        if not accepted or not name.strip():
            return
        name = name.strip()
        if any(item["name"] == name and item["id"] != folder_id for item in self.folders):
            return
        folder["name"] = name
        self._refresh_folders()

    def delete_folder(self, folder_id: str) -> None:
        if folder_id == self.default_folder()["id"]:
            replacement = next((folder for folder in self.folders if folder["type"] == "normal"), None)
            if replacement is None:
                return
            self.set_default_folder(replacement["id"], notify=False)
        self.folders = [folder for folder in self.folders if folder["id"] != folder_id]
        self._refresh_folders()

    def toggle_folder(self, folder_id: str, *, animate=False) -> None:
        for folder in self.folders:
            if folder["id"] == folder_id:
                self._folders_folded_by_drag.discard(folder_id)
                folder["collapsed"] = not folder["collapsed"]
                self._refresh_folders(animate=animate and motion.enabled())
                return

    def move_to_folder(self, room_ids: list[str], folder_id: str) -> None:
        target = self.get_folder(folder_id or self.default_folder()["id"])
        if target is None or target["type"] == "smart":
            return
        known = {str(item.room.get("room_id")) for item in self._items}
        moving = list(dict.fromkeys(key for key in room_ids if key in known))
        for folder in self.folders:
            folder["rooms"] = [key for key in folder["rooms"] if key not in moving]
        if target["type"] == "normal":
            target["rooms"].extend(moving)
            self._folder_pending.difference_update(moving)
        else:
            self._folder_pending.update(moving)
        self._refresh_folders()

    def move_folder(self, folder_id: str, direction: int) -> None:
        folder = self.get_folder(folder_id)
        if folder is None:
            return
        index = self.folders.index(folder)
        target = index + direction
        if 0 <= target < len(self.folders):
            self.folders[index], self.folders[target] = self.folders[target], self.folders[index]
            self._refresh_folders()

    def start_folder_drag(self) -> None:
        """拖动标题时临时收起全部文件夹，结束后恢复原来的展开状态。"""
        self._folder_drag_previous = {folder["id"]: folder["collapsed"] for folder in self.folders}
        self._folders_folded_by_drag.update(folder["id"] for folder in self.folders)
        for folder in self.folders:
            folder["collapsed"] = True
        self._refresh_folders(notify=False)

    def end_folder_drag(self) -> None:
        self.list_box.set_scroll_dir(0)
        self.list_box.folder_drop_indicator.hide()
        for folder in self.folders:
            if folder["id"] in self._folder_drag_previous:
                folder["collapsed"] = self._folder_drag_previous[folder["id"]]
        self._folder_drag_previous.clear()
        self._folders_folded_by_drag.clear()
        self._refresh_folders()

    def _folder_drop_target(self, folder_id: str, global_pos):
        box = self.list_box
        local = box.mapFromGlobal(global_pos)
        if self.get_folder(folder_id) is None or not box.rect().contains(local):
            return None
        remaining = [folder for folder in self.folders if folder["id"] != folder_id]
        headers = [(index, self._folder_buttons[folder["id"]]) for index, folder in enumerate(remaining)
                   if not self._folder_buttons[folder["id"]].isHidden()]
        along = local.x() if box.horizontal else local.y()
        for index, header in headers:
            start = header.x() if box.horizontal else header.y()
            length = header.width() if box.horizontal else header.height()
            if along < start + length / 2:
                return index, max(0, start - NAV_ITEM_GAP)
        if headers:
            index, header = headers[-1]
            end = header.geometry().right() if box.horizontal else header.geometry().bottom()
            return index + 1, end + 1
        return None

    def hover_folder_drag(self, folder_id: str, global_pos) -> None:
        self.list_box.auto_scroll(global_pos)
        target = self._folder_drop_target(folder_id, global_pos)
        indicator = self.list_box.folder_drop_indicator
        if target is None:
            indicator.hide()
            return
        _, along = target
        if self.list_box.horizontal:
            indicator.setGeometry(along, 0, 2, self.list_box.item_size()[1])
        else:
            indicator.setGeometry(0, along, self.list_box.width(), 2)
        indicator.show()
        indicator.raise_()

    def finish_folder_drag(self, folder_id: str, global_pos) -> None:
        self.list_box.set_scroll_dir(0)
        self.list_box.folder_drop_indicator.hide()
        target = self._folder_drop_target(folder_id, global_pos)
        if target is None:
            return
        index, _ = target
        folder = self.get_folder(folder_id)
        if self.folders.index(folder) != index:
            self.folders.remove(folder)
            self.folders.insert(index, folder)
            self._refresh_folders(notify=not bool(self._folder_drag_previous))

    def prompt_smart_folder(self, folder_id="") -> None:
        folder = self.get_folder(folder_id)
        dialog = SmartFolderDialog(self, folder)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.values()
        if any(item["name"] == data["name"] and item["id"] != folder_id for item in self.folders):
            return
        if folder:
            folder.update(data)
            self._refresh_folders()
        else:
            self.create_folder(**data)

    def _refresh_folders(self, notify: bool = True, *, animate=False) -> None:
        self._sync_watch_history_mode()
        revealing = {item for item in self._items if item.filtered_out} if animate else ()
        ids = {folder["id"] for folder in self.folders}
        self._folders_folded_by_drag.intersection_update(ids)
        for folder_id in list(self._folder_buttons):
            if folder_id not in ids:
                button = self._folder_buttons.pop(folder_id)
                button.hide()
                button.deleteLater()
        self.clear_sort_selection()
        self.resort(animate=animate, duration=280 if animate else 150, revealing=revealing,
                    viewport_only=animate)
        for item in self._items:
            if item.filtered_out:
                item.check.setChecked(False)
        self._update_batch_label()
        self._sync_sort_selection()
        if notify:
            self.foldersChanged.emit()

    def folder_entries(self, preview_items: list | None = None,
                       dragging_ids: set[str] | None = None) -> list:
        """分组显示，不改变关注、置顶或自定义顺序的保存方式。"""
        entries = []
        visible = self.visible_items() if preview_items is None else [
            item for item in preview_items if not item.filtered_out]
        active_copies = set()
        for folder in self.folders:
            button = self._folder_buttons.get(folder["id"])
            if button is None:
                button = FollowFolderButton(self, folder["id"])
                self._folder_buttons[folder["id"]] = button
            members = [item for item in visible
                       if self.folder_for(str(item.room.get("room_id"))) == folder["id"]]
            count = sum(fid == folder["id"] for fid in self._folder_assignments.values())
            copies = folder["type"] == "smart" and folder["rule"].get("display") == "copy"
            if copies:
                matched = follow_folders.smart_members(self.rooms(), self.folders, folder, self._folder_pending)
                count = len(matched)
                members = [item for item in self._items if str(item.room["room_id"]) in matched
                           and self.matches(item, self.filter_text.split(), folder["id"])]
                order = self.import_order if folder["sort"] == "imported" else self.custom_order
                positions = {rid: i for i, rid in enumerate(order)}
                pin_positions = {rid: i for i, rid in enumerate(self.pinned)}
                def copy_key(item):
                    index = positions.get(str(item.room["room_id"]), len(positions))
                    if folder["sort"] == "frequent":
                        rid = str(item.room["room_id"])
                        return ((False, pin_positions.get(rid, index), 0, 0) if item.is_pinned else
                                (True, not bool(item.room.get("live")),
                                 -self._frequent_scores.get(rid, 0), index))
                    value = (str(item.room.get("uname") or "").casefold() if folder["sort"] == "name"
                             else bool(item.room.get("live")) != (folder["sort"] == "live")
                             if folder["sort"] in ("live", "offline") else index)
                    return (not item.is_pinned, value, index)
                members.sort(key=copy_key)
                folded = folder["collapsed"] and (not self.filter_text or folder["id"] in self._folders_folded_by_drag)
                displayed = []
                if not folded:
                    for item in members:
                        key = (folder["id"], str(item.room["room_id"]))
                        active_copies.add(key)
                        if key not in self._smart_cards:
                            self._smart_cards[key] = SmartFolderCard(item, self.list_box)
                        displayed.append(self._smart_cards[key])
                members = displayed
            arrow = "▸" if folder["collapsed"] and (
                not self.filter_text or folder["id"] in self._folders_folded_by_drag) else "▾"
            title = f"{arrow} {folder['name']} · {count}"
            button.setToolTip(title + ("\n智能文件夹：拖动标题排序；右键编辑规则和排序" if folder["type"] == "smart"
                                      else "\n点击展开/收起；拖动标题排序；拖入卡片归类；右键管理"))
            width, height = self.list_box.item_size()
            label_width = height if self.side == "top" else width
            button.setToolButtonStyle(Qt.ToolButtonIconOnly if self.collapsed and self.side == "left"
                                      else Qt.ToolButtonTextBesideIcon)
            button.setText(button.fontMetrics().elidedText(title, Qt.ElideRight, max(12, label_width - 44)))
            search_match = bool(members) if copies else any(
                self.folder_for(str(item.room.get("room_id"))) == folder["id"]
                and self.matches(item, self.filter_text.split()) for item in self._items)
            button.setVisible(not self.filter_text or search_match)
            if not button.isHidden():
                entries.append(button)
                entries.extend(None if dragging_ids and str(item.room.get("room_id")) in dragging_ids
                               else item for item in members)
        originals = set(self._items)
        for key, card in list(self._smart_cards.items()):
            if key not in active_copies:
                card.hide()
            if card.original not in originals or not self.get_folder(key[0]):
                self._smart_cards.pop(key)
                card.deleteLater()
        return entries

    def _focus_room_list(self) -> None:
        """回车：把焦点从搜索框让给列表，接着就能直接点选 / 拖动。"""
        self.scroll.setFocus()

    def refresh_strip(self) -> None:
        """把当前关注列表（连已经下载好的头像）同步到顶部横栏。"""
        strip = getattr(self, "_head_strip", None)
        if strip is None:
            return
        rooms = []
        faces = {}
        for item in self.visible_items():          # 过滤时头像排也跟着缩
            room = dict(item.room)
            rooms.append(room)
            pixmap = item.thumb.face_pixmap()
            if pixmap is not None:
                faces[str(room.get("room_id") or "")] = pixmap
        strip.set_rooms(rooms, faces, self._wall_room_ids)

    def focus_search(self) -> None:
        """Ctrl+F：展开关注栏并把输入焦点交给搜索框。"""
        if self.collapsed:
            self.set_collapsed(False, animate=False)
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def set_wall_rooms(self, room_ids) -> None:
        """同步画面墙占用状态，供卡片和竖屏头像条显示蓝色标记。"""
        ids = {str(room_id) for room_id in room_ids if str(room_id)}
        if ids == self._wall_room_ids:
            return
        self._wall_room_ids = ids
        self._refresh_wall_marks()
        self.refresh_strip()

    def _refresh_wall_marks(self) -> None:
        """按当前的画面墙占用，重设每张卡片的蓝框。

        列表一变（加 / 删 / 重建）就调一次。`_append_item()` 建卡片时读的是**当时**的
        `_wall_room_ids`，而 `set_wall_rooms()` 有个「没变就直接返回」的短路 ——
        两条路径一交叉，卡片就可能留着一个过期的蓝框（用户报的「刚加进关注栏就被
        标成已在画面墙」）。所以列表动过之后统一重设一遍，状态只有一个来源。
        """
        for item in self._items:
            item.set_on_wall(str(item.room.get("room_id") or "") in self._wall_room_ids)

    # ---- 收起 / 展开 ----
    def set_side(self, side: str) -> None:
        """摆放方式：left = 横屏的左栏（默认）；top = 竖屏的顶部横栏。

        竖屏下侧栏变成一条顶部横栏：宽度撑满、搜索框变宽、列表只留一行头像
        （收起时只剩头像，展开时多一行按钮），逻辑和横屏的收起/展开一致。
        """
        side = "top" if side == "top" else "left"
        # 无论走哪个分支，先把约束解掉：
        # - 滚动区的高度上限（竖屏那条「只占一条」的限制留着，切回左栏就只剩一条）
        # - 侧栏的竖直策略（竖屏时被压成一条，切回左栏必须重新撑满）
        self.scroll.setMinimumHeight(0)
        self.scroll.setMaximumHeight(16_777_215)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16_777_215)
        self.list_box._clamp_vertical_scroll()
        if side == self.side:
            # 已经是这个摆放方式：不重复设置宽度，但仍要同步一次可见性 ——
            # 调用方（换排布 / 刚设过收起状态）可能正等着头像排露出来
            if side == "top":
                self._sync_top_mode()
            else:
                # 竖向时务必把滚动区的高度上限解掉：竖屏那条 130px 的限制留着，
                # 左栏就只剩一条（用户看到的就是这个）
                self._apply_scroll_axis()
            return
        if side == 'top':
            self.navigation.release()
        self.side = side
        self.set_card_mode(self._effective_card_mode())
        horizontal = side == "top"
        for item in self._items:
            item.set_portrait_strip(horizontal and not self.card_mode)
        if not horizontal:
            # 切回左栏：横栏那一行先拆掉（控件按原顺序挂回竖排），头像排收掉
            # （它只服务于顶部横栏），展开键还回标题行，并把「顶部横栏收起时
            # 藏起来的控件」逐个恢复 —— 只显示标题行容器是不够的，
            # 搜索/列表/按钮行会一直是隐藏状态，左栏就只剩一小条。
            self._release_bar_row()
            self._head_scroll.setVisible(False)      # 头像排只服务于顶部横栏
            header = getattr(self, "_header_row", None)
            if header is not None:
                header.setVisible(True)
            for index in range(self.title_box.count()):
                holder = self.title_box.itemAt(index).widget()
                if holder is not None:
                    holder.setVisible(True)
            self._set_brand_header(compact=False)
            self.batch_button.setVisible(True)
            for widget, visible in ((self.search, True), (self.status_row, True),
                                    (self.scroll, True),
                                    (self.normal_bar, not self.select_mode),
                                    (self.batch_bar, self.select_mode),
                                    (self.tool_row, True)):
                widget.setVisible(visible)
            self.settings_button.setVisible(True)    # 竖屏时它收进「⋯」里了
            # 横栏里的工具回到状态行，多选仍保留为状态行的图标。
            self._restore_side_children()
            self.account_row.setVisible(self._account_row_should_show())
            self._restore_toggle_to_header()
            # 竖屏那套滚动轴状态必须在这里还原：横排时 horizontal_only=True、
            # 竖条常关、横条 AsNeeded，不回滚的话回横屏后竖向滚动条一直藏着，
            # 滚轮还会被 CarouselScroll 当成横滚吞掉 —— 左栏整列就滚不动了。
            self._apply_scroll_axis()
        self.setFixedWidth(theme.SIDEBAR_WIDTH + RAIL_WIDTH)
        if horizontal:
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._layout.setSpacing(6)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)
        else:
            self._layout.setContentsMargins(12 if not self.collapsed else 8, 14,
                                            12 if not self.collapsed else 8, 12)
            self._layout.setSpacing(10)
            self.setFixedWidth(
                (theme.SIDEBAR_RAIL_WIDTH if self.collapsed else theme.SIDEBAR_WIDTH) + RAIL_WIDTH)
        self._sync_top_mode()
        self.list_box.relayout(animate=False)

    def _restore_toggle_to_header(self) -> None:
        """把「收起/展开」按钮放回标题行（竖屏时它是摘出来放在横栏右上角的）。"""
        toggle = getattr(self, "toggle_button", None)
        header = getattr(self, "_header_row", None)
        if toggle is None or header is None:
            return
        self._detach_from_rows(toggle)
        toggle.setObjectName("SidebarToggle")      # 换回标题行那套样式
        toggle.setFixedSize(24, 24)
        toggle.setParent(header)
        header.layout().addWidget(toggle, 0, Qt.AlignTop)
        toggle.setVisible(True)
        _repolish(toggle)

    # ---- 横栏那一行 ----
    def _detach_from_rows(self, widget: QWidget) -> None:
        """把控件从「竖排布局」和横栏那两个容器里都摘出来。"""
        for holder in (self._layout, self._bar_row_box, getattr(self, '_bar_row2_box', None),
                       getattr(self, '_bar_right_box', None)):
            if holder is not None:
                holder.removeWidget(widget)

    def _ensure_bar_row(self) -> None:
        """建出横栏的两行容器（只建一次）。

        第一行：logo + 搜索框（收起时换成头像排）+ 多选/外观/刷新小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块（账号 / 布局预设 / 设置 竖排）。
        右侧那一块只占第二行，不侵占第一行的地方（用户要求）；高度就是卡片条
        那一行的高度，三个按钮 + 两条分割线把它正好分完。
        """
        if self._bar_row is not None:
            return
        self._bar_row = QWidget(self)
        box = QHBoxLayout(self._bar_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self._bar_row_box = box
        self._bar_row2 = QWidget(self)
        box2 = QHBoxLayout(self._bar_row2)
        box2.setContentsMargins(0, 0, 0, 0)
        box2.setSpacing(6)
        self._bar_row2_box = box2
        self._bar_right = QWidget(self._bar_row2)
        right = QVBoxLayout(self._bar_right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self._bar_right_box = right
        #: 三个按钮之间的分割线（用户要求「适当给予分割」）
        self._bar_divider_label = QFrame(self._bar_right)
        self._bar_divider_tool = QFrame(self._bar_right)
        for divider in (self._bar_divider_label, self._bar_divider_tool):
            divider.setObjectName("BarDivider")
            divider.setFixedHeight(1)
            divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        #: 分割线两侧的空白：高度由 _sync_bar_gaps() 按缩略图高度算出来
        self._bar_gaps = tuple(QWidget(self._bar_right) for _ in range(4))
        for gap in self._bar_gaps:
            gap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 末尾留一条 stretch：三个按钮的总高只到缩略图下沿，剩下的高度（滚动条
        # 那条）不参与分配，这一块本身仍然撑满卡片条那一行
        right.addStretch(1)

    def _bar_widgets(self) -> list:
        """竖屏时会被横栏借走的控件（横屏要按原样挂回去）。"""
        return [self.search, self._head_scroll, self.batch_button, self.notification_button, self.clear_wall_button,
                self.appearance_button, self.refresh_button, self.account_row, self.tool_row,
                self.batch_bar, self.toggle_button]

    def _place_account(self, in_right_block: bool) -> None:
        """账号头像的位置：展开时在整块里排第一，收起时回到第一行最右端。"""
        wanted = self._bar_right if in_right_block else self._bar_row
        if self.account_row.parentWidget() is wanted:
            return
        self._detach_from_rows(self.account_row)
        self.account_row.setParent(wanted)
        if in_right_block:
            self._bar_right_box.insertWidget(0, self.account_row, 1)
            self._apply_bar_block_stretches()
        else:
            self._bar_row_box.insertWidget(self._bar_row_box.count() - 1,
                                           self.account_row)

    def _sync_bar_gaps(self) -> None:
        """算两条空白的高度。

        目标是让**最下面的按钮下沿和直播间缩略图的下沿齐平**，所以减的是缩略图
        高度（`NAV_ITEM_HEIGHT`），不是整条卡片行 —— 卡片行还含那 8px 滚动条。
        三个按钮各用横屏那套高度，两条线各 1px，剩下的**均分**给两条空白。
        """
        target = NAV_ITEM_HEIGHT
        buttons = (theme.CONTROL_HEIGHT + self.layout_button.sizeHint().height()
                   + self.picture_in_picture_button.sizeHint().height()
                   + self.settings_button.sizeHint().height())
        slack = max(0, target - buttons - 2)       # 四条空白加起来的高度
        # 每条空白 = 线上那段 + 1px 线 + 线下那段，所以先把那 1px 加回来再对半分
        per_gap, extra = divmod(slack + 2, 2)
        blank, blank_extra = divmod(max(0, per_gap - 1), 2)
        for index, gap in enumerate(self._bar_gaps):
            # 每条空白里「线上 / 线下」两段：先按对半分，余数给上面那段
            height = blank + (blank_extra if index % 2 == 0 else 0)
            if index >= 2:
                height += extra                    # 除不尽的那 1px 给第二条空白
            gap.setFixedHeight(height)

    def _sync_bar_density(self) -> None:
        """竖屏两种卡片密度共用账号、布局、设置的竖排位置。"""
        self._bar_right_box.setDirection(QBoxLayout.TopToBottom)
        self._bar_right_box.setSpacing(0)
        tool_box = self.tool_row.layout()
        tool_box.setDirection(QBoxLayout.TopToBottom)
        tool_box.setSpacing(0)
        for widget in (*self._bar_gaps, self._bar_divider_label, self._bar_divider_tool):
            widget.setVisible(True)
        self.layout_button.setText("布局预设")
        for button in (self.layout_button, self.picture_in_picture_button, self.settings_button):
            button.setMaximumWidth(16_777_215)
        self.tool_row.setMinimumWidth(0)
        self.tool_row.setMaximumWidth(16_777_215)
        self._sync_bar_gaps()

    def _apply_bar_block_stretches(self) -> None:
        """账号和工具行自己不占 stretch（高度全由按钮 + 空白算出来）。

        每次挪动账号都要重设：`insertWidget` / `removeWidget` 会让布局里其它项
        的下标平移。
        """
        for index in range(self._bar_right_box.count()):
            widget = self._bar_right_box.itemAt(index).widget()
            if widget is self.account_row or widget is self.tool_row:
                self._bar_right_box.setStretch(index, 0)

    def _bar_icons(self) -> tuple:
        """横栏里当小图标用的三个按钮（横屏时它们各有各的文字位置）。"""
        return (self.batch_button, self.notification_button, self.appearance_button, self.refresh_button,
                self.clear_wall_button)

    def _sync_bar_icons(self) -> None:
        """竖屏工具统一用图标；横屏多选仍为紧凑图标。"""
        top = self.side == "top"
        self.batch_button.setProperty("sidebarCompact", not top)
        self.notification_button.setProperty("sidebarCompact", not top)
        if top:
            # 图标是自己画的（BarIconButton）：字形在雅黑下会偏左 / 偏小。
            # 按钮换成 #BarIcon 那套方形样式，ChipButton 的 10px 内边距会挤掉图标
            for button in self._bar_icons():
                button.setObjectName("BarIcon")
                button.setFixedSize(30, 30)
                if isinstance(button, BarIconButton):
                    button.set_icon_mode(True)
        else:
            for button in self._bar_icons():
                button.setObjectName("ChipButton")
                button.setMinimumSize(0, 0)
                button.setMaximumSize(16_777_215, 16_777_215)
                if isinstance(button, BarIconButton):
                    button.set_icon_mode(False)
            self.batch_button.setObjectName("BarIcon")
            self.batch_button.set_icon_mode(True)
            self.batch_button.setFixedSize(22, 22)
            self.refresh_button.setFixedSize(28, 22)  # RefreshButton 的原始尺寸
        if not top:
            self.notification_button.setObjectName("BarIcon")
            self.notification_button.setFixedSize(22, 22)
        self.appearance_button.setFixedSize(22, 22)
        for button in self._bar_icons():
            _repolish(button)

    def _restore_side_children(self) -> None:
        """回左栏：多选图标与外观、刷新一起回状态行。"""
        self._detach_from_rows(self.batch_button)
        self.batch_button.setParent(self.status_row)

        box = self.status_row.layout()
        for widget in (self.count_label, self.batch_button, self.notification_button, self.appearance_button, self.refresh_button):
            box.removeWidget(widget)
        box.addWidget(self.count_label, 1)
        box.addWidget(self.batch_button, 0, Qt.AlignRight)
        box.addWidget(self.notification_button, 0, Qt.AlignRight)
        box.addWidget(self.appearance_button, 0, Qt.AlignRight)
        box.addWidget(self.refresh_button, 0, Qt.AlignRight)
        self.appearance_button.setParent(self.status_row)
        self.refresh_button.setParent(self.status_row)
        self._sync_bar_icons()

    def _adopt_bar_row(self) -> None:
        """竖屏：把横栏排成两行。

        第一行：logo（圆点 + 「DD监控室CE」）+ 搜索框（收起时换成头排）
        + 多选/外观/刷新三个小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块，那块里「账号 / 布局预设 / 设置」竖排、
        中间两条 1px 分割线 —— 三个按钮 + 两条线正好把卡片条那一行的高度分完，
        不占第一行的地方（用户要求：加起来和左侧展开关注栏同高，别占用别处）。
        """
        self._ensure_bar_row()
        if not self._bar_in_use:
            index = self._layout.indexOf(self._header_row)
            for widget in (self._header_row, self.search, self._head_scroll,
                           self.batch_bar, self.batch_button, self.notification_button,
                           self.appearance_button, self.refresh_button, self.clear_wall_button, self.toggle_button):
                self._detach_from_rows(widget)
                widget.setParent(self._bar_row)
            # 左边是 logo，然后是搜索框（收起时换成头像排）、多选条、图标、展开键。
            # 多选条和搜索框轮流坐第一行：**不额外占一行**，横栏高度不变，
            # 画面墙就不会因为点「多选」抖一下（用户报的）。
            self._bar_row_box.addWidget(self._header_row)
            self._bar_row_box.addWidget(self.search, 1)
            self._bar_row_box.addWidget(self._head_scroll, 1)
            self._bar_row_box.addWidget(self.batch_bar, 1)
            for widget in self._bar_icons() + (self.toggle_button,):
                self._bar_row_box.addWidget(widget)
            # 第一行的高度固定成标准控件那一档（多选条里的删除/取消就是原来那两个
            # 按钮，压矮了圆角就和样式表对不上）。固定住之后，搜索框和多选条谁在
            # 这一行里都一样高 —— 点「多选」不会让横栏变高、画布不抖。
            self._bar_row.setFixedHeight(self.batch_bar.sizeHint().height())

            self._detach_from_rows(self.scroll)
            self._detach_from_rows(self.tool_row)
            self.scroll.setParent(self._bar_row2)
            self._bar_row2_box.addWidget(self.scroll, 1)
            self._bar_row2_box.addWidget(self._bar_right)
            # 右边那一块：账号 / 空白 / 分割线 / 空白 / 工具行。
            # 三个按钮都用横屏那套自然高度，两条空白（含中间的 1px 线）一样高，
            # 最上面、最下面的按钮正好贴着卡片条那一行的上下沿。
            self._place_account(True)
            self._bar_right_box.insertWidget(1, self._bar_gaps[0])
            self._bar_right_box.insertWidget(2, self._bar_divider_label)
            self._bar_right_box.insertWidget(3, self._bar_gaps[1])
            self._bar_right_box.insertWidget(4, self.tool_row)
            self._apply_bar_block_stretches()
            tool_box = self.tool_row.layout()
            tool_box.setDirection(QBoxLayout.TopToBottom)
            tool_box.setSpacing(0)
            tool_box.insertWidget(1, self._bar_gaps[2])
            tool_box.insertWidget(2, self._bar_divider_tool)
            tool_box.insertWidget(3, self._bar_gaps[3])
            # 两个按钮自己不吃 stretch（横屏时布局预设是 stretch 1）
            tool_box.setStretch(0, 0)
            tool_box.setStretch(4, 0)
            self._sync_bar_gaps()
            # 三个按钮左右长度一样（都撑满这一块）；高度用横屏那套自然高度
            for button in (self.layout_button, self.picture_in_picture_button, self.settings_button):
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            self._layout.insertWidget(index + 1 if index >= 0 else 1, self._bar_row)
            self._layout.insertWidget(index + 2 if index >= 0 else 2, self._bar_row2)
            self._bar_in_use = True
            self._sync_bar_icons()
        self._bar_row.setVisible(True)

    def _release_bar_row(self) -> None:
        """回左栏：把这两行拆掉，控件按 __init__ 里的原始顺序挂回竖排布局。"""
        if not self._bar_in_use:
            return
        for row in (self._bar_row, self._bar_row2):
            self._layout.removeWidget(row)
            row.setVisible(False)
        for widget in self._bar_widgets() + [self.scroll, self._header_row]:
            self._detach_from_rows(widget)
        for widget in self._column_order:
            self._detach_from_rows(widget)
            self._layout.addWidget(widget)
        # 布局预设 / 设置回到横排一行，把竖排时插进去的空白和分割线拿出来
        tool_box = self.tool_row.layout()
        tool_box.removeWidget(self._bar_divider_tool)
        for gap in self._bar_gaps[2:]:
            tool_box.removeWidget(gap)
        tool_box.setDirection(QBoxLayout.LeftToRight)
        tool_box.setStretch(0, 1)
        tool_box.setSpacing(6)
        for gap in self._bar_gaps[:2]:
            self._bar_right_box.removeWidget(gap)
        for button, policy in self._tool_button_policies.items():
            button.setSizePolicy(policy)
            button.setMaximumWidth(16_777_215)   # 竖屏时按自身宽度限过
        self.layout_button.setText("布局预设")
        self.tool_row.setMinimumWidth(0)
        self.tool_row.setMaximumWidth(16_777_215)
        # 多选条回左栏：高度限制解掉，按钮恢复样式表那套高度
        self._bar_row.setMinimumHeight(0)
        self._bar_row.setMaximumHeight(16_777_215)
        self.batch_bar.setMinimumHeight(0)
        self.batch_bar.setMaximumHeight(16_777_215)
        for button in (self.delete_button, self.cancel_button):
            button.setMinimumHeight(0)
            button.setMaximumHeight(16_777_215)
        self.account_row.setSizePolicy(self._account_policy)
        self._bar_in_use = False
        self._sync_account_row_shape()          # 账号条恢复原来的固定高度
        self._sync_account_row_width()          # 左栏的账号条恢复撑满

    def _account_row_should_show(self) -> bool:
        """账号按钮什么时候露出来。

        用户 2026-09-18：**没登录也要露**（显示「登录」，点了弹扫码登录）；
        登录后横屏在侧栏底部、竖屏在横栏右侧那一块 / 收起态头像排旁边。
        """
        return not self.select_mode

    def _sync_selection_controls(self):
        self.account_row.setVisible(self._account_row_should_show())
        self.tool_row.setVisible(self.side == 'top' and not self.select_mode and not self.collapsed)
        self.normal_bar.hide()
        if self.select_mode and self.side == 'top':
            self._bar_right.hide()

    def _sync_account_row_shape(self) -> None:
        """账号条的形状跟着「横屏/竖屏 + 收起/展开」走。

        竖屏收起时横栏只有 36px 高，账号头像要按头排头像的尺寸（34）挤进去；
        竖屏展开时它在右侧那一块里，高度就用横屏那套（34），多出来的高度留给
        两条空白；其它情况沿用原来的样子。
        """
        if self.side == "top" and not self.collapsed:
            self.account_row.set_compact(False)
            # 高度用横屏那套（34），宽度跟着这一块走（三个按钮左右一样长）
            self.account_row.setFixedHeight(theme.CONTROL_HEIGHT)
            self.account_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        elif self.side == "top":
            self.account_row.set_compact(True, avatar=RoomStrip.AVATAR, margin=1)
        else:
            self.account_row.set_compact(self.collapsed)

    def _sync_account_row_width(self) -> None:
        """横栏里的账号条宽度。

        展开时放得下昵称（否则会被挤成「A…」）；收起时它就是一个和头排头像
        一样大的小圆点 —— 不这么算的话它会一直沿用昵称的宽度，变成一条长胶囊。
        横屏时它本来就撑满侧栏，不需要这个限制。
        """
        row = self.account_row
        if self.side != "top":
            row.setMinimumWidth(0)
            row.setMaximumWidth(16_777_215)
            return
        row.setMaximumWidth(16_777_215)
        if self.collapsed:
            row.setMinimumWidth(row.avatar.width() + 2)
            return
        box = row._layout
        margins = box.contentsMargins()
        # +8：留一点余量，正好卡着算出来的宽度会让昵称尾字差几个像素被省略
        need = (margins.left() + margins.right() + box.spacing() * 2
                + row.avatar.width() + max(row.name.sizeHint().width(), row.account_id.sizeHint().width())
                + row.arrow.sizeHint().width() + 8)
        row.setMinimumWidth(min(self.ACCOUNT_PILL_MAX, need))

    def _sync_top_mode(self) -> None:
        """按 side + collapsed 决定顶部横栏露哪些控件。

        横栏是**一行**：左边搜索框（收起时换成头像排），中间「多选 / 外观 / 刷新」
        三个小图标，右边一块是账号头像 + 布局预设 + 设置 + 展开/收起键；
        下面只剩横向卡片条。头像排在收起时露出来（它就是关注列表）。
        """
        self._sync_toggle_arrow()          # 竖屏要上下箭头，横屏左右
        if self.side != "top":
            self._sync_appearance_row()
            return
        self._adopt_bar_row()
        self._sync_bar_density()
        self._sync_account_row_shape()
        self._sync_account_row_width()
        header = getattr(self, "_header_row", None)
        toggle = getattr(self, "toggle_button", None)
        # 展开时收起头排（用户要求展开后不显示头像排，那点高度留给卡片）；
        # 收起时它顶掉搜索框的位置，一行摆满关注头像
        self._head_scroll.setVisible(self.collapsed)
        # 账号头像：展开时在卡片条右边那一块里，收起时回到第一行最右端
        self._place_account(not self.collapsed)
        self._bar_right.setVisible(not self.collapsed)
        self._bar_row2.setVisible(not self.collapsed)
        if toggle is not None:
            # 摘到横栏这一行的右端常驻；换成紧凑样式，
            # 否则标题行那套 24px 最小尺寸 + padding 会把横栏撑高一截
            toggle.setObjectName("BarToggle")
            toggle.setFixedSize(22, 22)
            if toggle.parentWidget() is not self._bar_row:
                toggle.setParent(self._bar_row)
                self._bar_row_box.addWidget(toggle)
            toggle.setVisible(True)
            _repolish(toggle)
        if self.collapsed:
            if header is not None:
                header.setVisible(False)
            # 收起时这一行只剩：头像排 + 账号头像 + 展开键
            for widget in (self.search, self.status_row, self.scroll, self.normal_bar,
                           self.batch_bar, self.tool_row) + self._bar_icons():
                widget.setVisible(False)
            self.account_row.setVisible(self._account_row_should_show())
        else:
            # 标题行留在第一行最前面当 logo（用户要求左侧给 logo 留位置）：
            # 只露「DD监控室CE」，副标题藏起来；搜索框因此短了一截
            if header is not None:
                header.setVisible(True)
            self._show_logo_title()
            # 第一行：平时是搜索框 + 三个图标；进多选态就让多选条顶掉它们，
            # 这一行的高度不变 —— 点「多选」时画面墙不会跟着抖（用户报的）
            select = self.select_mode
            self.search.setVisible(not select)
            self.batch_bar.setVisible(select)
            for button in self._bar_icons():
                button.setVisible(not select)
            self.batch_button.setVisible(True)
            # 排序/刷新已经在搜索那一行当图标了，「关注中 · N」那一行不再出来
            self.status_row.setVisible(False)
            self.scroll.setVisible(True)
            # 导入关注 / 添加直播间收进账号菜单，别再占一行
            self.normal_bar.setVisible(False)
            self.account_row.setVisible(self._account_row_should_show())
            self.tool_row.setVisible(True)           # 布局预设 + 设置并排
            self.settings_button.setVisible(True)
            self._apply_scroll_axis()
        self._sync_appearance_row()

    def _show_logo_title(self) -> None:
        """竖屏横栏只挂紧凑 Logo，不改变原有第一行高度。"""
        self._set_brand_header(compact=True)

    def _set_brand_header(self, compact: bool) -> None:
        """横屏显示 Logo + 名称；紧凑横栏只显示 Logo。"""
        size = 30 if compact else 28
        self.logo_label.setFixedSize(size, size)
        if not self._brand_logo.isNull():
            self.logo_label.setPixmap(self._brand_logo.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.logo_label.setVisible(True)
        self.title_label.setVisible(not compact)
        self.subtitle_label.setVisible(False)
        if not compact:
            self.subtitle_label.setVisible(True)

    def _apply_scroll_axis(self) -> None:
        """竖屏横栏里关注列表是横向卡片条：左右滚，只占一条高度。"""
        top = self.side == "top"
        if top:
            # 一条卡片 + 间距 + 横向滚动条自己的高度：滚动条是占位的，
            # 不留这 8px 卡片底边会被它切掉（「直播中」角标会缺一角）
            rows = self.list_box.item_size()[1] + NAV_ITEM_GAP + theme.SCROLLBAR_SIZE
            self.scroll.setMinimumHeight(rows)
            self.scroll.setMaximumHeight(rows)
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.scroll.horizontal_only = True
        else:
            self.scroll.setMinimumHeight(0)
            self.scroll.setMaximumHeight(16_777_215)
            # 横滚条必须显式关掉：留着 AsNeeded 时，卡片宽度正好等于视口宽度，
            # Qt 会把滚动条弹出来，挤掉高度后就只剩一张卡片可见了
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff if self.collapsed else Qt.ScrollBarAlwaysOn)
            self.scroll.horizontal_only = False
        self.list_box.relayout(animate=False)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.collapsed)

    def _sync_toggle_arrow(self) -> None:
        """收起键的箭头方向：横屏左右、竖屏上下（用户要求）。"""
        toggle = getattr(self, "toggle_button", None)
        if toggle is None:
            return
        if hasattr(toggle, "set_orientation"):
            toggle.set_orientation(self.side == "top", self.collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        """一次提交完整布局；保留 animate 参数供既有调用方使用。"""
        if collapsed == self.collapsed:
            return
        if self.side == "top":
            self.collapsed = collapsed
            # 竖屏：宽度始终撑满，收起/展开只影响露出哪些控件。
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._sync_top_mode()
            if not collapsed:
                for item in self._items:
                    item.set_compact(False)
                self.list_box.relayout(animate=False)
            self.collapsedChanged.emit(collapsed)
            return

        updates_enabled = self.updatesEnabled()
        items = self._items
        self.setUpdatesEnabled(False)
        self._collapse_animating = True
        self.collapseAnimationChanged.emit(True)
        prepared = False
        try:
            for item in items:
                item.thumb.stop()
                item.thumb.set_cover_hold(True)
            self.collapsed = collapsed
            self._apply_collapsed_controls()
            self._finish_collapse(
                (theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH) + RAIL_WIDTH)
            prepared = True
        finally:
            self._collapse_animating = False
            for item in items:
                item.thumb.set_cover_hold(False)
            try:
                self.setUpdatesEnabled(updates_enabled)
                if prepared and updates_enabled and self.isVisible():
                    # 左栏完整绘制后才调整原生视频窗口，避免缩放开销卡住左栏显示。
                    self.repaint()
            finally:
                self.collapseAnimationChanged.emit(False)
        self.collapsedChanged.emit(collapsed)

    def _apply_collapsed_controls(self) -> None:
        """在暂停绘制期间对齐控件与条目的最终显示状态。"""
        collapsed = self.collapsed
        for widget in (self.search, self.status_row, self.normal_bar, self.batch_bar,
                       self.logo_label, self.batch_button, self.tool_row):
            widget.setVisible(not collapsed and (widget is not self.batch_bar or self.select_mode))
        self._sync_account_row_shape()
        self.account_row.setVisible(self._account_row_should_show())
        # 窄条里列表一出现滚动条就会把内容挤窄，上下两排头像就对不齐了；
        # 收起时干脆不显示滚动条，滚轮照样能滚
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if collapsed else Qt.ScrollBarAlwaysOn)
        for index in range(self.title_box.count()):
            widget = self.title_box.itemAt(index).widget()
            if widget:
                widget.setVisible(not collapsed)
        self._layout.setContentsMargins(8 if collapsed else 12, 14, 8 if collapsed else 12, 12)
        self._sync_toggle_arrow()
        self._sync_appearance_row()
        for item in self._items:
            item.set_compact(collapsed)
        self.list_box.relayout(animate=False)

    def _finish_collapse(self, target: int) -> None:
        """恢复绘制前完成最终几何与可见封面，屏外封面滚入时再补。"""
        self.setFixedWidth(target)
        if self.parentWidget() is not None:
            layout = self.parentWidget().layout()
            if layout is not None:
                layout.activate()
        self._outer_layout.activate()
        self._layout.activate()
        self._collapse_animating = False
        self.list_box.relayout(animate=False)
        for item in self._items:
            item.layout().activate()
            item.thumb.set_cover_hold(False)
            if not item.thumb.visibleRegion().isEmpty():
                item.thumb.refresh_cover()
            item.thumb.update()
        for card in self._smart_cards.values():
            card.update()

    def _refresh_visible_covers(self) -> None:
        if self._collapse_animating:
            return
        for item in self._items:
            if item.thumb._cover_dirty and not item.thumb.visibleRegion().isEmpty():
                item.thumb.refresh_cover()

    def _set_pointer_hover(self, item) -> None:
        previous = self._pointer_hover_item
        self._pointer_hover_item = item
        if previous is not None and previous is not item:
            try:
                previous._hover_leave_timer.stop()
                if previous.property("hovered"):
                    previous._set_hovered(False)
                    previous.unhovered.emit(previous.room)
            except RuntimeError:  # The previous row may have been removed.
                pass
        if item is not None:
            item._hover_leave_timer.stop()
            if not item.property("hovered"):
                item._set_hovered(True)
                item.hovered.emit(item.room)

    def _sync_pointer_hover(self) -> None:
        # Native child windows can omit Enter as well as Leave. Hit-test once
        # for the whole visible list, including rows without a live preview.
        item = None
        viewport = self.scroll.viewport()
        if (self.isVisible() and viewport.isVisible()
                and not QApplication.activePopupWidget() and not QApplication.activeModalWidget()):
            pointer = QCursor.pos()
            if viewport.rect().contains(viewport.mapFromGlobal(pointer)):
                child = self.list_box.childAt(self.list_box.mapFromGlobal(pointer))
                while child is not None and child is not self.list_box:
                    if isinstance(child, NavItem):
                        item = child
                        break
                    child = child.parentWidget()
        self._set_pointer_hover(item)

    def _prepare_drag_snapshot(self) -> None:
        if self._drag_snapshot_ready or not self.isVisible():
            return
        if self.drag_session.active or QApplication.mouseButtons() != Qt.NoButton:
            self._drag_snapshot_timer.start(100)
            return
        # Qt render() flushes pending move/resize events across the whole window,
        # including hidden cards. Do this once after show, outside the first drag.
        # Paint only one pixel without children; keep no stale card snapshot.
        pixel = QPixmap(1, 1)
        pixel.fill(Qt.transparent)
        self.render(pixel, QPoint(), QRegion(QRect(0, 0, 1, 1)), QWidget.RenderFlag(0))
        self._drag_snapshot_ready = True

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
        enabled = bool(enabled)
        if enabled == self.card_mode:
            return
        self.card_mode = enabled
        for item in self._items:
            item.thumb.stop()
            item.set_card_mode(enabled)
            item.set_portrait_strip(self.side == "top" and not enabled)
        self.list_box.relayout(animate=False)
        if self.side == "top" and self._bar_in_use:
            self._sync_top_mode()

    def set_compact_policy(self, card_mode: bool, auto_compact: bool,
                           compact_threshold: int) -> None:
        """保存用户偏好，并按当前关注数量决定实际使用哪种列表。"""
        self.preferred_card_mode = bool(card_mode)
        self.auto_compact = bool(auto_compact)
        self.compact_threshold = max(2, int(compact_threshold))
        self.set_card_mode(self._effective_card_mode())

    def set_compact_background(self, enabled: bool) -> None:
        self.compact_background = bool(enabled)
        for item in self._items:
            item.thumb.set_compact_background(enabled)

    def _effective_card_mode(self) -> bool:
        """横竖屏共用关注数量阈值，竖屏改为紧凑横向列表。"""
        return self.preferred_card_mode and not (
            self.auto_compact and len(self._items) >= self.compact_threshold)

    # ---- 批量选择 ----
    def set_select_mode(self, enabled: bool) -> None:
        self.select_mode = enabled
        if enabled:
            self.clear_sort_selection()
        self.batch_button.setChecked(enabled)
        if enabled and self.filter_text:
            # 进多选就把搜索清掉：藏起来的条目也还在「已选」里，批量删太危险
            self.search.clear()
        # 竖屏时 batch_bar 被借到横栏第一行里（见 _adopt_bar_row），
        # 露不露由 _sync_top_mode 统一决定，这里只管横屏那一列。
        if self.side != "top":
            self.batch_bar.setVisible(enabled and not self.collapsed)
            self.normal_bar.setVisible(not enabled and not self.collapsed)
        else:
            self._sync_top_mode()
        for item in self._items:
            item.set_select_mode(enabled and not self.collapsed)
        self._sync_selection_controls()
        self._update_batch_label()

    def _update_batch_label(self) -> None:
        count = sum(1 for item in self._items if item.is_checked())
        self.batch_label.setText(f"已选 {count} 个")
        self._sync_sort_selection()

    def _emit_delete(self) -> None:
        chosen = [item.room for item in self._items if item.is_checked()]
        if chosen:
            self.deleteRequested.emit(chosen)
        self.set_select_mode(False)

    def selected_sort_ids(self) -> list[str]:
        if self.select_mode:
            return [str(item.room.get("room_id")) for item in self._items
                    if item.is_checked() and not item.filtered_out]
        return [str(item.room.get("room_id")) for item in self._items
                if str(item.room.get("room_id")) in self._sort_selected_ids]

    def _sync_sort_selection(self) -> None:
        selected = set() if self.select_mode else set(self.selected_sort_ids())
        for item in self._items:
            item.set_sort_selected(str(item.room.get("room_id")) in selected)

    def clear_sort_selection(self) -> None:
        if self._sort_selected_ids:
            self._sort_selected_ids.clear()
            self._sync_sort_selection()
        self._sort_anchor = None

    def select_sort_item(self, room_id: str, modifiers) -> None:
        """Ctrl 增减选择，Shift 选一段；普通点击回到单卡片操作。"""
        room_id = str(room_id)
        if modifiers & Qt.ShiftModifier:
            visible = [str(item.room.get("room_id")) for item in self.visible_items()]
            if self._sort_anchor in visible and room_id in visible:
                start, end = sorted((visible.index(self._sort_anchor), visible.index(room_id)))
                chosen = set(visible[start:end + 1])
            else:
                chosen = {room_id}
            self._sort_selected_ids = (self._sort_selected_ids | chosen
                                       if modifiers & Qt.ControlModifier else chosen)
        elif modifiers & Qt.ControlModifier:
            if room_id in self._sort_selected_ids:
                self._sort_selected_ids.remove(room_id)
            else:
                self._sort_selected_ids.add(room_id)
            self._sort_anchor = room_id
        else:
            self._sort_selected_ids.clear()
            self._sort_anchor = room_id
        self._sync_sort_selection()

    def dragged_room_ids(self, room_id: str) -> list[str]:
        """从选中卡片拖动时带上整组；拖动未选中的卡片则只移动它。"""
        room_id = str(room_id)
        if room_id in self.selected_sort_ids():
            return self.selected_sort_ids()
        if not self.select_mode:
            self.clear_sort_selection()
        return [room_id]

    def move_sort_selection(self, room_id: str, to_front: bool) -> bool:
        return self.reorder_items(self.dragged_room_ids(room_id),
                                  0 if to_front else len(self._items))

    # ---- 列表维护 ----
    def select_room(self, room: dict) -> None:
        room_id = str(room.get("room_id") or "")
        for item in self._items:
            item.set_selected(bool(room_id) and str(item.room.get("room_id") or "") == room_id)

    def _append_item(self, room: dict) -> NavItem:
        item = NavItem(room, len(self._items), parent=self.list_box)
        room_id = str(room.get("room_id"))
        if room_id and room_id not in self.import_order:
            self.import_order.append(room_id)     # 「导入顺序」排序用
        if room_id and room_id not in self.custom_order:
            self.custom_order.append(room_id)     # 新加的房间先排在自定义顺序最后
        item.drop_host = self                 # 列表内部拖动排序
        item.clicked.connect(self.roomSelected.emit)
        item.addRequested.connect(self.addToWallRequested.emit)
        item.removeRequested.connect(self.removeRequested.emit)
        item.openBrowserRequested.connect(self.openBrowserRequested.emit)
        item.checkedChanged.connect(self._update_batch_label)
        item.pinToggled.connect(self.toggle_pin)
        item.hovered.connect(self.previewHovered.emit)
        item.unhovered.connect(self.previewUnhovered.emit)
        item.set_card_mode(self.card_mode)
        item.thumb.set_compact_background(self.compact_background)
        item.set_portrait_strip(self.side == "top" and not self.card_mode)
        item.set_on_wall(room_id in self._wall_room_ids)
        item.set_select_mode(self.select_mode)
        self._items.append(item)
        item_height = NAV_ITEM_HEIGHT if self.card_mode else NAV_LIST_ITEM_HEIGHT
        item.resize(self.list_box.width(), item_height)
        item.show()
        return item

    def add_room(self, room: dict) -> bool:
        return bool(self.add_rooms([room]))

    def add_rooms(self, rooms: list[dict]) -> list[dict]:
        known = {str(item.room.get("room_id")) for item in self._items}
        added = []
        for room in rooms:
            room_id = str(room.get("room_id"))
            if room_id in known:
                continue
            known.add(room_id)
            self._folder_pending.add(room_id)
            self._append_item(room)
            added.append(room)
        if not added:
            return []
        self.set_compact_policy(self.preferred_card_mode, self.auto_compact,
                                self.compact_threshold)
        # 新控件初始坐标是 (0, 0)，必须立即排版，否则会压在第一项上，
        # 直到用户拖动列表才恢复。
        self.resort(animate=False)
        self._sync_count()
        self._refresh_wall_marks()      # 新卡片的蓝框按当前墙面重设一次
        self.refresh_strip()
        if self.isVisible() and motion.enabled():
            self._entering_room_ids.update(str(room["room_id"]) for room in added)
            self._card_entry_timer.start(0)
        return added

    def _reveal_added_rooms(self) -> None:
        """等批量添加与目标文件夹归类结束，只让新卡片从最终落点滑入。"""
        entering = {item for item in self._items
                    if str(item.room.get("room_id")) in self._entering_room_ids}
        self._entering_room_ids.clear()
        if entering and self.isVisible() and motion.enabled():
            self.list_box.relayout(animate=True, duration=220, revealing=entering)

    def remove_room(self, room: dict) -> None:
        item = next((entry for entry in self._items
                     if str(entry.room.get("room_id")) == str(room.get("room_id"))), None)
        if item is None:
            return
        item.hide()
        item.drop_live_alert()
        item.thumb.stop()               # 缩略图里可能正在放预览
        item.thumb.release_player()
        item.setParent(None)
        item.deleteLater()
        self._items.remove(item)
        room_id = str(room.get("room_id"))
        self._folder_pending.discard(room_id)
        for folder in self.folders:
            if room_id in folder["rooms"]:
                folder["rooms"].remove(room_id)
        self._sort_selected_ids.discard(room_id)
        if self._sort_anchor == room_id:
            self._sort_anchor = None
        if room_id in self.import_order:
            self.import_order.remove(room_id)
        if room_id in self.custom_order:
            self.custom_order.remove(room_id)
        self.set_compact_policy(self.preferred_card_mode, self.auto_compact,
                                self.compact_threshold)
        self.refresh_filter()
        self._sync_count()
        self._refresh_wall_marks()      # 删完也重设一次，蓝框状态别留旧账
        self.refresh_strip()

    def rooms(self) -> list[dict]:
        return [item.room for item in self._items]

    def items(self) -> list[NavItem]:
        return list(self._items)

    def drop_index_at(self, global_pos) -> int:
        """全局坐标 -> 列表里的落点下标（给 NavItem 转发拖动用）。"""
        local = self.list_box.mapFromGlobal(global_pos)
        return self.list_box.index_at(local.x() if self.list_box.horizontal
                                      else local.y())

    def hover_drag(self, room_id: str, global_pos) -> None:
        """拖动过程中：贴近边缘自动滚，并在落点让出一格。"""
        # 自动滚吃**全局坐标**（它内部按视口算边界）；落点下标要的是**内容坐标**
        # —— 以前把两者混成同一个变量，往下滚就永远触发不了。
        self.list_box.auto_scroll(global_pos)
        local = self.list_box.mapFromGlobal(global_pos)
        along = local.x() if self.list_box.horizontal else local.y()
        self.show_drop_indicator(room_id, self.list_box.index_at(along))

    def finish_drag(self, room_id: str, global_pos) -> None:
        """松手时结算：鼠标还在列表里就按落点排序，否则只把卡片放回去。"""
        self.list_box.set_scroll_dir(0)
        local = self.list_box.mapFromGlobal(global_pos)
        inside = (0 <= local.x() <= self.list_box.width()
                  and 0 <= local.y() <= self.list_box.height())
        if inside:
            for folder_id, button in self._folder_buttons.items():
                if not button.isHidden() and button.geometry().contains(local):
                    self.move_to_folder(self.dragged_room_ids(room_id), folder_id)
                    return
            along = local.x() if self.list_box.horizontal else local.y()
            self.reorder_items(self.dragged_room_ids(room_id),
                               self._full_drop_index(self.list_box.index_at(along)))
        self.list_box.relayout(animate=True)

    # ---- 拖动排序 ----
    def _full_drop_index(self, visible_index: int) -> int:
        """搜索过滤时把屏幕上的落点换算为完整列表下标。"""
        visible = self.visible_items()
        if not visible:
            return len(self._items)
        if visible_index >= len(visible):
            return self._items.index(visible[-1]) + 1
        return self._items.index(visible[max(0, visible_index)])

    def _reordered_items(self, room_ids: list[str], drop_index: int) -> list[NavItem]:
        """将选中项作为一组移动；置顶和普通项分别留在自己的区域。"""
        moving = set(room_ids)
        result = []
        groups = [[item for item in self._items if item.is_pinned == pinned
                   and self.folder_for(str(item.room.get("room_id"))) == folder["id"]]
                  for folder in self.folders for pinned in (True, False)]
        for group in groups:
            start = self._items.index(group[0]) if group else 0
            target = max(0, min(drop_index - start, len(group)))
            before = sum(str(item.room.get("room_id")) not in moving
                         for item in group[:target])
            remaining = [item for item in group
                         if str(item.room.get("room_id")) not in moving]
            selected = [item for item in group
                        if str(item.room.get("room_id")) in moving]
            result.extend(remaining[:before] + selected + remaining[before:])
        return result

    def show_drop_indicator(self, room_id: str | None, drop_index: int) -> None:
        """拖动中：选中卡片藏起来，其余卡片让出整组空位。"""
        if not room_id:
            self.list_box.relayout(animate=True)
            return
        moving = set(self.dragged_room_ids(room_id))
        items = self._reordered_items(list(moving), self._full_drop_index(drop_index))
        preview = self.folder_entries(items, moving) if self.folders else [
            None if str(item.room.get("room_id")) in moving else item
            for item in items if not item.filtered_out]
        self.list_box.relayout(animate=True, preview_order=preview, dragging_ids=moving)

    def end_drag(self) -> None:
        """拖动结束（放下或者取消）：所有卡片恢复显示并归位。"""
        self.list_box.set_scroll_dir(0)
        self.list_box.relayout(animate=True)

    def reorder_item(self, room_id: str, drop_index: int) -> bool:
        return self.reorder_items([str(room_id)], drop_index)

    def reorder_items(self, room_ids: list[str], drop_index: int) -> bool:
        """按当前顺序整体移动卡片，并立即保存自定义顺序。"""
        known = {str(item.room.get("room_id")) for item in self._items}
        if not known.intersection(room_ids):
            return False
        items = self._reordered_items(room_ids, drop_index)
        if [str(entry.room.get("room_id")) for entry in items] == \
                [str(entry.room.get("room_id")) for entry in self._items]:
            return False
        pinned_before = list(self.pinned)
        self._items = items
        self.pinned = [str(entry.room.get("room_id")) for entry in items if entry.is_pinned]
        changed_folders = {self.folder_for(rid) for rid in room_ids}
        for folder in self.folders:
            if folder["id"] in changed_folders:
                self._remember_folder_order(folder["id"])
                folder["sort"] = "custom"
        self.sort_mode = self.default_folder()["sort"]
        self._sync_watch_history_mode()
        self.list_box.relayout(animate=True)
        self.refresh_strip()
        if self.pinned != pinned_before:
            self.pinChanged.emit(list(self.pinned))
        self.orderChanged.emit()
        return True

    # ---- 置顶 ----
    def apply_pins(self, pinned: list) -> None:
        """置顶的先显示在前面（顺序按置顶列表）。"""
        self.pinned = [str(item) for item in pinned]
        for item in self._items:
            item.set_pinned(str(item.room.get("room_id")) in self.pinned)
        self.resort(animate=False)

    # ---- 排序 ----
    def _sync_watch_history_mode(self, *, refresh=False):
        current = {folder["id"] for folder in self.folders if folder["sort"] == "frequent"}
        self.watch_history.set_enabled(bool(current))
        if refresh or current - self._frequent_folders:
            self._frequent_scores = self.watch_history.scores()
        self._frequent_folders = current

    def refresh_frequent_order(self):
        self._frequent_scores = self.watch_history.scores()
        self.resort(animate=False)

    def add_folder_sort_menu(self, menu, folder) -> None:
        menu.setToolTipsVisible(True)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for mode, label in self.SORT_MODES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == folder["sort"])
            if mode == "frequent":
                action.setToolTip(SORT_TIP)
            action.triggered.connect(lambda _checked=False, value=mode, fid=folder["id"]:
                                     self.set_folder_sort(fid, value))
            group.addAction(action)
        menu.addSeparator()
        menu.addAction("固定当前显示顺序").triggered.connect(
            lambda: self.freeze_current_order(folder["id"]))

    def freeze_current_order(self, folder_id="") -> None:
        """把当前看到的顺序保存为自定义顺序。"""
        folder_id = folder_id or self.default_folder()["id"]
        self._remember_folder_order(folder_id)
        self.set_folder_sort(folder_id, "custom")

    def _remember_folder_order(self, folder_id: str) -> None:
        current = [str(item.room.get("room_id")) for item in self._items
                   if self.folder_for(str(item.room.get("room_id"))) == folder_id]
        ordered = iter(current)
        self.custom_order = [next(ordered) if rid in current else rid for rid in self.custom_order]

    def set_folder_sort(self, folder_id: str, mode: str, notify=True) -> None:
        folder = self.get_folder(folder_id)
        if folder is None:
            return
        folder["sort"] = mode if mode in dict(self.SORT_MODES) else "custom"
        self._sync_watch_history_mode(refresh=mode == "frequent")
        self.resort(animate=False)
        if notify:
            self.foldersChanged.emit()

    def set_sort_mode(self, mode: str, notify: bool = True) -> None:
        """切排序方式：自定义 / 开播优先 / 导入顺序。"""
        if mode not in dict(self.SORT_MODES):
            mode = "custom"
        self.sort_mode = mode
        self.set_folder_sort(self.default_folder()["id"], mode, notify=False)
        if notify:
            self.sortChanged.emit(mode)

    def set_import_order(self, order: list | None) -> None:
        """导入顺序（配置里存的）；没存过就按当前列表顺序算。"""
        known = [str(item) for item in (order or [])]
        for item in self._items:
            room_id = str(item.room.get("room_id"))
            if room_id not in known:
                known.append(room_id)
        self.import_order = known
        self.resort(animate=False)

    def set_custom_order(self, order: list | None) -> None:
        """自定义顺序（配置里存的）；没存过的房间按当前列表顺序补在后面。"""
        known = list(dict.fromkeys(str(entry) for entry in (order or [])))
        for item in self._items:
            room_id = str(item.room.get("room_id"))
            if room_id not in known:
                known.append(room_id)
        present = {str(item.room.get("room_id")) for item in self._items}
        self.custom_order = [room_id for room_id in known if room_id in present]
        self.resort(animate=False)

    def resort(self, animate: bool = False, *, duration=150, revealing=(), viewport_only=False) -> None:
        """每个文件夹独立排序，置顶只作用于所在文件夹。"""
        self.sort_mode = self.default_folder()["sort"]
        self._folder_assignments = follow_folders.assign_folders(
            self.rooms(), self.folders, self._folder_pending)
        pinned_ids = list(self.pinned)
        ordered = []
        for folder in self.folders:
            members = [item for item in self._items
                       if self.folder_for(str(item.room.get("room_id"))) == folder["id"]]
            pinned = [item for rid in pinned_ids for item in members if str(item.room.get("room_id")) == rid]
            rest = [item for item in members if str(item.room.get("room_id")) not in pinned_ids]
            order = self.import_order if folder["sort"] == "imported" else self.custom_order
            position = {rid: index for index, rid in enumerate(order)}
            def key(item):
                index = position.get(str(item.room.get("room_id")), len(position))
                if folder["sort"] == "frequent":
                    return (not bool(item.room.get("live")),
                            -self._frequent_scores.get(str(item.room.get("room_id")), 0), index)
                if folder["sort"] in ("live", "offline"):
                    return (bool(item.room.get("live")) != (folder["sort"] == "live"), index)
                if folder["sort"] == "name":
                    return (str(item.room.get("uname") or "").casefold(), index)
                return index
            rest.sort(key=key)
            ordered.extend(pinned + rest)
        self._items = ordered
        # 先按搜索词重算谁该藏起来，再摆位置 —— 顺序反了会留下「藏起来的还占位」
        self._apply_filter_marks()
        self.list_box.relayout(animate=animate, duration=duration, revealing=revealing,
                              viewport_only=viewport_only)
        self._sync_count()             # 过滤时这里写成「露出来几路 / 一共几路」
        # 顺手把顶部横栏那一排头像也刷新：竖屏下它就是关注列表
        self.refresh_strip()

    def play_live_alerts(self, items: list) -> None:
        """重排之后再播开播动效。

        调用方要先把 room["live"] 置位、再 resort()，卡片才会先挪到「开播优先」
        该在的位置；动效放到下一个事件循环里播，那时卡片已经就位，水滴和气泡
        才会落在卡片身上，而不是留在它挪走之前的那一行。
        """
        pending = [item for item in items if item is not None]
        if not pending:
            return
        QTimer.singleShot(0, lambda: self._play_live_alerts_now(pending))

    @staticmethod
    def _play_live_alerts_now(items: list) -> None:
        for item in items:
            if item.parentWidget() is None:      # 已经不在列表里了
                continue
            item.play_live_alert()
            print(f"[开播提醒] {item.room.get('uname')}", file=sys.stderr, flush=True)

    def toggle_pin(self, room: dict) -> None:
        room_id = str(room.get("room_id"))
        if room_id in self.pinned:
            self.pinned.remove(room_id)
        else:
            self.pinned.append(room_id)
        self.apply_pins(self.pinned)
        self.pinChanged.emit(list(self.pinned))

    def _sync_count(self) -> None:
        platforms = {str(item.room.get("room_id", "")).split(":", 1)[0]
                     if ":" in str(item.room.get("room_id", "")) else "bilibili"
                     for item in self._items}
        for item in self._items:
            show = len(platforms) > 1 and getattr(self, "show_platform_logos", True)
            changed = item.platform_badge.property("showPlatform") != show
            if changed:
                item.platform_badge.setProperty("showPlatform", show)
            item.platform_badge.setVisible(show and not item.thumb.video.isVisible())
            if changed:
                item.thumb._layout_overlay()
        shown = len(self.visible_items())
        if self.filter_text:
            # 搜索时把「露出来几路 / 一共几路」都写上，免得以为关注丢了
            self.count_label.setText(f"关注中 · {shown} / {len(self._items)}")
        else:
            self.count_label.setText(f"关注中 · {len(self._items)}")
        if hasattr(self, 'navigation'):
            self.navigation.sync_count()

    def set_refreshing(self, busy: bool) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.set_refreshing(busy)
        self.refresh_button.setToolTip(
            "正在刷新关注列表…再次点击可排队刷新" if busy else "立刻刷新关注列表：直播状态、标题、在线人数、头像")
