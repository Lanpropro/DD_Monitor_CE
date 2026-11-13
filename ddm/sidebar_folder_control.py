"""Follow-folder commands and presentation; data and Qt children belong to the sidebar."""
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QInputDialog, QMenu

from . import follow_folders, motion
from .widget_support import NAV_ITEM_GAP


class SidebarFolderControl:
    def __init__(self, host):
        self.host = host

    def folder_create_menu(self) -> QMenu:
        host = self.host
        menu = motion.AnimatedMenu(host)
        menu.addAction("新建文件夹…").triggered.connect(lambda: host.prompt_folder())
        menu.addAction("新建智能文件夹…").triggered.connect(lambda: host.prompt_smart_folder())
        return menu

    def folder_state(self) -> list[dict]:
        host = self.host
        return follow_folders.folder_state(host.folders)

    def get_folder(self, folder_id: str):
        host = self.host
        return next((folder for folder in host.folders if folder["id"] == folder_id), None)

    def default_folder(self):
        host = self.host
        return follow_folders.default_folder(host.folders)

    def set_default_folder(self, folder_id, *, notify=True):
        host = self.host
        target = host.get_folder(folder_id)
        if target is None or target["type"] != "normal":
            return
        previous = host.default_folder()
        assigned = {rid for folder in host.folders if folder["type"] != "smart"
                    for rid in folder["rooms"]}
        previous["rooms"].extend(str(room["room_id"]) for room in host.rooms()
                                 if str(room["room_id"]) not in assigned)
        previous["type"] = "normal"
        target["type"] = "unclassified"
        host._refresh_folders(notify=notify)

    def folder_for(self, room_id: str) -> str:
        host = self.host
        return host._folder_assignments.get(room_id) or next(
            (folder["id"] for folder in host.folders if room_id in folder["rooms"]), "")

    def set_folders(self, folders: list) -> None:
        host = self.host
        host.folders = follow_folders.normalize_folders(folders, host.sort_mode)
        host._refresh_folders(notify=False)

    def create_folder(self, name: str, *, rule=None, sort="custom", icon=None) -> str:
        host = self.host
        name = name.strip()
        if not name or any(folder["name"] == name for folder in host.folders):
            return ""
        folder_id = uuid4().hex
        folder = {"id": folder_id, "name": name, "type": "smart" if rule is not None else "normal",
                  "collapsed": False, "rooms": [], "sort": sort}
        if rule is not None:
            folder["rule"] = rule
        if icon is not None:
            folder['icon'] = icon
        index = host.folders.index(host.default_folder())
        if rule is not None:
            folder["rule"] = dict(rule, sources=rule.get("sources", [host.default_folder()["id"]]))
        host.folders.insert(index, follow_folders.normalize_folders([folder])[0])
        host._refresh_folders()
        return folder_id

    def rename_folder(self, folder_id, name):
        host = self.host
        folder = host.get_folder(folder_id)
        name = name.strip()
        if not name or any(item['name'] == name and item['id'] != folder_id for item in host.folders):
            return
        if name != folder['name']:
            folder['name'] = name
            host._refresh_folders()

    def prompt_folder(self, room_ids=None, *, folder_id="", create_dialog) -> None:
        host = self.host
        create_folder_dialog = create_dialog
        folder = next((item for item in host.folders if item["id"] == folder_id), None)
        if folder is None:
            folder_id, _name = create_folder_dialog(host, host.create_folder,
                                                    (item['name'] for item in host.folders))
            if folder_id and room_ids:
                host.move_to_folder(room_ids, folder_id)
            return
        name, accepted = QInputDialog.getText(
            host, "重命名文件夹", "文件夹名称：", text=folder["name"])
        if not accepted or not name.strip():
            return
        name = name.strip()
        if any(item["name"] == name and item["id"] != folder_id for item in host.folders):
            return
        folder["name"] = name
        host._refresh_folders()

    def delete_folder(self, folder_id: str) -> None:
        host = self.host
        if folder_id == host.default_folder()["id"]:
            replacement = next((folder for folder in host.folders if folder["type"] == "normal"), None)
            if replacement is None:
                return
            host.set_default_folder(replacement["id"], notify=False)
        host.folders = [folder for folder in host.folders if folder["id"] != folder_id]
        host._refresh_folders()

    def toggle_folder(self, folder_id: str, *, animate=False) -> None:
        host = self.host
        for folder in host.folders:
            if folder["id"] == folder_id:
                host._folders_folded_by_drag.discard(folder_id)
                folder["collapsed"] = not folder["collapsed"]
                host._refresh_folders(animate=animate and motion.enabled())
                return

    def move_to_folder(self, room_ids: list[str], folder_id: str) -> None:
        host = self.host
        target = host.get_folder(folder_id or host.default_folder()["id"])
        if target is None or target["type"] == "smart":
            return
        known = {str(item.room.get("room_id")) for item in host._items}
        moving = list(dict.fromkeys(key for key in room_ids if key in known))
        for folder in host.folders:
            folder["rooms"] = [key for key in folder["rooms"] if key not in moving]
        if target["type"] == "normal":
            target["rooms"].extend(moving)
            host._folder_pending.difference_update(moving)
        else:
            host._folder_pending.update(moving)
        host._refresh_folders()

    def move_folder(self, folder_id: str, direction: int) -> None:
        host = self.host
        folder = host.get_folder(folder_id)
        if folder is None:
            return
        index = host.folders.index(folder)
        target = index + direction
        if 0 <= target < len(host.folders):
            host.folders[index], host.folders[target] = host.folders[target], host.folders[index]
            host._refresh_folders()

    def start_folder_drag(self) -> None:
        """拖动标题时临时收起全部文件夹，结束后恢复原来的展开状态。"""
        host = self.host
        host._folder_drag_previous = {folder["id"]: folder["collapsed"] for folder in host.folders}
        host._folders_folded_by_drag.update(folder["id"] for folder in host.folders)
        for folder in host.folders:
            folder["collapsed"] = True
        host._refresh_folders(notify=False)

    def end_folder_drag(self) -> None:
        host = self.host
        host.list_box.set_scroll_dir(0)
        host.list_box.folder_drop_indicator.hide()
        for folder in host.folders:
            if folder["id"] in host._folder_drag_previous:
                folder["collapsed"] = host._folder_drag_previous[folder["id"]]
        host._folder_drag_previous.clear()
        host._folders_folded_by_drag.clear()
        host._refresh_folders()

    def folder_drop_target(self, folder_id: str, global_pos):
        host = self.host
        box = host.list_box
        local = box.mapFromGlobal(global_pos)
        if host.get_folder(folder_id) is None or not box.rect().contains(local):
            return None
        remaining = [folder for folder in host.folders if folder["id"] != folder_id]
        headers = [(index, host._folder_buttons[folder["id"]]) for index, folder in enumerate(remaining)
                   if not host._folder_buttons[folder["id"]].isHidden()]
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
        host = self.host
        host.list_box.auto_scroll(global_pos)
        target = host._folder_drop_target(folder_id, global_pos)
        indicator = host.list_box.folder_drop_indicator
        if target is None:
            indicator.hide()
            return
        _, along = target
        if host.list_box.horizontal:
            indicator.setGeometry(along, 0, 2, host.list_box.item_size()[1])
        else:
            indicator.setGeometry(0, along, host.list_box.width(), 2)
        indicator.show()
        indicator.raise_()

    def finish_folder_drag(self, folder_id: str, global_pos) -> None:
        host = self.host
        host.list_box.set_scroll_dir(0)
        host.list_box.folder_drop_indicator.hide()
        target = host._folder_drop_target(folder_id, global_pos)
        if target is None:
            return
        index, _ = target
        folder = host.get_folder(folder_id)
        if host.folders.index(folder) != index:
            host.folders.remove(folder)
            host.folders.insert(index, folder)
            host._refresh_folders(notify=not bool(host._folder_drag_previous))

    def prompt_smart_folder(self, folder_id="", *, dialog_type) -> None:
        host = self.host
        SmartFolderDialog = dialog_type
        folder = host.get_folder(folder_id)
        dialog = SmartFolderDialog(host, folder)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.values()
        if any(item["name"] == data["name"] and item["id"] != folder_id for item in host.folders):
            return
        if folder:
            folder.update(data)
            host._refresh_folders()
        else:
            host.create_folder(**data)

    def refresh_folders(self, notify: bool = True, *, animate=False) -> None:
        host = self.host
        host._sync_watch_history_mode()
        revealing = {item for item in host._items if item.filtered_out} if animate else ()
        ids = {folder["id"] for folder in host.folders}
        host._folders_folded_by_drag.intersection_update(ids)
        for folder_id in list(host._folder_buttons):
            if folder_id not in ids:
                button = host._folder_buttons.pop(folder_id)
                button.hide()
                button.deleteLater()
        host.clear_sort_selection()
        host.resort(animate=animate, duration=280 if animate else 150, revealing=revealing,
                    viewport_only=animate)
        for item in host._items:
            if item.filtered_out:
                item.check.setChecked(False)
        host._update_batch_label()
        host._sync_sort_selection()
        if notify:
            host.foldersChanged.emit()

    def folder_entries(self, preview_items: list | None = None,
                       dragging_ids: set[str] | None = None, *, header_type, card_type) -> list:
        """分组显示，不改变关注、置顶或自定义顺序的保存方式。"""
        host = self.host
        FollowFolderButton = header_type
        SmartFolderCard = card_type
        entries = []
        visible = host.visible_items() if preview_items is None else [
            item for item in preview_items if not item.filtered_out]
        active_copies = set()
        for folder in host.folders:
            button = host._folder_buttons.get(folder["id"])
            if button is None:
                button = FollowFolderButton(host, folder["id"])
                host._folder_buttons[folder["id"]] = button
            members = [item for item in visible
                       if host.folder_for(str(item.room.get("room_id"))) == folder["id"]]
            count = sum(fid == folder["id"] for fid in host._folder_assignments.values())
            copies = folder["type"] == "smart" and folder["rule"].get("display") == "copy"
            if copies:
                matched = follow_folders.smart_members(host.rooms(), host.folders, folder, host._folder_pending)
                count = len(matched)
                members = [item for item in host._items if str(item.room["room_id"]) in matched
                           and host.matches(item, host.filter_text.split(), folder["id"])]
                order = host.import_order if folder["sort"] == "imported" else host.custom_order
                positions = {rid: i for i, rid in enumerate(order)}
                pin_positions = {rid: i for i, rid in enumerate(host.pinned)}
                def copy_key(item):
                    index = positions.get(str(item.room["room_id"]), len(positions))
                    if folder["sort"] == "frequent":
                        rid = str(item.room["room_id"])
                        return ((False, pin_positions.get(rid, index), 0, 0) if item.is_pinned else
                                (True, not bool(item.room.get("live")),
                                 -host._frequent_scores.get(rid, 0), index))
                    value = (str(item.room.get("uname") or "").casefold() if folder["sort"] == "name"
                             else bool(item.room.get("live")) != (folder["sort"] == "live")
                             if folder["sort"] in ("live", "offline") else index)
                    return (not item.is_pinned, value, index)
                members.sort(key=copy_key)
                folded = folder["collapsed"] and (not host.filter_text or folder["id"] in host._folders_folded_by_drag)
                displayed = []
                if not folded:
                    for item in members:
                        key = (folder["id"], str(item.room["room_id"]))
                        active_copies.add(key)
                        if key not in host._smart_cards:
                            host._smart_cards[key] = SmartFolderCard(item, host.list_box)
                        displayed.append(host._smart_cards[key])
                members = displayed
            arrow = "▸" if folder["collapsed"] and (
                not host.filter_text or folder["id"] in host._folders_folded_by_drag) else "▾"
            title = f"{arrow} {folder['name']} · {count}"
            button.setToolTip(title + ("\n智能文件夹：拖动标题排序；右键编辑规则和排序" if folder["type"] == "smart"
                                      else "\n点击展开/收起；拖动标题排序；拖入卡片归类；右键管理"))
            width, height = host.list_box.item_size()
            label_width = height if host.side == "top" else width
            button.setToolButtonStyle(Qt.ToolButtonIconOnly if host.collapsed and host.side == "left"
                                      else Qt.ToolButtonTextBesideIcon)
            button.setText(button.fontMetrics().elidedText(title, Qt.ElideRight, max(12, label_width - 44)))
            search_match = bool(members) if copies else any(
                host.folder_for(str(item.room.get("room_id"))) == folder["id"]
                and host.matches(item, host.filter_text.split()) for item in host._items)
            button.setVisible(not host.filter_text or search_match)
            if not button.isHidden():
                entries.append(button)
                entries.extend(None if dragging_ids and str(item.room.get("room_id")) in dragging_ids
                               else item for item in members)
        originals = set(host._items)
        for key, card in list(host._smart_cards.items()):
            if key not in active_copies:
                card.hide()
            if card.original not in originals or not host.get_folder(key[0]):
                host._smart_cards.pop(key)
                card.deleteLater()
        return entries
