"""Room addition and follow import dialogs; no settings-page or main-window dependency."""
import re
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QMenu, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget
)
from . import theme
from .follow_folders import default_folder
from .folder_icons import create_folder_dialog
from .search import matches_text
from .motion import AnimatedDialog
from .follow_import_ui import FollowImportDelegate, FollowImportItem, FollowImportList
from .ui.select import SelectControl
from pypinyin import lazy_pinyin


from .room_folder_controls import (_add_folder_option, _create_folder_for_dialog)


from .add_room_dialog import (AddRoomDialog)


class FollowImportDialog(QDialog):
    """从关注列表里挑要加入监控室的直播间。

    整行点击即可切换勾选；已在关注列表里的默认勾选（重复导入不会重复添加）。
    """

    def __init__(self, rooms: list[dict], existing: set[str], parent=None, *, folders=None,
                 folder_creator=None, room_menu=False):
        super().__init__(parent)
        self.room_menu = room_menu
        self.setWindowTitle("导入关注")
        self.resize(660, 620)
        self.rooms = rooms
        self.existing = {str(item) for item in existing}
        self._explicitly_checked = set()
        self.folder_id = ""
        self.folder_changed = False
        self.folder_names = {folder['name'] for folder in folders or []}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.header = QLabel()
        self.header.setObjectName("AppSubtitle")
        self.header.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.removal_hint = QLabel()
        self.removal_hint.setObjectName("SettingsHint")
        self.removal_hint.setWordWrap(True)
        self.removal_hint.hide()
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.timeout.connect(self._update_header)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索主播名称")
        self.search_edit.setToolTip("支持中文、全拼和拼音首字母")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_rooms)
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self.search_edit, 1)
        self.sort_control = SelectControl()
        self.sort_control.setAccessibleName("主播排序")
        self.sort_control.setMinimumContentsLength(4)
        self.sort_control.setFixedWidth(126)
        for label, mode in (("原顺序", "original"), ("直播优先", "live"),
                            ("未添加优先", "unadded"), ("名称排序", "name")):
            self.sort_control.addItem(label, mode)
        self.sort_control.setToolTip("只调整显示顺序；名称按拼音及字母排序，不改变勾选")
        self.sort_control.currentIndexChanged.connect(lambda _: self._sort_rooms())
        search_row.addWidget(self.sort_control)
        layout.addLayout(search_row)

        self.folder_controls = QWidget()
        folder_row = QHBoxLayout(self.folder_controls)
        folder_row.setContentsMargins(0, 0, 0, 0)
        self.folder_button = QPushButton(default_folder(folders)["name"])
        self.folder_button.setObjectName("IconButton")
        self.folder_button.setMaximumWidth(160)
        self.folder_button.setAutoDefault(False)
        self.folder_button.setToolTip("仅调整新增或主动勾选的主播；默认勾选的已有关注保留原归属")
        folder_menu = QMenu(self.folder_button)
        options = [("", default_folder(folders)["name"])] + [(folder["id"], folder["name"]) for folder in folders or []
                                  if folder.get("type", "normal") == "normal"]
        for folder_id, name in options:
            _add_folder_option(self, folder_menu, folder_id, name)
        self.folder_button.setMenu(folder_menu)
        folder_row.addWidget(self.folder_button)
        folder_menu.addSeparator()
        self.new_folder_action = folder_menu.addAction("新建文件夹…")
        self.new_folder_action.setEnabled(folder_creator is not None)
        self.new_folder_action.triggered.connect(lambda: _create_folder_for_dialog(self, folder_creator))
        # 快捷筛选
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(6)
        selection_actions = QHBoxLayout()
        selection_actions.setContentsMargins(0, 0, 0, 0)
        selection_actions.setSpacing(6)
        self.filter_buttons = []
        for text, handler in (("全选", lambda: self._check_all(True)),
                              ("不选", lambda: self._check_all(False)),
                              ("选直播中", self._check_live)):
            button = QPushButton(text)
            button.setObjectName("IconButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setToolTip("只操作当前搜索结果")
            button.clicked.connect(handler)
            selection_actions.addWidget(button)
            self.filter_buttons.append(button)
        selection_actions.addStretch(1)
        filters.addLayout(selection_actions, 0, 0)
        filters.setColumnStretch(0, 1)
        self.hide_existing = QCheckBox("隐藏已添加")
        self.hide_existing.setToolTip("仅隐藏已有关注，保留其勾选；不会因为隐藏而移除关注")
        self.hide_existing.toggled.connect(lambda _: self._filter_rooms(self.search_edit.text()))
        filters.addWidget(self.hide_existing, 0, 1)
        if self.room_menu:
            pending_count = sum(not room.get("room_id") for room in rooms)
            self.show_pending = QCheckBox(f"待识别 {pending_count}")
            self.show_pending.setToolTip("显示尚未取得直播间号的账号；勾选后保存，识别成功后再导入")
            self.show_pending.setVisible(any(not room.get("room_id") for room in rooms))
            self.show_pending.toggled.connect(lambda _: self._filter_rooms(self.search_edit.text()))
            filters.addWidget(self.show_pending, 1, 0, 1, 2)
        layout.addLayout(filters)

        self.list = FollowImportList()
        self.list.setObjectName("FollowList")
        self.list.setItemDelegate(FollowImportDelegate(self.existing, self.list))
        self.list.itemDelegate().checkChanged.connect(self._update_header)
        self.list.setMouseTracking(True)
        self._avatar_items = {}
        self.list.setUniformItemSizes(True)
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
        self.empty_label = QLabel()
        self.empty_label.setObjectName("SettingsHint")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

        layout.addWidget(self.removal_hint)
        self.secondary_actions = QHBoxLayout()
        layout.addLayout(self.secondary_actions)
        self.footer = QGridLayout()
        self.footer.setColumnStretch(0, 1)
        self.footer.addWidget(self.header, 0, 0)
        self.footer.addWidget(self.folder_controls, 1, 0)
        self.confirm_controls = QWidget()
        buttons = QHBoxLayout(self.confirm_controls)
        buttons.setContentsMargins(0, 0, 0, 0)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("应用选择")
        self.import_button = confirm
        confirm.setObjectName("PrimaryButton")
        confirm.setAutoDefault(False)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        self.footer.addWidget(self.confirm_controls, 1, 2)
        layout.addLayout(self.footer)

        self.sort_control.setEnabled(not self._populating)
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
            item = FollowImportItem(self._room_text(room))
            item.setData(Qt.UserRole + 2, self.list.count())
            item.setData(Qt.UserRole + 3, (self.list.count(),))
            item.setData(Qt.UserRole, room)
            item.setToolTip(self._room_text(room))
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if room_id in self.existing or room.get("pending_import") else Qt.Unchecked)
            item.setData(Qt.UserRole + 1, item.checkState() == Qt.Checked)
            self.list.addItem(item)
            if room_id:
                self._avatar_items.setdefault(room_id, item)
            if room.get("anchor_uid"):
                self._avatar_items.setdefault("account:" + str(room["anchor_uid"]), item)
            item.setHidden(self._room_hidden(room))
            for key in (room_id, 'account:' + str(room.get('anchor_uid'))):
                pixmap = self._pending_avatars.pop(key, None)
                if pixmap is not None:
                    self.set_avatar(key, pixmap)
        if self.sort_control.currentData() != "original":
            self._sort_rooms()

    def _populate_more(self):
        self._append_rooms(self.rooms[self._offset:self._offset + 32])
        self._offset = self.list.count()
        self._populating = self._offset < len(self.rooms)
        if not self._populating:
            self._populate_timer.stop()
            self.import_button.setEnabled(True)
            self.sort_control.setEnabled(True)
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
        visible = self.list.viewport().rect().adjusted(0, -80, 0, 80)
        faces = {}
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.isHidden() or not self.list.visualItemRect(item).intersects(visible):
                continue
            room = item.data(Qt.UserRole)
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
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(self._room_hidden(item.data(Qt.UserRole)))
        self._avatar_timer.start()
        self._update_header()

    def _room_hidden(self, room):
        return (not matches_text(room['uname'], self.search_edit.text().strip().casefold())
                or (self.hide_existing.isChecked() and str(room['room_id']) in self.existing)
                or (self.room_menu and not self.show_pending.isChecked() and not room.get('room_id')))

    def _sort_rooms(self):
        mode = self.sort_control.currentData()
        for index in range(self.list.count()):
            item = self.list.item(index)
            room = item.data(Qt.UserRole)
            original = item.data(Qt.UserRole + 2)
            if mode == 'live':
                key = (not bool(room.get('live')), original)
            elif mode == 'unadded':
                key = (str(room['room_id']) in self.existing, original)
            elif mode == 'name':
                key = (''.join(lazy_pinyin(room['uname'])).casefold(), original)
            else:
                key = (original,)
            item.setData(Qt.UserRole + 3, key)
        self.list.sortItems()
        self._avatar_timer.start()

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
        self._summary_timer.start(0)

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
        chosen = self.selected()
        shown = sum(not self.list.item(index).isHidden() for index in range(self.list.count()))
        pending = sum(not room.get("room_id") for room in self.rooms)
        added = sum(bool(room.get("room_id")) and str(room["room_id"]) not in self.existing for room in chosen)
        removed = len(self.deselected_existing())
        pending_chosen = sum(not room.get("room_id") for room in chosen)
        parts = [f"已选 {len(chosen)}", f"新增 {added}"]
        if removed:
            parts.append(f"移除 {removed}")
        if pending_chosen:
            parts.append(f"待识别 {pending_chosen}")
        self.header.setText(" · ".join(parts))
        references = sum(bool(room.get("follow_account_ref")) for room in self.rooms)
        self.header.setToolTip(f"共 {len(self.rooms)} 个关注，当前显示 {shown} 个；"
                               f"{len(self.rooms) - pending - references} 个直播间，{pending} 个待识别，"
                               f"{references} 个按账号关注")
        self.removal_hint.setText(f"应用后将移除 {removed} 个本地关注。")
        self.removal_hint.setVisible(bool(removed))
        self.import_button.setText("应用选择")
        self.import_button.setToolTip("应用勾选并移除取消勾选的已有关注；文件夹仅调整新增或主动勾选的主播。"
                                     "待识别账号只保存选择，取得房间号后加入关注栏。")
        if self.room_menu:
            self.show_pending.setText(f"待识别 {pending}")
            self.show_pending.setVisible(bool(pending))
        if self.search_edit.text().strip():
            empty_text = "没有匹配的主播，请调整搜索条件。"
        elif self.hide_existing.isChecked() and self.rooms:
            empty_text = "当前没有未添加的主播，可取消“隐藏已添加”查看。"
        elif self.room_menu:
            empty_text = "暂无可导入的直播间，可补充识别或显示待识别账号。"
        else:
            empty_text = "暂无可导入的关注。"
        self.empty_label.setText(empty_text)
        self.empty_label.setVisible(shown == 0 and not self.property("loading"))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "confirm_controls"):
            # 窄窗口统计独占一行，文件夹与确认操作留在下一行。
            wide = self.width() >= 620
            self.footer.removeWidget(self.header)
            self.footer.removeWidget(self.confirm_controls)
            self.footer.removeWidget(self.folder_controls)
            self.footer.addWidget(self.header, 0, 0, 1, 1 if wide else 3)
            self.footer.addWidget(self.folder_controls, 0 if wide else 1, 1 if wide else 0)
            self.footer.addWidget(self.confirm_controls, 0 if wide else 1, 2)

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
                item = self._avatar_items.get('account:' + str(account.get('anchor_uid')))
                if item is None:
                    return
                item.setData(Qt.UserRole, dict(account))
                item.setText(self._room_text(account))
                item.setToolTip(self._room_text(account))
                if account.get("room_id"):
                    self._avatar_items[str(account["room_id"])] = item
                self._sort_rooms()
                self._filter_rooms(self.search_edit.text())
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
