"""Follow-list filtering; the sidebar owns folder assignments and selection state."""
from . import follow_folders
from .search import matches_text


class SidebarFilter:
    def __init__(self, host):
        self.host = host

    def apply_filter(self, text: str) -> None:
        """搜索框一有动静就过滤；批量删除的勾选状态不受影响。"""
        host = self.host
        wanted = (text or "").strip().lower()
        if wanted == host.filter_text:
            return
        host.clear_sort_selection()
        host.filter_text = wanted
        host.refresh_filter()

    def refresh_filter(self) -> None:
        """按当前搜索词重算谁该露出来（状态刷新、增删、换排序之后都要走一遍）。"""
        host = self.host
        host._apply_filter_marks()
        host.list_box.relayout(animate=False)
        host.refresh_strip()
        host._sync_count()

    def apply_filter_marks(self) -> None:
        """只更新「谁被过滤掉了」，不动位置 —— 由调用方决定什么时候重排。"""
        host = self.host
        words = host.filter_text.split()
        host._folder_assignments = follow_folders.assign_folders(
            host.rooms(), host.folders, host._folder_pending)
        for item in host._items:
            folder = host.get_folder(host.folder_for(str(item.room.get("room_id"))))
            folded = folder and folder["collapsed"] and (
                not words or folder["id"] in host._folders_folded_by_drag)
            item.set_filtered_out(bool(folded) or not host.matches(item, words))
            if folded:
                host._sort_selected_ids.discard(str(item.room.get("room_id")))
                item.set_sort_selected(False)
                item.check.setChecked(False)

    def matches(self, item, words: list[str], folder_id=None) -> bool:
        """主播名 / 房间号 / 文件夹名，大小写不敏感；多个词必须全匹配。"""
        host = self.host
        if host.live_only and not item.room.get('live'):
            return False
        if not words:
            return True
        room = item.room
        haystack = " ".join(str(room.get(key) or "")
                            for key in ("uname", "room_id", "display_room_id")).lower()
        folder_id = folder_id or host.folder_for(str(room.get("room_id")))
        haystack += " " + next((folder["name"].lower() for folder in host.folders
                                if folder["id"] == folder_id), "")
        return all(matches_text(haystack, word) for word in words)

    def visible_items(self) -> list:
        """当前露在外面的条目（过滤掉的不算）。"""
        host = self.host
        items = [item for item in host._items if not item.filtered_out]
        return [item for folder in host.folders for item in items
                if host.folder_for(str(item.room.get("room_id"))) == folder["id"]]

    def empty_hint_text(self) -> str:
        """列表一条都露不出来时说的话（列表区就摆它一个）。"""
        host = self.host
        if host.filter_text:
            return f"没有匹配「{host.filter_text}」的直播间"
        if host.live_only:
            return '当前没有正在直播的关注'
        return "还没有关注任何直播间"
