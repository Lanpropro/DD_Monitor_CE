"""Follow-card selection coordination; state, signals and controls belong to the sidebar."""
from PySide6.QtCore import Qt


class SidebarSelection:
    def __init__(self, host):
        self.host = host

    def sync_selection_controls(self):
        host = self.host
        host.account_row.setVisible(host._account_row_should_show())
        host.tool_row.setVisible(host.side == 'top' and not host.select_mode and not host.collapsed)
        host.normal_bar.hide()
        if host.select_mode and host.side == 'top':
            host._bar_right.hide()

    def set_select_mode(self, enabled: bool) -> None:
        host = self.host
        host.select_mode = enabled
        if enabled:
            host.clear_sort_selection()
        host.batch_button.setChecked(enabled)
        if enabled and host.filter_text:
            # 进多选就把搜索清掉：藏起来的条目也还在「已选」里，批量删太危险
            host.search.clear()
        # 竖屏时 batch_bar 被借到横栏第一行里（见 _adopt_bar_row），
        # 露不露由 _sync_top_mode 统一决定，这里只管横屏那一列。
        if host.side != "top":
            host.batch_bar.setVisible(enabled and not host.collapsed)
            host.normal_bar.setVisible(not enabled and not host.collapsed)
        else:
            host._sync_top_mode()
        for item in host._items:
            item.set_select_mode(enabled and not host.collapsed)
        host._sync_selection_controls()
        host._update_batch_label()

    def update_batch_label(self) -> None:
        host = self.host
        count = sum(1 for item in host._items if item.is_checked())
        host.batch_label.setText(f"已选 {count} 个")
        host._sync_sort_selection()

    def emit_delete(self) -> None:
        host = self.host
        chosen = [item.room for item in host._items if item.is_checked()]
        if chosen:
            host.deleteRequested.emit(chosen)
        host.set_select_mode(False)

    def selected_sort_ids(self) -> list[str]:
        host = self.host
        if host.select_mode:
            return [str(item.room.get("room_id")) for item in host._items
                    if item.is_checked() and not item.filtered_out]
        return [str(item.room.get("room_id")) for item in host._items
                if str(item.room.get("room_id")) in host._sort_selected_ids]

    def sync_sort_selection(self) -> None:
        host = self.host
        selected = set() if host.select_mode else set(host.selected_sort_ids())
        for item in host._items:
            item.set_sort_selected(str(item.room.get("room_id")) in selected)

    def clear_sort_selection(self) -> None:
        host = self.host
        if host._sort_selected_ids:
            host._sort_selected_ids.clear()
            host._sync_sort_selection()
        host._sort_anchor = None

    def select_sort_item(self, room_id: str, modifiers) -> None:
        """Ctrl 增减选择，Shift 选一段；普通点击回到单卡片操作。"""
        host = self.host
        room_id = str(room_id)
        if modifiers & Qt.ShiftModifier:
            visible = [str(item.room.get("room_id")) for item in host.visible_items()]
            if host._sort_anchor in visible and room_id in visible:
                start, end = sorted((visible.index(host._sort_anchor), visible.index(room_id)))
                chosen = set(visible[start:end + 1])
            else:
                chosen = {room_id}
            host._sort_selected_ids = (host._sort_selected_ids | chosen
                                       if modifiers & Qt.ControlModifier else chosen)
        elif modifiers & Qt.ControlModifier:
            if room_id in host._sort_selected_ids:
                host._sort_selected_ids.remove(room_id)
            else:
                host._sort_selected_ids.add(room_id)
            host._sort_anchor = room_id
        else:
            host._sort_selected_ids.clear()
            host._sort_anchor = room_id
        host._sync_sort_selection()

    def dragged_room_ids(self, room_id: str) -> list[str]:
        """从选中卡片拖动时带上整组；拖动未选中的卡片则只移动它。"""
        host = self.host
        room_id = str(room_id)
        if room_id in host.selected_sort_ids():
            return host.selected_sort_ids()
        if not host.select_mode:
            host.clear_sort_selection()
        return [room_id]

    def move_sort_selection(self, room_id: str, to_front: bool) -> bool:
        host = self.host
        return host.reorder_items(host.dragged_room_ids(room_id),
                                  0 if to_front else len(host._items))
