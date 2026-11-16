"""Sidebar collapse and expansion coordination; original Sidebar owns animation and timers."""
from PySide6.QtCore import Qt
from . import theme
from .sidebar_navigation import RAIL_WIDTH
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from . import follow_folders, layouts, motion, theme, version as version_module


class SidebarCollapse:
    def __init__(self, host):
        self.host = host

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
