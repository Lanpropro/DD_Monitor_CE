"""Sidebar orientation, borrowed controls and collapse layout; state stays on the widget."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .avatar_widgets import RoomStrip
from .sidebar_navigation import RAIL_WIDTH
from .ui.toolbar import BarIconButton
from .widget_support import NAV_ITEM_GAP, NAV_ITEM_HEIGHT, _repolish


class SidebarPresentation:
    def __init__(self, host):
        self.host = host

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
        """建出横栏的两行容器（只建一次）。

        第一行：logo + 搜索框（收起时换成头像排）+ 多选/外观/刷新小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块（账号 / 布局预设 / 设置 竖排）。
        右侧那一块只占第二行，不侵占第一行的地方（用户要求）；高度就是卡片条
        那一行的高度，三个按钮 + 两条分割线把它正好分完。
        """
        host = self.host
        if host._bar_row is not None:
            return
        host._bar_row = QWidget(host)
        box = QHBoxLayout(host._bar_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        host._bar_row_box = box
        host._bar_row2 = QWidget(host)
        box2 = QHBoxLayout(host._bar_row2)
        box2.setContentsMargins(0, 0, 0, 0)
        box2.setSpacing(6)
        host._bar_row2_box = box2
        host._bar_right = QWidget(host._bar_row2)
        right = QVBoxLayout(host._bar_right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        host._bar_right_box = right
        #: 三个按钮之间的分割线（用户要求「适当给予分割」）
        host._bar_divider_label = QFrame(host._bar_right)
        host._bar_divider_tool = QFrame(host._bar_right)
        for divider in (host._bar_divider_label, host._bar_divider_tool):
            divider.setObjectName("BarDivider")
            divider.setFixedHeight(1)
            divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        #: 分割线两侧的空白：高度由 _sync_bar_gaps() 按缩略图高度算出来
        host._bar_gaps = tuple(QWidget(host._bar_right) for _ in range(4))
        for gap in host._bar_gaps:
            gap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 末尾留一条 stretch：三个按钮的总高只到缩略图下沿，剩下的高度（滚动条
        # 那条）不参与分配，这一块本身仍然撑满卡片条那一行
        right.addStretch(1)

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
        """竖屏两种卡片密度共用账号、布局、设置的竖排位置。"""
        host = self.host
        host._bar_right_box.setDirection(QBoxLayout.TopToBottom)
        host._bar_right_box.setSpacing(0)
        tool_box = host.tool_row.layout()
        tool_box.setDirection(QBoxLayout.TopToBottom)
        tool_box.setSpacing(0)
        for widget in (*host._bar_gaps, host._bar_divider_label, host._bar_divider_tool):
            widget.setVisible(True)
        host.layout_button.setText("布局预设")
        for button in (host.layout_button, host.picture_in_picture_button, host.settings_button):
            button.setMaximumWidth(16_777_215)
        host.tool_row.setMinimumWidth(0)
        host.tool_row.setMaximumWidth(16_777_215)
        host._sync_bar_gaps()

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
        """竖屏：把横栏排成两行。

        第一行：logo（圆点 + 「DD监控室CE」）+ 搜索框（收起时换成头排）
        + 多选/外观/刷新三个小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块，那块里「账号 / 布局预设 / 设置」竖排、
        中间两条 1px 分割线 —— 三个按钮 + 两条线正好把卡片条那一行的高度分完，
        不占第一行的地方（用户要求：加起来和左侧展开关注栏同高，别占用别处）。
        """
        host = self.host
        host._ensure_bar_row()
        if not host._bar_in_use:
            index = host._layout.indexOf(host._header_row)
            for widget in (host._header_row, host.search, host._head_scroll,
                           host.batch_bar, host.batch_button, host.notification_button,
                           host.appearance_button, host.refresh_button, host.clear_wall_button, host.toggle_button):
                host._detach_from_rows(widget)
                widget.setParent(host._bar_row)
            # 左边是 logo，然后是搜索框（收起时换成头像排）、多选条、图标、展开键。
            # 多选条和搜索框轮流坐第一行：**不额外占一行**，横栏高度不变，
            # 画面墙就不会因为点「多选」抖一下（用户报的）。
            host._bar_row_box.addWidget(host._header_row)
            host._bar_row_box.addWidget(host.search, 1)
            host._bar_row_box.addWidget(host._head_scroll, 1)
            host._bar_row_box.addWidget(host.batch_bar, 1)
            for widget in host._bar_icons() + (host.toggle_button,):
                host._bar_row_box.addWidget(widget)
            # 第一行的高度固定成标准控件那一档（多选条里的删除/取消就是原来那两个
            # 按钮，压矮了圆角就和样式表对不上）。固定住之后，搜索框和多选条谁在
            # 这一行里都一样高 —— 点「多选」不会让横栏变高、画布不抖。
            host._bar_row.setFixedHeight(host.batch_bar.sizeHint().height())

            host._detach_from_rows(host.scroll)
            host._detach_from_rows(host.tool_row)
            host.scroll.setParent(host._bar_row2)
            host._bar_row2_box.addWidget(host.scroll, 1)
            host._bar_row2_box.addWidget(host._bar_right)
            # 右边那一块：账号 / 空白 / 分割线 / 空白 / 工具行。
            # 三个按钮都用横屏那套自然高度，两条空白（含中间的 1px 线）一样高，
            # 最上面、最下面的按钮正好贴着卡片条那一行的上下沿。
            host._place_account(True)
            host._bar_right_box.insertWidget(1, host._bar_gaps[0])
            host._bar_right_box.insertWidget(2, host._bar_divider_label)
            host._bar_right_box.insertWidget(3, host._bar_gaps[1])
            host._bar_right_box.insertWidget(4, host.tool_row)
            host._apply_bar_block_stretches()
            tool_box = host.tool_row.layout()
            tool_box.setDirection(QBoxLayout.TopToBottom)
            tool_box.setSpacing(0)
            tool_box.insertWidget(1, host._bar_gaps[2])
            tool_box.insertWidget(2, host._bar_divider_tool)
            tool_box.insertWidget(3, host._bar_gaps[3])
            # 两个按钮自己不吃 stretch（横屏时布局预设是 stretch 1）
            tool_box.setStretch(0, 0)
            tool_box.setStretch(4, 0)
            host._sync_bar_gaps()
            # 三个按钮左右长度一样（都撑满这一块）；高度用横屏那套自然高度
            for button in (host.layout_button, host.picture_in_picture_button, host.settings_button):
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            host._layout.insertWidget(index + 1 if index >= 0 else 1, host._bar_row)
            host._layout.insertWidget(index + 2 if index >= 0 else 2, host._bar_row2)
            host._bar_in_use = True
            host._sync_bar_icons()
        host._bar_row.setVisible(True)

    def release_bar_row(self) -> None:
        """回左栏：把这两行拆掉，控件按 __init__ 里的原始顺序挂回竖排布局。"""
        host = self.host
        if not host._bar_in_use:
            return
        for row in (host._bar_row, host._bar_row2):
            host._layout.removeWidget(row)
            row.setVisible(False)
        for widget in host._bar_widgets() + [host.scroll, host._header_row]:
            host._detach_from_rows(widget)
        for widget in host._column_order:
            host._detach_from_rows(widget)
            host._layout.addWidget(widget)
        # 布局预设 / 设置回到横排一行，把竖排时插进去的空白和分割线拿出来
        tool_box = host.tool_row.layout()
        tool_box.removeWidget(host._bar_divider_tool)
        for gap in host._bar_gaps[2:]:
            tool_box.removeWidget(gap)
        tool_box.setDirection(QBoxLayout.LeftToRight)
        tool_box.setStretch(0, 1)
        tool_box.setSpacing(6)
        for gap in host._bar_gaps[:2]:
            host._bar_right_box.removeWidget(gap)
        for button, policy in host._tool_button_policies.items():
            button.setSizePolicy(policy)
            button.setMaximumWidth(16_777_215)   # 竖屏时按自身宽度限过
        host.layout_button.setText("布局预设")
        host.tool_row.setMinimumWidth(0)
        host.tool_row.setMaximumWidth(16_777_215)
        # 多选条回左栏：高度限制解掉，按钮恢复样式表那套高度
        host._bar_row.setMinimumHeight(0)
        host._bar_row.setMaximumHeight(16_777_215)
        host.batch_bar.setMinimumHeight(0)
        host.batch_bar.setMaximumHeight(16_777_215)
        for button in (host.delete_button, host.cancel_button):
            button.setMinimumHeight(0)
            button.setMaximumHeight(16_777_215)
        host.account_row.setSizePolicy(host._account_policy)
        host._bar_in_use = False
        host._sync_account_row_shape()          # 账号条恢复原来的固定高度
        host._sync_account_row_width()          # 左栏的账号条恢复撑满

    def account_row_should_show(self) -> bool:
        """账号按钮什么时候露出来。

        用户 2026-09-18：**没登录也要露**（显示「登录」，点了弹扫码登录）；
        登录后横屏在侧栏底部、竖屏在横栏右侧那一块 / 收起态头像排旁边。
        """
        host = self.host
        return not host.select_mode

    def sync_account_row_shape(self) -> None:
        """账号条的形状跟着「横屏/竖屏 + 收起/展开」走。

        竖屏收起时横栏只有 36px 高，账号头像要按头排头像的尺寸（34）挤进去；
        竖屏展开时它在右侧那一块里，高度就用横屏那套（34），多出来的高度留给
        两条空白；其它情况沿用原来的样子。
        """
        host = self.host
        if host.side == "top" and not host.collapsed:
            host.account_row.set_compact(False)
            # 高度用横屏那套（34），宽度跟着这一块走（三个按钮左右一样长）
            host.account_row.setFixedHeight(theme.CONTROL_HEIGHT)
            host.account_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        elif host.side == "top":
            host.account_row.set_compact(True, avatar=RoomStrip.AVATAR, margin=1)
        else:
            host.account_row.set_compact(host.collapsed)

    def sync_account_row_width(self) -> None:
        """横栏里的账号条宽度。

        展开时放得下昵称（否则会被挤成「A…」）；收起时它就是一个和头排头像
        一样大的小圆点 —— 不这么算的话它会一直沿用昵称的宽度，变成一条长胶囊。
        横屏时它本来就撑满侧栏，不需要这个限制。
        """
        host = self.host
        row = host.account_row
        if host.side != "top":
            row.setMinimumWidth(0)
            row.setMaximumWidth(16_777_215)
            return
        row.setMaximumWidth(16_777_215)
        if host.collapsed:
            row.setMinimumWidth(row.avatar.width() + 2)
            return
        box = row._layout
        margins = box.contentsMargins()
        # +8：留一点余量，正好卡着算出来的宽度会让昵称尾字差几个像素被省略
        need = (margins.left() + margins.right() + box.spacing() * 2
                + row.avatar.width() + max(row.name.sizeHint().width(), row.account_id.sizeHint().width())
                + row.arrow.sizeHint().width() + 8)
        row.setMinimumWidth(min(host.ACCOUNT_PILL_MAX, need))

    def sync_top_mode(self) -> None:
        """按 side + collapsed 决定顶部横栏露哪些控件。

        横栏是**一行**：左边搜索框（收起时换成头像排），中间「多选 / 外观 / 刷新」
        三个小图标，右边一块是账号头像 + 布局预设 + 设置 + 展开/收起键；
        下面只剩横向卡片条。头像排在收起时露出来（它就是关注列表）。
        """
        host = self.host
        host._sync_toggle_arrow()          # 竖屏要上下箭头，横屏左右
        if host.side != "top":
            host._sync_appearance_row()
            return
        host._adopt_bar_row()
        host._sync_bar_density()
        host._sync_account_row_shape()
        host._sync_account_row_width()
        header = getattr(host, "_header_row", None)
        toggle = getattr(host, "toggle_button", None)
        # 展开时收起头排（用户要求展开后不显示头像排，那点高度留给卡片）；
        # 收起时它顶掉搜索框的位置，一行摆满关注头像
        host._head_scroll.setVisible(host.collapsed)
        # 账号头像：展开时在卡片条右边那一块里，收起时回到第一行最右端
        host._place_account(not host.collapsed)
        host._bar_right.setVisible(not host.collapsed)
        host._bar_row2.setVisible(not host.collapsed)
        if toggle is not None:
            # 摘到横栏这一行的右端常驻；换成紧凑样式，
            # 否则标题行那套 24px 最小尺寸 + padding 会把横栏撑高一截
            toggle.setObjectName("BarToggle")
            toggle.setFixedSize(22, 22)
            if toggle.parentWidget() is not host._bar_row:
                toggle.setParent(host._bar_row)
                host._bar_row_box.addWidget(toggle)
            toggle.setVisible(True)
            _repolish(toggle)
        if host.collapsed:
            if header is not None:
                header.setVisible(False)
            # 收起时这一行只剩：头像排 + 账号头像 + 展开键
            for widget in (host.search, host.status_row, host.scroll, host.normal_bar,
                           host.batch_bar, host.tool_row) + host._bar_icons():
                widget.setVisible(False)
            host.account_row.setVisible(host._account_row_should_show())
        else:
            # 标题行留在第一行最前面当 logo（用户要求左侧给 logo 留位置）：
            # 只露「DD监控室CE」，副标题藏起来；搜索框因此短了一截
            if header is not None:
                header.setVisible(True)
            host._show_logo_title()
            # 第一行：平时是搜索框 + 三个图标；进多选态就让多选条顶掉它们，
            # 这一行的高度不变 —— 点「多选」时画面墙不会跟着抖（用户报的）
            select = host.select_mode
            host.search.setVisible(not select)
            host.batch_bar.setVisible(select)
            for button in host._bar_icons():
                button.setVisible(not select)
            host.batch_button.setVisible(True)
            # 排序/刷新已经在搜索那一行当图标了，「关注中 · N」那一行不再出来
            host.status_row.setVisible(False)
            host.scroll.setVisible(True)
            # 导入关注 / 添加直播间收进账号菜单，别再占一行
            host.normal_bar.setVisible(False)
            host.account_row.setVisible(host._account_row_should_show())
            host.tool_row.setVisible(True)           # 布局预设 + 设置并排
            host.settings_button.setVisible(True)
            host._apply_scroll_axis()
        host._sync_appearance_row()

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

    def toggle_collapsed(self) -> None:
        host = self.host
        host.set_collapsed(not host.collapsed)

    def sync_toggle_arrow(self) -> None:
        """收起键的箭头方向：横屏左右、竖屏上下（用户要求）。"""
        host = self.host
        toggle = getattr(host, "toggle_button", None)
        if toggle is None:
            return
        if hasattr(toggle, "set_orientation"):
            toggle.set_orientation(host.side == "top", host.collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        """一次提交完整布局；保留 animate 参数供既有调用方使用。"""
        host = self.host
        if collapsed == host.collapsed:
            return
        if host.side == "top":
            host.collapsed = collapsed
            # 竖屏：宽度始终撑满，收起/展开只影响露出哪些控件。
            host._layout.setContentsMargins(10, 8, 10, 8)
            host._sync_top_mode()
            if not collapsed:
                for item in host._items:
                    item.set_compact(False)
                host.list_box.relayout(animate=False)
            host.collapsedChanged.emit(collapsed)
            return

        updates_enabled = host.updatesEnabled()
        items = host._items
        host.setUpdatesEnabled(False)
        host._collapse_animating = True
        host.collapseAnimationChanged.emit(True)
        prepared = False
        try:
            for item in items:
                item.thumb.stop()
                item.thumb.set_cover_hold(True)
            host.collapsed = collapsed
            host._apply_collapsed_controls()
            host._finish_collapse(
                (theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH) + RAIL_WIDTH)
            prepared = True
        finally:
            host._collapse_animating = False
            for item in items:
                item.thumb.set_cover_hold(False)
            try:
                host.setUpdatesEnabled(updates_enabled)
                if prepared and updates_enabled and host.isVisible():
                    # 左栏完整绘制后才调整原生视频窗口，避免缩放开销卡住左栏显示。
                    host.repaint()
            finally:
                host.collapseAnimationChanged.emit(False)
        host.collapsedChanged.emit(collapsed)

    def apply_collapsed_controls(self) -> None:
        """在暂停绘制期间对齐控件与条目的最终显示状态。"""
        host = self.host
        collapsed = host.collapsed
        for widget in (host.search, host.status_row, host.normal_bar, host.batch_bar,
                       host.logo_label, host.batch_button, host.tool_row):
            widget.setVisible(not collapsed and (widget is not host.batch_bar or host.select_mode))
        host._sync_account_row_shape()
        host.account_row.setVisible(host._account_row_should_show())
        # 窄条里列表一出现滚动条就会把内容挤窄，上下两排头像就对不齐了；
        # 收起时干脆不显示滚动条，滚轮照样能滚
        host.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if collapsed else Qt.ScrollBarAlwaysOn)
        for index in range(host.title_box.count()):
            widget = host.title_box.itemAt(index).widget()
            if widget:
                widget.setVisible(not collapsed)
        host._layout.setContentsMargins(8 if collapsed else 12, 14, 8 if collapsed else 12, 12)
        host._sync_toggle_arrow()
        host._sync_appearance_row()
        for item in host._items:
            item.set_compact(collapsed)
        host.list_box.relayout(animate=False)

    def finish_collapse(self, target: int) -> None:
        """恢复绘制前完成最终几何与可见封面，屏外封面滚入时再补。"""
        host = self.host
        host.setFixedWidth(target)
        if host.parentWidget() is not None:
            layout = host.parentWidget().layout()
            if layout is not None:
                layout.activate()
        host._outer_layout.activate()
        host._layout.activate()
        host._collapse_animating = False
        host.list_box.relayout(animate=False)
        for item in host._items:
            item.layout().activate()
            item.thumb.set_cover_hold(False)
            if not item.thumb.visibleRegion().isEmpty():
                item.thumb.refresh_cover()
            item.thumb.update()
        for card in host._smart_cards.values():
            card.update()
