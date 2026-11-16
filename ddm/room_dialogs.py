"""Room addition and follow import dialogs; no settings-page or main-window dependency."""
import re
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QMenu, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout
)
from . import theme
from .follow_folders import default_folder
from .folder_icons import create_folder_dialog
from .search import matches_text
from .motion import AnimatedDialog


from .room_folder_controls import (_add_folder_option, _create_folder_for_dialog)


from .add_room_dialog import (AddRoomDialog)


class FollowImportDialog(QDialog):
    """从关注列表里挑要加入监控室的直播间。

    整行点击即可切换勾选；已在关注列表里的默认勾选（重复导入不会重复添加）。
    """

    INDICATOR_WIDTH = 30      # 勾选方块占据的左侧宽度

    def __init__(self, rooms: list[dict], existing: set[str], parent=None, *, folders=None,
                 folder_creator=None, room_menu=False):
        super().__init__(parent)
        self.room_menu = room_menu
        self.setWindowTitle("导入关注")
        self.resize(520, 620)
        self.rooms = rooms
        self.existing = {str(item) for item in existing}
        self._explicitly_checked = set()
        self.folder_id = ""
        self.folder_changed = False
        self.folder_names = {folder['name'] for folder in folders or []}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        live_count = sum(1 for room in rooms if room["live"])
        self.header = QLabel(f"共 {len(rooms)} 个直播间（{live_count} 个直播中）")
        self.header.setObjectName("AppSubtitle")
        if self.room_menu:
            self.header.setWordWrap(True)
        layout.addWidget(self.header)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索主播名称")
        self.search_edit.setToolTip("支持中文、全拼和拼音首字母")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_rooms)
        layout.addWidget(self.search_edit)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("放入文件夹"))
        self.folder_button = QPushButton(default_folder(folders)["name"])
        self.folder_button.setObjectName("IconButton")
        self.folder_button.setAutoDefault(False)
        self.folder_button.setToolTip("仅调整新增或主动勾选的主播；默认勾选的已有关注保留原归属")
        folder_menu = QMenu(self.folder_button)
        options = [("", default_folder(folders)["name"])] + [(folder["id"], folder["name"]) for folder in folders or []
                                  if folder.get("type", "normal") == "normal"]
        for folder_id, name in options:
            _add_folder_option(self, folder_menu, folder_id, name)
        self.folder_button.setMenu(folder_menu)
        folder_row.addWidget(self.folder_button, 1)
        self.new_folder_button = QPushButton("新建文件夹")
        self.new_folder_button.setObjectName("IconButton")
        self.new_folder_button.setAutoDefault(False)
        self.new_folder_button.setEnabled(folder_creator is not None)
        self.new_folder_button.clicked.connect(lambda: _create_folder_for_dialog(self, folder_creator))
        folder_row.addWidget(self.new_folder_button)
        layout.addLayout(folder_row)

        hint = QLabel("取消勾选并导入会移除本地关注；文件夹仅用于新增或主动勾选的主播。已有关注需取消后重新勾选，或用筛选后的全选明确归类。")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 快捷筛选
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.filter_buttons = []
        for text, handler in (("全选", lambda: self._check_all(True)),
                              ("全不选", lambda: self._check_all(False)),
                              ("只选直播中", self._check_live)):
            button = QPushButton(text)
            button.setObjectName("IconButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setToolTip("只操作当前搜索结果")
            button.clicked.connect(handler)
            filters.addWidget(button)
            self.filter_buttons.append(button)
        if self.room_menu:
            self.show_pending = QCheckBox("显示待识别账号")
            self.show_pending.setVisible(any(not room.get("room_id") for room in rooms))
            self.show_pending.toggled.connect(lambda _: self._filter_rooms(self.search_edit.text()))
            filters.addWidget(self.show_pending)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.list = QListWidget()
        self.list.setObjectName("FollowList")
        self.list.itemClicked.connect(self._on_item_clicked)
        self._avatar_items = {}
        self.list.setUniformItemSizes(True)
        self.list.setLayoutMode(QListWidget.Batched)
        self.list.setBatchSize(64)
        self._offset = 0
        self._populating = len(rooms) > 128
        self._pending_avatars = {}
        self._requested_avatars = set()
        self._populate_timer = QTimer(self)
        self._populate_timer.setInterval(8)
        self._populate_timer.timeout.connect(self._populate_more)
        self._avatar_timer = QTimer(self)
        self._avatar_timer.setSingleShot(True)
        self._avatar_timer.setInterval(30)
        self._avatar_timer.timeout.connect(self.request_visible_avatars)
        self.list.verticalScrollBar().valueChanged.connect(lambda: self._avatar_timer.start())
        self._append_rooms(rooms[:32] if self._populating else rooms)
        self._offset = self.list.count()
        layout.addWidget(self.list, 1)
        self.list.itemChanged.connect(self._track_checked)
        if self.room_menu:
            self.empty_label = QLabel("暂未识别到可导入的直播间；可等待补充识别，或查看待识别账号。")
            self.empty_label.setObjectName("SettingsHint")
            self.empty_label.setWordWrap(True)
            layout.addWidget(self.empty_label)
            self.empty_label.hide()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("导入")
        self.import_button = confirm
        confirm.setObjectName("PrimaryButton")
        confirm.setAutoDefault(False)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

        self.import_button.setEnabled(not self._populating)
        for button in self.filter_buttons:
            button.setEnabled(not self._populating)
        if self.room_menu:
            self._filter_rooms(self.search_edit.text())
        else:
            self._update_header()

    avatarRequested = Signal(dict)

    def _append_rooms(self, rooms):
        for room in rooms:
            room_id = str(room["room_id"])
            item = QListWidgetItem(self._room_text(room))
            item.setData(Qt.UserRole, room)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if room_id in self.existing or room.get("pending_import") else Qt.Unchecked)
            item.setData(Qt.UserRole + 1, item.checkState() == Qt.Checked)
            self.list.addItem(item)
            if room_id:
                self._avatar_items.setdefault(room_id, item)
            if room.get("anchor_uid"):
                self._avatar_items.setdefault("account:" + str(room["anchor_uid"]), item)
            query = self.search_edit.text().strip().casefold()
            item.setHidden(not matches_text(room['uname'], query))
            if self.room_menu and not self.show_pending.isChecked() and not room.get("room_id"):
                item.setHidden(True)
            for key in (room_id, 'account:' + str(room.get('anchor_uid'))):
                pixmap = self._pending_avatars.pop(key, None)
                if pixmap is not None:
                    self.set_avatar(key, pixmap)

    def _populate_more(self):
        self._append_rooms(self.rooms[self._offset:self._offset + 32])
        self._offset = self.list.count()
        self._populating = self._offset < len(self.rooms)
        if not self._populating:
            self._populate_timer.stop()
            self.import_button.setEnabled(True)
            for button in self.filter_buttons:
                button.setEnabled(True)
            self._avatar_timer.start()
        self._update_header()

    def showEvent(self, event):
        super().showEvent(event)
        if self._populating:
            self._populate_timer.start()
        self._avatar_timer.start()

    def hideEvent(self, event):
        self._populate_timer.stop()
        self._avatar_timer.stop()
        super().hideEvent(event)

    def request_visible_avatars(self):
        if not self.isVisible():
            return
        first = max(0, self.list.indexAt(self.list.viewport().rect().topLeft()).row())
        last = self.list.indexAt(self.list.viewport().rect().bottomLeft()).row()
        if last < first:
            last = first + 24
        faces = {}
        for index in range(first, min(self.list.count(), last + 5)):
            room = self.list.item(index).data(Qt.UserRole)
            key = str(room.get('room_id') or 'account:' + str(room.get('anchor_uid')))
            if room.get('face') and key not in self._requested_avatars:
                self._requested_avatars.add(key)
                faces[key] = room['face']
        if faces:
            self.avatarRequested.emit(faces)

    def _select_folder(self, action) -> None:
        self.folder_id = action.data()
        self.folder_changed = True
        self.folder_button.setText(action.text())
        for option in self.folder_button.menu().actions():
            option.setChecked(option is action)

    def _filter_rooms(self, text: str) -> None:
        # 隐藏条目而不重建列表，保留勾选和异步回填的头像。
        if self.property("loading"):
            return
        query = text.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(not matches_text(item.data(Qt.UserRole)["uname"], query))
            if self.room_menu and not self.show_pending.isChecked() and not item.data(Qt.UserRole).get("room_id"):
                item.setHidden(True)
        self._update_header()

    # ---- 勾选交互：整行可点 ----
    def _track_checked(self, item: QListWidgetItem) -> None:
        checked = item.checkState() == Qt.Checked
        if checked == item.data(Qt.UserRole + 1):
            return
        item.setData(Qt.UserRole + 1, checked)
        room_id = str(item.data(Qt.UserRole)["room_id"])
        if checked:
            self._explicitly_checked.add(room_id)
        else:
            self._explicitly_checked.discard(room_id)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        position = self.list.viewport().mapFromGlobal(QCursor.pos())
        rect = self.list.visualItemRect(item)
        if position.x() - rect.x() <= self.INDICATOR_WIDTH:
            self._update_header()      # 点在方块上，Qt 已处理
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self._update_header()

    def _check_all(self, checked: bool) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                if checked:
                    self._explicitly_checked.add(str(item.data(Qt.UserRole)["room_id"]))
        self._update_header()

    def _check_live(self) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if item.data(Qt.UserRole)["live"] else Qt.Unchecked)
                if item.checkState() == Qt.Checked:
                    self._explicitly_checked.add(str(item.data(Qt.UserRole)["room_id"]))
        self._update_header()

    def _update_header(self) -> None:
        if self._populating:
            self.header.setText(f'共 {len(self.rooms)} 个关注，正在显示 {self.list.count()} 个…')
            return
        selected = len(self.selected())
        shown = sum(not self.list.item(index).isHidden() for index in range(self.list.count()))
        filtered = f"，当前显示 {shown} 个" if self.search_edit.text().strip() else ""
        pending = sum(not room.get("room_id") for room in self.rooms)
        if self.room_menu:
            chosen = sum(bool(room.get("room_id")) for room in self.selected())
            references = sum(bool(room.get("follow_account_ref")) for room in self.rooms)
            pending_chosen = len(self.selected()) - chosen
            self.import_button.setText("导入并保存待识别" if pending_chosen and chosen else
                                       "保存待识别选择" if pending_chosen else "导入")
            self.import_button.setToolTip("待识别账号只保存选择，取得房间号后才能加入关注栏。")
            if references:
                self.import_button.setToolTip("未开播的账号也可直接导入，导入后随状态刷新自动识别直播间。")
            saved = f"，{pending_chosen} 个待识别账号已勾选" if pending_chosen else ""
            accounts = f"，{references} 个按账号关注" if references else ""
            self.header.setText(f"共 {len(self.rooms)} 个关注账号，{len(self.rooms) - pending - references} 个直播间"
                                f"{accounts}，{pending} 个待识别{filtered}，已勾选 {chosen} 项{saved}")
            self.empty_label.setText("没有匹配的主播，请调整搜索条件。" if self.search_edit.text().strip() else
                                     "暂未识别到可导入的直播间；可补充识别，或显示待识别账号。")
            self.empty_label.setVisible(shown == 0)
            return
        noun = "关注账号" if any(room.get("anchor_uid") for room in self.rooms) else "直播间"
        detail = f"，{pending} 个直播间待识别" if pending else ""
        self.header.setText(f"共 {len(self.rooms)} 个{noun}{detail}{filtered}，已勾选 {selected} 个")

    @staticmethod
    def _room_text(room):
        status = ("直播间待识别" if not room.get("room_id") else
                  "直播状态待刷新" if room.get("live_known") is False else
                  "直播中" if room["live"] else "未开播")
        if room.get("follow_account_ref"):
            status += "（账号关注）"
        if room.get("follow_resolve_error"):
            status += "（本次识别失败）"
        elif room.get("follow_resolve_note"):
            status += "（本次" + room["follow_resolve_note"] + "）"
        return "　".join([room["uname"], status] + ([room["title"][:18]] if room.get("title") else []))

    def update_account(self, account):
        for index, room in enumerate(self.rooms):
            if room.get("anchor_uid") == account.get("anchor_uid"):
                self.rooms[index] = dict(account)
                if index >= self.list.count():
                    return
                item = self.list.item(index)
                item.setData(Qt.UserRole, dict(account))
                item.setText(self._room_text(account))
                if account.get("room_id"):
                    self._avatar_items[str(account["room_id"])] = item
                if self.room_menu:
                    self._filter_rooms(self.search_edit.text())
                else:
                    self._update_header()
                return

    # ---- 结果 ----
    def folder_room_ids(self) -> list[str]:
        return [str(room["room_id"]) for room in self.selected()
                if str(room["room_id"]) not in self.existing
                or str(room["room_id"]) in self._explicitly_checked]

    def deselected_existing(self) -> list[str]:
        return [str(self.list.item(index).data(Qt.UserRole)["room_id"])
                for index in range(self.list.count())
                if str(self.list.item(index).data(Qt.UserRole)["room_id"]) in self.existing
                and self.list.item(index).checkState() != Qt.Checked]

    def selected(self) -> list[dict]:
        result = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def set_avatar(self, room_id: str, pixmap: QPixmap) -> None:
        """头像下好之后回填（下载是异步的）。"""
        from .avatar_widgets import circular_pixmap
        item = self._avatar_items.get(str(room_id))
        if item is None and self._populating:
            self._pending_avatars[str(room_id)] = pixmap
        if item is not None:
            item.setIcon(QIcon(circular_pixmap(pixmap, 32)))
