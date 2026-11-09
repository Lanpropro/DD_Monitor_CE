"""Sidebar pointer and drag presentation; the existing drag session and widget own state."""
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QCursor, QKeySequence, QPainter, QPen, QPixmap, QRegion, QShortcut
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QPushButton, QVBoxLayout, QWidget
)
from .sidebar_item import NavItem
from PySide6.QtCore import Qt


class SidebarInteraction:
    def __init__(self, host):
        self.host = host

    def set_pointer_hover(self, item) -> None:
        host = self.host
        previous = host._pointer_hover_item
        host._pointer_hover_item = item
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

    def sync_pointer_hover(self) -> None:
        # Native child windows can omit Enter as well as Leave. Hit-test once
        # for the whole visible list, including rows without a live preview.
        host = self.host
        item = None
        viewport = host.scroll.viewport()
        if (host.isVisible() and viewport.isVisible()
                and not QApplication.activePopupWidget() and not QApplication.activeModalWidget()):
            pointer = QCursor.pos()
            if viewport.rect().contains(viewport.mapFromGlobal(pointer)):
                child = host.list_box.childAt(host.list_box.mapFromGlobal(pointer))
                while child is not None and child is not host.list_box:
                    if isinstance(child, NavItem):
                        item = child
                        break
                    child = child.parentWidget()
        host._set_pointer_hover(item)

    def prepare_drag_snapshot(self) -> None:
        host = self.host
        if host._drag_snapshot_ready or not host.isVisible():
            return
        if host.drag_session.active or QApplication.mouseButtons() != Qt.NoButton:
            host._drag_snapshot_timer.start(100)
            return
        # Qt render() flushes pending move/resize events across the whole window,
        # including hidden cards. Do this once after show, outside the first drag.
        # Paint only one pixel without children; keep no stale card snapshot.
        pixel = QPixmap(1, 1)
        pixel.fill(Qt.transparent)
        host.render(pixel, QPoint(), QRegion(QRect(0, 0, 1, 1)), QWidget.RenderFlag(0))
        host._drag_snapshot_ready = True

    def drop_index_at(self, global_pos) -> int:
        """全局坐标 -> 列表里的落点下标（给 NavItem 转发拖动用）。"""
        host = self.host
        local = host.list_box.mapFromGlobal(global_pos)
        return host.list_box.index_at(local.x() if host.list_box.horizontal
                                      else local.y())

    def hover_drag(self, room_id: str, global_pos) -> None:
        """拖动过程中：贴近边缘自动滚，并在落点让出一格。"""
        host = self.host
        # 自动滚吃**全局坐标**（它内部按视口算边界）；落点下标要的是**内容坐标**
        # —— 以前把两者混成同一个变量，往下滚就永远触发不了。
        host.list_box.auto_scroll(global_pos)
        local = host.list_box.mapFromGlobal(global_pos)
        along = local.x() if host.list_box.horizontal else local.y()
        host.show_drop_indicator(room_id, host.list_box.index_at(along))

    def finish_drag(self, room_id: str, global_pos) -> None:
        """松手时结算：鼠标还在列表里就按落点排序，否则只把卡片放回去。"""
        host = self.host
        host.list_box.set_scroll_dir(0)
        local = host.list_box.mapFromGlobal(global_pos)
        inside = (0 <= local.x() <= host.list_box.width()
                  and 0 <= local.y() <= host.list_box.height())
        if inside:
            for folder_id, button in host._folder_buttons.items():
                if not button.isHidden() and button.geometry().contains(local):
                    host.move_to_folder(host.dragged_room_ids(room_id), folder_id)
                    return
            along = local.x() if host.list_box.horizontal else local.y()
            host.reorder_items(host.dragged_room_ids(room_id),
                               host._full_drop_index(host.list_box.index_at(along)))
        host.list_box.relayout(animate=True)

    def show_drop_indicator(self, room_id: str | None, drop_index: int) -> None:
        """拖动中：选中卡片藏起来，其余卡片让出整组空位。"""
        host = self.host
        if not room_id:
            host.list_box.relayout(animate=True)
            return
        moving = set(host.dragged_room_ids(room_id))
        items = host._reordered_items(list(moving), host._full_drop_index(drop_index))
        preview = host.folder_entries(items, moving) if host.folders else [
            None if str(item.room.get("room_id")) in moving else item
            for item in items if not item.filtered_out]
        host.list_box.relayout(animate=True, preview_order=preview, dragging_ids=moving)

    def end_drag(self) -> None:
        """拖动结束（放下或者取消）：所有卡片恢复显示并归位。"""
        host = self.host
        host.list_box.set_scroll_dir(0)
        host.list_box.relayout(animate=True)

    def focus_room_list(self) -> None:
        """回车：把焦点从搜索框让给列表，接着就能直接点选 / 拖动。"""
        host = self.host
        host.scroll.setFocus()

    def focus_search(self) -> None:
        """Ctrl+F：展开关注栏并把输入焦点交给搜索框。"""
        host = self.host
        if host.collapsed:
            host.set_collapsed(False, animate=False)
        host.search.setFocus(Qt.ShortcutFocusReason)
        host.search.selectAll()
