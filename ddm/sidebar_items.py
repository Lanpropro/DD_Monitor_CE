"""Follow-card collection, display state and entry effects; the sidebar owns cards and timers."""
import sys
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from . import follow_folders, layouts, motion, theme, version as version_module
from .sidebar_item import NavItem
from .widget_support import (
    BRAND_ASSETS_DIR, NAV_ITEM_GAP, NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT, _repolish
)


class SidebarItems:
    def __init__(self, host):
        self.host = host

    def on_strip_room(self, room_id: str) -> None:
        """点横栏里的头像 = 点列表里那一条（行为和横屏一致）。"""
        host = self.host
        item = next((entry for entry in host._items
                     if str(entry.room.get("room_id")) == str(room_id)), None)
        if item is not None:
            host.roomSelected.emit(item.room)

    def set_room_face(self, room_id: str, pixmap) -> None:
        """某个主播的头像下载好了：头排那一张也换掉（横屏走列表，竖屏走头排）。"""
        host = self.host
        strip = getattr(host, "_head_strip", None)
        if strip is not None:
            strip.set_room_face(room_id, pixmap)

    def refresh_strip(self) -> None:
        """把当前关注列表（连已经下载好的头像）同步到顶部横栏。"""
        host = self.host
        strip = getattr(host, "_head_strip", None)
        if strip is None:
            return
        rooms = []
        faces = {}
        for item in host.visible_items():          # 过滤时头像排也跟着缩
            room = dict(item.room)
            rooms.append(room)
            pixmap = item.thumb.face_pixmap()
            if pixmap is not None:
                faces[str(room.get("room_id") or "")] = pixmap
        strip.set_rooms(rooms, faces, host._wall_room_ids)

    def set_wall_rooms(self, room_ids) -> None:
        """同步画面墙占用状态，供卡片和竖屏头像条显示蓝色标记。"""
        host = self.host
        ids = {str(room_id) for room_id in room_ids if str(room_id)}
        if ids == host._wall_room_ids:
            return
        host._wall_room_ids = ids
        host._refresh_wall_marks()
        host.refresh_strip()

    def refresh_wall_marks(self) -> None:
        """按当前的画面墙占用，重设每张卡片的蓝框。

        列表一变（加 / 删 / 重建）就调一次。`_append_item()` 建卡片时读的是**当时**的
        `_wall_room_ids`，而 `set_wall_rooms()` 有个「没变就直接返回」的短路 ——
        两条路径一交叉，卡片就可能留着一个过期的蓝框（用户报的「刚加进关注栏就被
        标成已在画面墙」）。所以列表动过之后统一重设一遍，状态只有一个来源。
        """
        host = self.host
        for item in host._items:
            item.set_on_wall(str(item.room.get("room_id") or "") in host._wall_room_ids)

    def refresh_visible_covers(self) -> None:
        host = self.host
        if host._collapse_animating:
            return
        for item in host._items:
            if item.thumb._cover_dirty and not item.thumb.visibleRegion().isEmpty():
                item.thumb.refresh_cover()

    def set_card_mode(self, enabled: bool) -> None:
        """切换关注列表样式；侧栏收起时只记录选择，展开后再呈现。"""
        host = self.host
        enabled = bool(enabled)
        if enabled == host.card_mode:
            return
        host.card_mode = enabled
        for item in host._items:
            item.thumb.stop()
            item.set_card_mode(enabled)
            item.set_portrait_strip(host.side == "top" and not enabled)
        host.list_box.relayout(animate=False)
        if host.side == "top" and host._bar_in_use:
            host._sync_top_mode()

    def set_compact_policy(self, card_mode: bool, auto_compact: bool,
                           compact_threshold: int) -> None:
        """保存用户偏好，并按当前关注数量决定实际使用哪种列表。"""
        host = self.host
        host.preferred_card_mode = bool(card_mode)
        host.auto_compact = bool(auto_compact)
        host.compact_threshold = max(2, int(compact_threshold))
        host.set_card_mode(host._effective_card_mode())

    def set_compact_background(self, enabled: bool) -> None:
        host = self.host
        host.compact_background = bool(enabled)
        for item in host._items:
            item.thumb.set_compact_background(enabled)

    def effective_card_mode(self) -> bool:
        """横竖屏共用关注数量阈值，竖屏改为紧凑横向列表。"""
        host = self.host
        return host.preferred_card_mode and not (
            host.auto_compact and len(host._items) >= host.compact_threshold)

    def select_room(self, room: dict) -> None:
        host = self.host
        room_id = str(room.get("room_id") or "")
        for item in host._items:
            item.set_selected(bool(room_id) and str(item.room.get("room_id") or "") == room_id)

    def append_item(self, room: dict, *, item_type) -> NavItem:
        host = self.host
        NavItem = item_type
        item = NavItem(room, len(host._items), parent=host.list_box)
        room_id = str(room.get("room_id"))
        if room_id and room_id not in host.import_order:
            host.import_order.append(room_id)     # 「导入顺序」排序用
        if room_id and room_id not in host.custom_order:
            host.custom_order.append(room_id)     # 新加的房间先排在自定义顺序最后
        item.drop_host = host                 # 列表内部拖动排序
        item.clicked.connect(host.roomSelected.emit)
        item.addRequested.connect(host.addToWallRequested.emit)
        item.removeRequested.connect(host.removeRequested.emit)
        item.openBrowserRequested.connect(host.openBrowserRequested.emit)
        item.checkedChanged.connect(host._update_batch_label)
        item.pinToggled.connect(host.toggle_pin)
        item.hovered.connect(host.previewHovered.emit)
        item.unhovered.connect(host.previewUnhovered.emit)
        item.set_card_mode(host.card_mode)
        item.thumb.set_compact_background(host.compact_background)
        item.set_portrait_strip(host.side == "top" and not host.card_mode)
        item.set_on_wall(room_id in host._wall_room_ids)
        item.set_select_mode(host.select_mode)
        host._items.append(item)
        item_height = NAV_ITEM_HEIGHT if host.card_mode else NAV_LIST_ITEM_HEIGHT
        item.resize(host.list_box.width(), item_height)
        item.show()
        return item

    def add_room(self, room: dict) -> bool:
        host = self.host
        return bool(host.add_rooms([room]))

    def add_rooms(self, rooms: list[dict]) -> list[dict]:
        host = self.host
        known = {str(item.room.get("room_id")) for item in host._items}
        added = []
        for room in rooms:
            room_id = str(room.get("room_id"))
            if room_id in known:
                continue
            known.add(room_id)
            host._folder_pending.add(room_id)
            host._append_item(room)
            added.append(room)
        if not added:
            return []
        host.set_compact_policy(host.preferred_card_mode, host.auto_compact,
                                host.compact_threshold)
        # 新控件初始坐标是 (0, 0)，必须立即排版，否则会压在第一项上，
        # 直到用户拖动列表才恢复。
        host.resort(animate=False)
        host._sync_count()
        host._refresh_wall_marks()      # 新卡片的蓝框按当前墙面重设一次
        host.refresh_strip()
        if host.isVisible() and motion.enabled():
            host._entering_room_ids.update(str(room["room_id"]) for room in added)
            host._card_entry_timer.start(0)
        return added

    def reveal_added_rooms(self) -> None:
        """等批量添加与目标文件夹归类结束，只让新卡片从最终落点滑入。"""
        host = self.host
        entering = {item for item in host._items
                    if str(item.room.get("room_id")) in host._entering_room_ids}
        host._entering_room_ids.clear()
        if entering and host.isVisible() and motion.enabled():
            host.list_box.relayout(animate=True, duration=220, revealing=entering)

    def remove_room(self, room: dict) -> None:
        host = self.host
        item = next((entry for entry in host._items
                     if str(entry.room.get("room_id")) == str(room.get("room_id"))), None)
        if item is None:
            return
        item.hide()
        item.drop_live_alert()
        item.thumb.stop()               # 缩略图里可能正在放预览
        item.thumb.release_player()
        item.setParent(None)
        item.deleteLater()
        host._items.remove(item)
        room_id = str(room.get("room_id"))
        host._folder_pending.discard(room_id)
        for folder in host.folders:
            if room_id in folder["rooms"]:
                folder["rooms"].remove(room_id)
        host._sort_selected_ids.discard(room_id)
        if host._sort_anchor == room_id:
            host._sort_anchor = None
        if room_id in host.import_order:
            host.import_order.remove(room_id)
        if room_id in host.custom_order:
            host.custom_order.remove(room_id)
        host.set_compact_policy(host.preferred_card_mode, host.auto_compact,
                                host.compact_threshold)
        host.refresh_filter()
        host._sync_count()
        host._refresh_wall_marks()      # 删完也重设一次，蓝框状态别留旧账
        host.refresh_strip()

    def rooms(self) -> list[dict]:
        host = self.host
        return [item.room for item in host._items]

    def items(self) -> list[NavItem]:
        host = self.host
        return list(host._items)

    def play_live_alerts(self, items: list) -> None:
        """重排之后再播开播动效。

        调用方要先把 room["live"] 置位、再 resort()，卡片才会先挪到「开播优先」
        该在的位置；动效放到下一个事件循环里播，那时卡片已经就位，水滴和气泡
        才会落在卡片身上，而不是留在它挪走之前的那一行。
        """
        host = self.host
        pending = [item for item in items if item is not None]
        if not pending:
            return
        QTimer.singleShot(0, lambda: host._play_live_alerts_now(pending))

    @staticmethod
    def play_live_alerts_now(items: list) -> None:
        for item in items:
            if item.parentWidget() is None:      # 已经不在列表里了
                continue
            item.play_live_alert()
            print(f"[开播提醒] {item.room.get('uname')}", file=sys.stderr, flush=True)

    def sync_count(self) -> None:
        host = self.host
        platforms = {str(item.room.get("room_id", "")).split(":", 1)[0]
                     if ":" in str(item.room.get("room_id", "")) else "bilibili"
                     for item in host._items}
        for item in host._items:
            show = len(platforms) > 1 and getattr(host, "show_platform_logos", True)
            changed = item.platform_badge.property("showPlatform") != show
            if changed:
                item.platform_badge.setProperty("showPlatform", show)
            item.platform_badge.setVisible(show and not item.thumb.video.isVisible())
            if changed:
                item.thumb._layout_overlay()
        shown = len(host.visible_items())
        if host.filter_text:
            # 搜索时把「露出来几路 / 一共几路」都写上，免得以为关注丢了
            host.count_label.setText(f"关注中 · {shown} / {len(host._items)}")
        else:
            host.count_label.setText(f"关注中 · {len(host._items)}")
        if hasattr(host, 'navigation'):
            host.navigation.sync_count()

    def set_refreshing(self, busy: bool) -> None:
        host = self.host
        host.refresh_button.setEnabled(True)
        host.refresh_button.set_refreshing(busy)
        host.refresh_button.setToolTip(
            "正在刷新关注列表…再次点击可排队刷新" if busy else "立刻刷新关注列表：直播状态、标题、在线人数、头像")
