"""Sidebar orientation, borrowed controls and collapse layout; state stays on the widget."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .avatar_widgets import RoomStrip
from .sidebar_navigation import RAIL_WIDTH
from .ui.toolbar import BarIconButton
from .widget_support import NAV_ITEM_GAP, NAV_ITEM_HEIGHT, _repolish
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QCursor, QKeySequence, QPainter, QPen, QPixmap, QRegion, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QVBoxLayout, QWidget
)
from . import follow_folders, layouts, motion, theme, version as version_module
from .sidebar_orientation import SidebarOrientation
from .sidebar_collapse import SidebarCollapse
from .sidebar_layout_picker import SidebarLayoutPicker


class SidebarPresentation:
    def __init__(self, host):
        self.host = host
        self.layout_picker = SidebarLayoutPicker(self.host)
        self.collapse = SidebarCollapse(self.host)
        self.orientation = SidebarOrientation(self.host)

    def set_side(self, side: str) -> None:
        """摆放方式：left = 横屏的左栏（默认）；top = 竖屏的顶部横栏。

        竖屏下侧栏变成一条顶部横栏：宽度撑满、搜索框变宽、列表只留一行头像
        （收起时只剩头像，展开时多一行按钮），逻辑和横屏的收起/展开一致。
        """
        return self.orientation.set_side(side)

    def restore_toggle_to_header(self) -> None:
        """把「收起/展开」按钮放回标题行（竖屏时它是摘出来放在横栏右上角的）。"""
        return self.orientation.restore_toggle_to_header()

    def detach_from_rows(self, widget: QWidget) -> None:
        """把控件从「竖排布局」和横栏那两个容器里都摘出来。"""
        return self.orientation.detach_from_rows(widget)

    def ensure_bar_row(self) -> None:
        """建出横栏的两行容器（只建一次）。

        第一行：logo + 搜索框（收起时换成头像排）+ 多选/外观/刷新小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块（账号 / 布局预设 / 设置 竖排）。
        右侧那一块只占第二行，不侵占第一行的地方（用户要求）；高度就是卡片条
        那一行的高度，三个按钮 + 两条分割线把它正好分完。
        """
        return self.orientation.ensure_bar_row()

    def bar_widgets(self) -> list:
        """竖屏时会被横栏借走的控件（横屏要按原样挂回去）。"""
        return self.orientation.bar_widgets()

    def place_account(self, in_right_block: bool) -> None:
        """账号头像的位置：展开时在整块里排第一，收起时回到第一行最右端。"""
        return self.orientation.place_account(in_right_block)

    def sync_bar_gaps(self) -> None:
        """算两条空白的高度。

        目标是让**最下面的按钮下沿和直播间缩略图的下沿齐平**，所以减的是缩略图
        高度（`NAV_ITEM_HEIGHT`），不是整条卡片行 —— 卡片行还含那 8px 滚动条。
        三个按钮各用横屏那套高度，两条线各 1px，剩下的**均分**给两条空白。
        """
        return self.orientation.sync_bar_gaps()

    def sync_bar_density(self) -> None:
        """竖屏两种卡片密度共用账号、布局、设置的竖排位置。"""
        return self.orientation.sync_bar_density()

    def apply_bar_block_stretches(self) -> None:
        """账号和工具行自己不占 stretch（高度全由按钮 + 空白算出来）。

        每次挪动账号都要重设：`insertWidget` / `removeWidget` 会让布局里其它项
        的下标平移。
        """
        return self.orientation.apply_bar_block_stretches()

    def bar_icons(self) -> tuple:
        """横栏里当小图标用的三个按钮（横屏时它们各有各的文字位置）。"""
        return self.orientation.bar_icons()

    def sync_bar_icons(self) -> None:
        """竖屏工具统一用图标；横屏多选仍为紧凑图标。"""
        return self.orientation.sync_bar_icons()

    def restore_side_children(self) -> None:
        """回左栏：多选图标与外观、刷新一起回状态行。"""
        return self.orientation.restore_side_children()

    def adopt_bar_row(self) -> None:
        """竖屏：把横栏排成两行。

        第一行：logo（圆点 + 「DD监控室CE」）+ 搜索框（收起时换成头排）
        + 多选/外观/刷新三个小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块，那块里「账号 / 布局预设 / 设置」竖排、
        中间两条 1px 分割线 —— 三个按钮 + 两条线正好把卡片条那一行的高度分完，
        不占第一行的地方（用户要求：加起来和左侧展开关注栏同高，别占用别处）。
        """
        return self.orientation.adopt_bar_row()

    def release_bar_row(self) -> None:
        """回左栏：把这两行拆掉，控件按 __init__ 里的原始顺序挂回竖排布局。"""
        return self.orientation.release_bar_row()

    def account_row_should_show(self) -> bool:
        """账号按钮什么时候露出来。

        用户 2026-09-18：**没登录也要露**（显示「登录」，点了弹扫码登录）；
        登录后横屏在侧栏底部、竖屏在横栏右侧那一块 / 收起态头像排旁边。
        """
        return self.host.account_control.account_row_should_show()

    def sync_account_row_shape(self) -> None:
        """账号条的形状跟着「横屏/竖屏 + 收起/展开」走。

        竖屏收起时横栏只有 36px 高，账号头像要按头排头像的尺寸（34）挤进去；
        竖屏展开时它在右侧那一块里，高度就用横屏那套（34），多出来的高度留给
        两条空白；其它情况沿用原来的样子。
        """
        return self.host.account_control.sync_account_row_shape()

    def sync_account_row_width(self) -> None:
        """横栏里的账号条宽度。

        展开时放得下昵称（否则会被挤成「A…」）；收起时它就是一个和头排头像
        一样大的小圆点 —— 不这么算的话它会一直沿用昵称的宽度，变成一条长胶囊。
        横屏时它本来就撑满侧栏，不需要这个限制。
        """
        return self.host.account_control.sync_account_row_width()

    def sync_top_mode(self) -> None:
        """按 side + collapsed 决定顶部横栏露哪些控件。

        横栏是**一行**：左边搜索框（收起时换成头像排），中间「多选 / 外观 / 刷新」
        三个小图标，右边一块是账号头像 + 布局预设 + 设置 + 展开/收起键；
        下面只剩横向卡片条。头像排在收起时露出来（它就是关注列表）。
        """
        return self.orientation.sync_top_mode()

    def show_logo_title(self) -> None:
        """竖屏横栏只挂紧凑 Logo，不改变原有第一行高度。"""
        return self.orientation.show_logo_title()

    def set_brand_header(self, compact: bool) -> None:
        """横屏显示 Logo + 名称；紧凑横栏只显示 Logo。"""
        return self.orientation.set_brand_header(compact)

    def apply_scroll_axis(self) -> None:
        """竖屏横栏里关注列表是横向卡片条：左右滚，只占一条高度。"""
        return self.orientation.apply_scroll_axis()

    def toggle_collapsed(self) -> None:
        return self.collapse.toggle_collapsed()

    def sync_toggle_arrow(self) -> None:
        """收起键的箭头方向：横屏左右、竖屏上下（用户要求）。"""
        return self.collapse.sync_toggle_arrow()

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        """一次提交完整布局；保留 animate 参数供既有调用方使用。"""
        return self.collapse.set_collapsed(collapsed, animate)

    def apply_collapsed_controls(self) -> None:
        """在暂停绘制期间对齐控件与条目的最终显示状态。"""
        return self.collapse.apply_collapsed_controls()

    def finish_collapse(self, target: int) -> None:
        """恢复绘制前完成最终几何与可见封面，屏外封面滚入时再补。"""
        return self.collapse.finish_collapse(target)

    def sync_appearance_row(self):
        host = self.host
        host.workspace_controls.sync_layout()
        host._sync_selection_controls()
        host.appearance_button.setVisible(not host.collapsed)
        if host.side == "left":
            host.status_row.setVisible(not host.collapsed)
            for widget in (host.count_label, host.batch_button, host.notification_button, host.refresh_button):
                widget.setVisible(not host.collapsed)
            host.status_row.layout().setAlignment(host.appearance_button,
                Qt.AlignHCenter if host.collapsed else Qt.AlignRight)
        host.navigation.sync()

    def set_layout_name(self, layout_id: str) -> None:
        """按钮只写「布局预设」，当前用的是哪套放在悬停提示里。"""
        return self.layout_picker.set_layout_name(layout_id)

    def open_layout_picker(self) -> None:
        # 只列当前方向能用的布局：横屏不列竖屏预设（套上去画面会变形）
        return self.layout_picker.open_layout_picker()

    def on_layout_chosen(self, layout_id: str) -> None:
        return self.layout_picker.on_layout_chosen(layout_id)

    def focus_room_list(self) -> None:
        """回车：把焦点从搜索框让给列表，接着就能直接点选 / 拖动。"""
        return self.host.interaction_control.focus_room_list()

    def focus_search(self) -> None:
        """Ctrl+F：展开关注栏并把输入焦点交给搜索框。"""
        return self.host.interaction_control.focus_search()
