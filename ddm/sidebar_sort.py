"""Follow ordering and pins; the sidebar owns cards, folder data and watch history."""
from PySide6.QtGui import QActionGroup

from . import follow_folders
from .watch_history import SORT_TIP


class SidebarSort:
    def __init__(self, host):
        self.host = host

    def full_drop_index(self, visible_index: int) -> int:
        """搜索过滤时把屏幕上的落点换算为完整列表下标。"""
        host = self.host
        visible = host.visible_items()
        if not visible:
            return len(host._items)
        if visible_index >= len(visible):
            return host._items.index(visible[-1]) + 1
        return host._items.index(visible[max(0, visible_index)])

    def reordered_items(self, room_ids: list[str], drop_index: int) -> list:
        """将选中项作为一组移动；置顶和普通项分别留在自己的区域。"""
        host = self.host
        moving = set(room_ids)
        result = []
        groups = [[item for item in host._items if item.is_pinned == pinned
                   and host.folder_for(str(item.room.get("room_id"))) == folder["id"]]
                  for folder in host.folders for pinned in (True, False)]
        for group in groups:
            start = host._items.index(group[0]) if group else 0
            target = max(0, min(drop_index - start, len(group)))
            before = sum(str(item.room.get("room_id")) not in moving
                         for item in group[:target])
            remaining = [item for item in group
                         if str(item.room.get("room_id")) not in moving]
            selected = [item for item in group
                        if str(item.room.get("room_id")) in moving]
            result.extend(remaining[:before] + selected + remaining[before:])
        return result

    def reorder_item(self, room_id: str, drop_index: int) -> bool:
        host = self.host
        return host.reorder_items([str(room_id)], drop_index)

    def reorder_items(self, room_ids: list[str], drop_index: int) -> bool:
        """按当前顺序整体移动卡片，并立即保存自定义顺序。"""
        host = self.host
        known = {str(item.room.get("room_id")) for item in host._items}
        if not known.intersection(room_ids):
            return False
        items = host._reordered_items(room_ids, drop_index)
        if [str(entry.room.get("room_id")) for entry in items] == \
                [str(entry.room.get("room_id")) for entry in host._items]:
            return False
        pinned_before = list(host.pinned)
        host._items = items
        host.pinned = [str(entry.room.get("room_id")) for entry in items if entry.is_pinned]
        changed_folders = {host.folder_for(rid) for rid in room_ids}
        for folder in host.folders:
            if folder["id"] in changed_folders:
                host._remember_folder_order(folder["id"])
                folder["sort"] = "custom"
        host.sort_mode = host.default_folder()["sort"]
        host._sync_watch_history_mode()
        host.list_box.relayout(animate=True)
        host.refresh_strip()
        if host.pinned != pinned_before:
            host.pinChanged.emit(list(host.pinned))
        host.orderChanged.emit()
        return True

    def apply_pins(self, pinned: list) -> None:
        """置顶的先显示在前面（顺序按置顶列表）。"""
        host = self.host
        host.pinned = [str(item) for item in pinned]
        for item in host._items:
            item.set_pinned(str(item.room.get("room_id")) in host.pinned)
        host.resort(animate=False)

    def sync_watch_history_mode(self, *, refresh=False):
        host = self.host
        current = {folder["id"] for folder in host.folders if folder["sort"] == "frequent"}
        host.watch_history.set_enabled(bool(current))
        if refresh or current - host._frequent_folders:
            host._frequent_scores = host.watch_history.scores()
        host._frequent_folders = current

    def refresh_frequent_order(self):
        host = self.host
        host._frequent_scores = host.watch_history.scores()
        host.resort(animate=False)

    def add_folder_sort_menu(self, menu, folder) -> None:
        host = self.host
        menu.setToolTipsVisible(True)
        group = QActionGroup(menu)
        group.setExclusive(True)
        for mode, label in host.SORT_MODES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == folder["sort"])
            if mode == "frequent":
                action.setToolTip(SORT_TIP)
            action.triggered.connect(lambda _checked=False, value=mode, fid=folder["id"]:
                                     host.set_folder_sort(fid, value))
            group.addAction(action)
        menu.addSeparator()
        menu.addAction("固定当前显示顺序").triggered.connect(
            lambda: host.freeze_current_order(folder["id"]))

    def freeze_current_order(self, folder_id="") -> None:
        """把当前看到的顺序保存为自定义顺序。"""
        host = self.host
        folder_id = folder_id or host.default_folder()["id"]
        host._remember_folder_order(folder_id)
        host.set_folder_sort(folder_id, "custom")

    def remember_folder_order(self, folder_id: str) -> None:
        host = self.host
        current = [str(item.room.get("room_id")) for item in host._items
                   if host.folder_for(str(item.room.get("room_id"))) == folder_id]
        ordered = iter(current)
        host.custom_order = [next(ordered) if rid in current else rid for rid in host.custom_order]

    def set_folder_sort(self, folder_id: str, mode: str, notify=True) -> None:
        host = self.host
        folder = host.get_folder(folder_id)
        if folder is None:
            return
        folder["sort"] = mode if mode in dict(host.SORT_MODES) else "custom"
        host._sync_watch_history_mode(refresh=mode == "frequent")
        host.resort(animate=False)
        if notify:
            host.foldersChanged.emit()

    def set_sort_mode(self, mode: str, notify: bool = True) -> None:
        """切排序方式：自定义 / 开播优先 / 导入顺序。"""
        host = self.host
        if mode not in dict(host.SORT_MODES):
            mode = "custom"
        host.sort_mode = mode
        host.set_folder_sort(host.default_folder()["id"], mode, notify=False)
        if notify:
            host.sortChanged.emit(mode)

    def set_import_order(self, order: list | None) -> None:
        """导入顺序（配置里存的）；没存过就按当前列表顺序算。"""
        host = self.host
        known = [str(item) for item in (order or [])]
        for item in host._items:
            room_id = str(item.room.get("room_id"))
            if room_id not in known:
                known.append(room_id)
        host.import_order = known
        host.resort(animate=False)

    def set_custom_order(self, order: list | None) -> None:
        """自定义顺序（配置里存的）；没存过的房间按当前列表顺序补在后面。"""
        host = self.host
        known = list(dict.fromkeys(str(entry) for entry in (order or [])))
        for item in host._items:
            room_id = str(item.room.get("room_id"))
            if room_id not in known:
                known.append(room_id)
        present = {str(item.room.get("room_id")) for item in host._items}
        host.custom_order = [room_id for room_id in known if room_id in present]
        host.resort(animate=False)

    def resort(self, animate: bool = False, *, duration=150, revealing=(), viewport_only=False) -> None:
        """每个文件夹独立排序，置顶只作用于所在文件夹。"""
        host = self.host
        host.sort_mode = host.default_folder()["sort"]
        host._folder_assignments = follow_folders.assign_folders(
            host.rooms(), host.folders, host._folder_pending)
        pinned_ids = list(host.pinned)
        ordered = []
        for folder in host.folders:
            members = [item for item in host._items
                       if host.folder_for(str(item.room.get("room_id"))) == folder["id"]]
            pinned = [item for rid in pinned_ids for item in members if str(item.room.get("room_id")) == rid]
            rest = [item for item in members if str(item.room.get("room_id")) not in pinned_ids]
            order = host.import_order if folder["sort"] == "imported" else host.custom_order
            position = {rid: index for index, rid in enumerate(order)}
            def key(item):
                index = position.get(str(item.room.get("room_id")), len(position))
                if folder["sort"] == "frequent":
                    return (not bool(item.room.get("live")),
                            -host._frequent_scores.get(str(item.room.get("room_id")), 0), index)
                if folder["sort"] in ("live", "offline"):
                    return (bool(item.room.get("live")) != (folder["sort"] == "live"), index)
                if folder["sort"] == "name":
                    return (str(item.room.get("uname") or "").casefold(), index)
                return index
            rest.sort(key=key)
            ordered.extend(pinned + rest)
        host._items = ordered
        # 先按搜索词重算谁该藏起来，再摆位置 —— 顺序反了会留下「藏起来的还占位」
        host._apply_filter_marks()
        host.list_box.relayout(animate=animate, duration=duration, revealing=revealing,
                              viewport_only=viewport_only)
        host._sync_count()             # 过滤时这里写成「露出来几路 / 一共几路」
        # 顺手把顶部横栏那一排头像也刷新：竖屏下它就是关注列表
        host.refresh_strip()

    def toggle_pin(self, room: dict) -> None:
        host = self.host
        room_id = str(room.get("room_id"))
        if room_id in host.pinned:
            host.pinned.remove(room_id)
        else:
            host.pinned.append(room_id)
        host.apply_pins(host.pinned)
        host.pinChanged.emit(list(host.pinned))
