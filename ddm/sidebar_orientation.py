"""Sidebar orientation and borrowed toolbar layout; Sidebar owns controls and mutable layout state."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget
from . import theme
from .sidebar_navigation import RAIL_WIDTH
from .ui.toolbar import BarIconButton
from .sidebar_portrait import PortraitSidebar
from .widget_support import NAV_ITEM_GAP, NAV_ITEM_HEIGHT, _repolish
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QLabel, QLineEdit, QMenu, QPushButton, QWidget
)
from . import follow_folders, layouts, motion, theme, version as version_module


class SidebarOrientation:
    def __init__(self, host):
        self.host = host
        self.portrait = PortraitSidebar(host)

    def set_side(self, side: str) -> None:
        """摆放方式：left = 横屏的左栏（默认）；top = 竖屏的顶部横栏。

        竖屏下侧栏变成一条顶部横栏：宽度撑满、搜索框变宽、列表只留一行头像
        （收起时只剩头像，展开时多一行按钮），逻辑和横屏的收起/展开一致。
        """
        host = self.host
        side = "top" if side == "top" else "left"
        # 无论走哪个分支，先把约束解掉：
        # - 滚动区的高度上限（竖屏那条「只占一条」的限制留着，切回左栏就只剩一条）
        # - 侧栏的竖直策略（竖屏时被压成一条，切回左栏必须重新撑满）
        host.scroll.setMinimumHeight(0)
        host.scroll.setMaximumHeight(16_777_215)
        host.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        host.setMinimumHeight(0)
        host.setMaximumHeight(16_777_215)
        host.list_box._clamp_vertical_scroll()
        if side == host.side:
            # 已经是这个摆放方式：不重复设置宽度，但仍要同步一次可见性 ——
            # 调用方（换排布 / 刚设过收起状态）可能正等着头像排露出来
            if side == "top":
                host._sync_top_mode()
            else:
                # 竖向时务必把滚动区的高度上限解掉：竖屏那条 130px 的限制留着，
                # 左栏就只剩一条（用户看到的就是这个）
                host._apply_scroll_axis()
            return
        if side == 'top':
            host.navigation.release()
        host.side = side
        host.set_card_mode(host._effective_card_mode())
        horizontal = side == "top"
        for item in host._items:
            item.set_portrait_strip(horizontal and not host.card_mode)
        if not horizontal:
            # 切回左栏：横栏那一行先拆掉（控件按原顺序挂回竖排），头像排收掉
            # （它只服务于顶部横栏），展开键还回标题行，并把「顶部横栏收起时
            # 藏起来的控件」逐个恢复 —— 只显示标题行容器是不够的，
            # 搜索/列表/按钮行会一直是隐藏状态，左栏就只剩一小条。
            host._release_bar_row()
            host._head_scroll.setVisible(False)      # 头像排只服务于顶部横栏
            header = getattr(host, "_header_row", None)
            if header is not None:
                header.setVisible(True)
            for index in range(host.title_box.count()):
                holder = host.title_box.itemAt(index).widget()
                if holder is not None:
                    holder.setVisible(True)
            host._set_brand_header(compact=False)
            host.batch_button.setVisible(True)
            for widget, visible in ((host.search, True), (host.status_row, True),
                                    (host.scroll, True),
                                    (host.normal_bar, not host.select_mode),
                                    (host.batch_bar, host.select_mode),
                                    (host.tool_row, True)):
                widget.setVisible(visible)
            host.settings_button.setVisible(True)    # 竖屏时它收进「⋯」里了
            # 横栏里的工具回到状态行，多选仍保留为状态行的图标。
            host._restore_side_children()
            host.account_row.setVisible(host._account_row_should_show())
            host._restore_toggle_to_header()
            # 竖屏那套滚动轴状态必须在这里还原：横排时 horizontal_only=True、
            # 竖条常关、横条 AsNeeded，不回滚的话回横屏后竖向滚动条一直藏着，
            # 滚轮还会被 CarouselScroll 当成横滚吞掉 —— 左栏整列就滚不动了。
            host._apply_scroll_axis()
        host.setFixedWidth(theme.SIDEBAR_WIDTH + RAIL_WIDTH)
        if horizontal:
            host._layout.setContentsMargins(10, 8, 10, 8)
            host._layout.setSpacing(6)
            host.setMinimumWidth(0)
            host.setMaximumWidth(16_777_215)
        else:
            host._layout.setContentsMargins(12 if not host.collapsed else 8, 14,
                                            12 if not host.collapsed else 8, 12)
            host._layout.setSpacing(10)
            host.setFixedWidth(
                (theme.SIDEBAR_RAIL_WIDTH if host.collapsed else theme.SIDEBAR_WIDTH) + RAIL_WIDTH)
        host._sync_top_mode()
        host.list_box.relayout(animate=False)

    def restore_toggle_to_header(self) -> None:
        """把「收起/展开」按钮放回标题行（竖屏时它是摘出来放在横栏右上角的）。"""
        host = self.host
        toggle = getattr(host, "toggle_button", None)
        header = getattr(host, "_header_row", None)
        if toggle is None or header is None:
            return
        host._detach_from_rows(toggle)
        toggle.setObjectName("SidebarToggle")      # 换回标题行那套样式
        toggle.setFixedSize(24, 24)
        toggle.setParent(header)
        header.layout().addWidget(toggle, 0, Qt.AlignTop)
        toggle.setVisible(True)
        _repolish(toggle)

    def detach_from_rows(self, widget: QWidget) -> None:
        """把控件从「竖排布局」和横栏那两个容器里都摘出来。"""
        host = self.host
        for holder in (host._layout, host._bar_row_box, getattr(host, '_bar_row2_box', None),
                       getattr(host, '_bar_right_box', None)):
            if holder is not None:
                holder.removeWidget(widget)

    def ensure_bar_row(self) -> None:
        return self.portrait.ensure()

    def bar_widgets(self) -> list:
        """竖屏时会被横栏借走的控件（横屏要按原样挂回去）。"""
        host = self.host
        return [host.search, host._head_scroll, host.batch_button, host.notification_button, host.clear_wall_button,
                host.appearance_button, host.refresh_button, host.account_row, host.tool_row,
                host.batch_bar, host.toggle_button]

    def place_account(self, in_right_block: bool) -> None:
        """账号头像的位置：展开时在整块里排第一，收起时回到第一行最右端。"""
        host = self.host
        wanted = host._bar_right if in_right_block else host._bar_row
        if host.account_row.parentWidget() is wanted:
            return
        host._detach_from_rows(host.account_row)
        host.account_row.setParent(wanted)
        if in_right_block:
            host._bar_right_box.insertWidget(0, host.account_row, 1)
            host._apply_bar_block_stretches()
        else:
            host._bar_row_box.insertWidget(host._bar_row_box.count() - 1,
                                           host.account_row)

    def sync_bar_gaps(self) -> None:
        """算两条空白的高度。

        目标是让**最下面的按钮下沿和直播间缩略图的下沿齐平**，所以减的是缩略图
        高度（`NAV_ITEM_HEIGHT`），不是整条卡片行 —— 卡片行还含那 8px 滚动条。
        三个按钮各用横屏那套高度，两条线各 1px，剩下的**均分**给两条空白。
        """
        host = self.host
        target = NAV_ITEM_HEIGHT
        buttons = (theme.CONTROL_HEIGHT + host.layout_button.sizeHint().height()
                   + host.picture_in_picture_button.sizeHint().height()
                   + host.settings_button.sizeHint().height())
        slack = max(0, target - buttons - 2)       # 四条空白加起来的高度
        # 每条空白 = 线上那段 + 1px 线 + 线下那段，所以先把那 1px 加回来再对半分
        per_gap, extra = divmod(slack + 2, 2)
        blank, blank_extra = divmod(max(0, per_gap - 1), 2)
        for index, gap in enumerate(host._bar_gaps):
            # 每条空白里「线上 / 线下」两段：先按对半分，余数给上面那段
            height = blank + (blank_extra if index % 2 == 0 else 0)
            if index >= 2:
                height += extra                    # 除不尽的那 1px 给第二条空白
            gap.setFixedHeight(height)

    def sync_bar_density(self) -> None:
        return self.portrait.sync_density()

    def apply_bar_block_stretches(self) -> None:
        """账号和工具行自己不占 stretch（高度全由按钮 + 空白算出来）。

        每次挪动账号都要重设：`insertWidget` / `removeWidget` 会让布局里其它项
        的下标平移。
        """
        host = self.host
        for index in range(host._bar_right_box.count()):
            widget = host._bar_right_box.itemAt(index).widget()
            if widget is host.account_row or widget is host.tool_row:
                host._bar_right_box.setStretch(index, 0)

    def bar_icons(self) -> tuple:
        """横栏里当小图标用的三个按钮（横屏时它们各有各的文字位置）。"""
        host = self.host
        return (host.batch_button, host.notification_button, host.appearance_button, host.refresh_button,
                host.clear_wall_button)

    def sync_bar_icons(self) -> None:
        """竖屏工具统一用图标；横屏多选仍为紧凑图标。"""
        if self.host.side == 'top':
            return self.portrait.sync_density()
        host = self.host
        top = host.side == "top"
        host.batch_button.setProperty("sidebarCompact", not top)
        host.notification_button.setProperty("sidebarCompact", not top)
        if top:
            # 图标是自己画的（BarIconButton）：字形在雅黑下会偏左 / 偏小。
            # 按钮换成 #BarIcon 那套方形样式，ChipButton 的 10px 内边距会挤掉图标
            for button in host._bar_icons():
                button.setObjectName("BarIcon")
                button.setFixedSize(30, 30)
                if isinstance(button, BarIconButton):
                    button.set_icon_mode(True)
        else:
            for button in host._bar_icons():
                button.setObjectName("ChipButton")
                button.setMinimumSize(0, 0)
                button.setMaximumSize(16_777_215, 16_777_215)
                if isinstance(button, BarIconButton):
                    button.set_icon_mode(False)
            host.batch_button.setObjectName("BarIcon")
            host.batch_button.set_icon_mode(True)
            host.batch_button.setFixedSize(22, 22)
            host.refresh_button.setFixedSize(28, 22)  # RefreshButton 的原始尺寸
        if not top:
            host.notification_button.setObjectName("BarIcon")
            host.notification_button.setFixedSize(22, 22)
        host.appearance_button.setFixedSize(22, 22)
        for button in host._bar_icons():
            _repolish(button)

    def restore_side_children(self) -> None:
        """回左栏：多选图标与外观、刷新一起回状态行。"""
        host = self.host
        host._detach_from_rows(host.batch_button)
        host.batch_button.setParent(host.status_row)

        box = host.status_row.layout()
        for widget in (host.count_label, host.batch_button, host.notification_button, host.appearance_button, host.refresh_button):
            box.removeWidget(widget)
        box.addWidget(host.count_label, 1)
        box.addWidget(host.batch_button, 0, Qt.AlignRight)
        box.addWidget(host.notification_button, 0, Qt.AlignRight)
        box.addWidget(host.appearance_button, 0, Qt.AlignRight)
        box.addWidget(host.refresh_button, 0, Qt.AlignRight)
        host.appearance_button.setParent(host.status_row)
        host.refresh_button.setParent(host.status_row)
        host._sync_bar_icons()

    def adopt_bar_row(self) -> None:
        return self.portrait.adopt()

    def release_bar_row(self) -> None:
        return self.portrait.release()

    def sync_top_mode(self) -> None:
        return self.portrait.sync()

    def show_logo_title(self) -> None:
        """竖屏横栏只挂紧凑 Logo，不改变原有第一行高度。"""
        host = self.host
        host._set_brand_header(compact=True)

    def set_brand_header(self, compact: bool) -> None:
        """横屏显示 Logo + 名称；紧凑横栏只显示 Logo。"""
        host = self.host
        size = 30 if compact else 28
        host.logo_label.setFixedSize(size, size)
        if not host._brand_logo.isNull():
            host.logo_label.setPixmap(host._brand_logo.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        host.logo_label.setVisible(True)
        host.title_label.setVisible(not compact)
        host.subtitle_label.setVisible(False)
        if not compact:
            host.subtitle_label.setVisible(True)

    def apply_scroll_axis(self) -> None:
        """竖屏横栏里关注列表是横向卡片条：左右滚，只占一条高度。"""
        host = self.host
        top = host.side == "top"
        if top:
            # 一条卡片 + 间距 + 横向滚动条自己的高度：滚动条是占位的，
            # 不留这 8px 卡片底边会被它切掉（「直播中」角标会缺一角）
            rows = host.list_box.item_size()[1] + NAV_ITEM_GAP + theme.SCROLLBAR_SIZE
            host.scroll.setMinimumHeight(rows)
            host.scroll.setMaximumHeight(rows)
            host.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            host.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            host.scroll.horizontal_only = True
        else:
            host.scroll.setMinimumHeight(0)
            host.scroll.setMaximumHeight(16_777_215)
            # 横滚条必须显式关掉：留着 AsNeeded 时，卡片宽度正好等于视口宽度，
            # Qt 会把滚动条弹出来，挤掉高度后就只剩一张卡片可见了
            host.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            host.scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff if host.collapsed else Qt.ScrollBarAlwaysOn)
            host.scroll.horizontal_only = False
        host.list_box.relayout(animate=False)
