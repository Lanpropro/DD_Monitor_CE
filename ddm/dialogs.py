"""对话框：设置（常规 / 快捷键）、添加直播间、从关注导入。"""
import re
import sys
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout,
    QWidget
)

from . import theme
from .update_version import update_identity
from .follow_folders import default_folder
from .folder_icons import create_folder_dialog
from .search import matches_text
from .motion import AnimatedDialog, SettingsStack

# 快捷键动作：键名 -> (显示名, 默认按键)
# 按下的键用 QKeySequence 的字符串表示，组合键写成 "Alt+M" / "Ctrl+Shift+F"。
from .shortcut_actions import SHORTCUT_ACTIONS


from .settings_general import (CodecSettingsPanel, CodecSettingsDialog, GeneralSettingsPage, TraySettingsPage)


from .settings_notifications import (NotificationSwitch, NoticeBlurPreview, NotificationSettingsPage)


from .settings_shortcuts import (ShortcutSettingsPage)


from .settings_danmaku import (DanmakuSettingsPage)


from .settings_recording import (RecordingSettingsPage)


from .settings_plugins import (PluginRemovePrompt, PluginSettingsPage)


from .settings_appearance import (AppearanceSettingsPage)


class SettingsDialog(QDialog):
    updatesViewed = Signal(object)
    appearanceChanged = Signal(str)
    pageCreated = Signal(int, object)
    """设置总窗口：左边选类别，右边改内容，不再弹二级菜单。"""

    PAGES = [("general", "常规"), ("appearance", "外观"), ("danmaku", "弹幕"),
             ("recording", "录制"), ("notifications", "通知"), ("shortcuts", "快捷键"),
             ("tray", "托盘行为"), ("plugins", "插件"), ("updates", "软件更新")]
    PAGE_INDEX = {key: index for index, (key, _label) in enumerate(PAGES)}

    def __init__(self, settings: dict, shortcuts: dict, parent=None, plugin_manager=None, *, preview=False,
                 update_page_factory=None):
        super().__init__(parent)
        self._created_at = time.perf_counter()
        self._paint_logged = False
        from .config import DEFAULT_SETTINGS
        # Part artwork and per-tile video danmaku are saved by their own editors.
        self._initial_settings = {key: settings.get(key, default) for key, default in DEFAULT_SETTINGS.items()
                                  if not key.startswith('video_danmaku_')
                                  and key not in ('skin_parts', 'danmaku_retention_version')}
        self._initial_shortcuts = {key: shortcuts.get(key) or default for key, _label, default in SHORTCUT_ACTIONS}
        self._plugin_manager = plugin_manager
        self._preview_only = preview
        self._update_page_factory = update_page_factory
        self.setWindowTitle("设置")
        self.restart_requested = False
        self.seen_versions = dict(settings.get('seen_update_versions') or {})
        available = self.screen().availableGeometry()
        self.setMinimumSize(760, 520)
        self.resize(min(1200, available.width() - 48), min(800, available.height() - 72))

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        from .settings_navigation import SettingsNavigation, SettingsPointerNavigation
        from .online_ui import AppUpdatePage
        self.navigation = SettingsNavigation(self.PAGES, self)
        self.nav = self.navigation.nav
        root.addWidget(self.navigation)

        self.content = QWidget(self)
        right = QVBoxLayout(self.content)
        right.setContentsMargins(20, 18, 20, 16)
        right.setSpacing(14)
        self.stack = SettingsStack()
        self.stack.setObjectName("SettingsStack")
        self.general_page = GeneralSettingsPage(settings)
        # Build the expensive controls only when their page is first requested.
        # Keep the public page properties so callers and settings validation
        # still use the same controls and value normalization.
        self._page_factories = {
            1: lambda: AppearanceSettingsPage(settings, skin_controller=getattr(parent, 'skin_controller', None)),
            2: lambda: DanmakuSettingsPage(settings),
            3: lambda: RecordingSettingsPage(settings),
            4: lambda: NotificationSettingsPage(settings),
            5: lambda: ShortcutSettingsPage(shortcuts),
            6: lambda: TraySettingsPage(settings),
            7: lambda: PluginSettingsPage(plugin_manager),
            8: lambda: update_page_factory(settings) if update_page_factory else AppUpdatePage(settings),
        }
        self._loaded_pages = {}
        if preview:
            # The appearance thumbnail needs the real controls, without creating
            # update/download workers or reading an installation result.
            self._page_factories[7] = QWidget
            self._page_factories[8] = QWidget
        self.general_scroll = QScrollArea()
        self.general_scroll.setFrameShape(QFrame.NoFrame)
        self.general_scroll.setWidgetResizable(True)
        self.general_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.general_scroll.setWidget(self.general_page)
        self.stack.addWidget(self.general_scroll)
        for _index in range(len(self.PAGES) - 1):
            self.stack.addWidget(QWidget())
        right.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.setObjectName("IconButton")
        self.reset_button.clicked.connect(self._reset_current)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton("保存")
        self.confirm_button.setObjectName("PrimaryButton")
        self.confirm_button.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        right.addLayout(buttons)
        root.addWidget(self.content, 1)
        self.pointer_navigation = SettingsPointerNavigation(self, self.navigation, self.content)

        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(0)
        if preview:
            return
        self._update_save_button()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._paint_logged:
            self._paint_logged = True
            print(f"[设置耗时] 首次绘制 {(time.perf_counter() - self._created_at) * 1000:.1f}ms",
                  file=sys.stderr, flush=True)

    def _mark_update_page(self, key, active):
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            if item.data(Qt.UserRole) == key:
                item.setData(Qt.UserRole + 1, active)

    def _page(self, index):
        if index not in self._loaded_pages:
            started = time.perf_counter()
            placeholder = self.stack.widget(index)
            page = self._page_factories[index]()
            self._loaded_pages[index] = page
            self.stack.removeWidget(placeholder)
            self.stack.insertWidget(index, page)
            placeholder.deleteLater()
            if index == 1:
                page.modeChanged.connect(self.appearanceChanged)
            elif index == 7 and not self._preview_only:
                from .online_ui import UpdateDot
                from PySide6.QtWidgets import QTabBar
                page.store_page.seen_versions = self.seen_versions
                self._plugin_update_dot = UpdateDot()
                page.tabs.tabBar().setTabButton(1, QTabBar.RightSide, self._plugin_update_dot)
                page.changed.connect(self._update_save_button)
                page.store_page.busyChanged.connect(self._update_save_button)
                page.store_page.offersChanged.connect(self._mark_plugin_updates)
                self._mark_plugin_updates(page.store_page.offers)
            elif index == 8 and not self._preview_only:
                page.saveRequested.connect(self._save)
                page.busyChanged.connect(self._update_save_button)
                page.releaseChecked.connect(self._mark_app_update)
                page.data_page.changed.connect(self._update_save_button)
                self._update_save_button()
            self.pageCreated.emit(index, page)
            print(f"[设置耗时] 创建 {self.PAGES[index][0]} 页 {(time.perf_counter() - started) * 1000:.1f}ms",
                  file=sys.stderr, flush=True)
        return self._loaded_pages[index]

    appearance_page = property(lambda self: self._page(1))
    danmaku_page = property(lambda self: self._page(2))
    recording_page = property(lambda self: self._page(3))
    notification_page = property(lambda self: self._page(4))
    shortcut_page = property(lambda self: self._page(5))
    plugin_page = property(lambda self: self._page(7))
    update_page = property(lambda self: self._page(8))

    def _remember_versions(self, versions):
        if any(self.seen_versions.get(key) != value for key, value in versions.items()):
            self.seen_versions.update(versions)
            self.updatesViewed.emit(dict(self.seen_versions))

    def _mark_app_update(self, offer):
        if offer and self.nav.currentRow() == 8:
            self._remember_versions({'app': update_identity(offer)})
        active = bool(offer and self.seen_versions.get('app') != update_identity(offer))
        self._mark_update_page('updates', active)

    def _mark_plugin_updates(self, offers):
        from .online_ui import plugin_update_offers
        updates = plugin_update_offers(self.plugin_page.store_page.manager, offers)
        if self.nav.currentRow() == 7:
            self._remember_versions({offer['id']: offer['version'] for offer in updates})
        active = any(self.seen_versions.get(offer['id']) != offer['version'] for offer in updates)
        self._mark_update_page('plugins', active)
        self._plugin_update_dot.setVisible(active)
        self.plugin_page.store_page.update_dots()

    def _update_save_button(self, *_args) -> None:
        plugin, update = self._loaded_pages.get(7), self._loaded_pages.get(8)
        data = getattr(update, 'data_page', None)
        restart = (plugin is not None and plugin.needs_restart()) or getattr(data, 'target', None) is not None
        self.confirm_button.setText("保存并重启" if restart else "保存")
        self.confirm_button.setEnabled(not (plugin is not None and plugin.store_page.jobs)
                                      and not (update is not None and update.jobs))

    def _save(self) -> None:
        appearance = self._loaded_pages.get(1)
        if appearance is not None and appearance.parts_editor is not None:
            if not appearance.parts_editor.save_changes():
                self.nav.setCurrentRow(1)
                appearance.scroll.ensureWidgetVisible(appearance.parts_editor.status)
                return
        plugin = self._loaded_pages.get(7)
        data = getattr(self._loaded_pages.get(8), 'data_page', None)
        if data is not None and not data.prepare():
            self.nav.setCurrentRow(8)
            self.update_page.scroll.ensureWidgetVisible(data.status)
            return
        self.restart_requested = (plugin is not None and plugin.needs_restart()) or getattr(data, 'target', None) is not None
        self.accept()

    def done(self, result):
        if self._preview_only:
            return super().done(result)
        self.stack.finish_transition()
        if 7 in self._loaded_pages:
            self._loaded_pages[7].store_page.stop()
        if 8 in self._loaded_pages:
            page = self._loaded_pages[8]
            if result != QDialog.Accepted:
                page.data_page.cancel_target()
            if self._update_page_factory is None:
                page.stop()
            elif page.parentWidget() is self.stack:
                page.saveRequested.disconnect()
                page.busyChanged.disconnect(self._update_save_button)
                page.releaseChecked.disconnect(self._mark_app_update)
                page.data_page.changed.disconnect(self._update_save_button)
                self.stack.removeWidget(page)
                page.hide()
                page.setParent(self.parentWidget())
        super().done(result)

    def _on_page_changed(self, index: int) -> None:
        if index >= 0:
            if index in self._page_factories:
                self._page(index)
            self.stack.show_page(index, animate=bool(QApplication.mouseButtons()))
            self.reset_button.setText("恢复本页默认")
            self.reset_button.setVisible(index not in (7, 8))
            if index == 7 and not self._preview_only:
                self._mark_plugin_updates(self.plugin_page.store_page.offers)
            elif index == 8 and not self._preview_only:
                self._mark_app_update(self.update_page.offer)

    def _reset_current(self) -> None:
        page = self.general_page if self.stack.currentIndex() == 0 else self.stack.currentWidget()
        if hasattr(page, "reset"):
            page.reset()

    def settings(self) -> dict:
        values = dict(self._initial_settings)
        values.update(self.general_page.values())
        for index in (1, 2, 3, 4, 6):
            if index in self._loaded_pages:
                values.update(self._loaded_pages[index].values())
        if 8 in self._loaded_pages:
            values.update(self._loaded_pages[8].values())
        values['seen_update_versions'] = dict(self.seen_versions)
        return values

    def shortcuts(self) -> dict:
        return self._loaded_pages[5].values() if 5 in self._loaded_pages else dict(self._initial_shortcuts)

    def enabled_plugins(self):
        if 7 in self._loaded_pages:
            return self._loaded_pages[7].enabled_plugins()
        enabled = self._plugin_manager.enabled if self._plugin_manager is not None else None
        return None if enabled is None else set(enabled)


def _add_folder_option(dialog, menu, folder_id, name):
    action = menu.addAction(name)
    action.setData(folder_id)
    action.setCheckable(True)
    action.setChecked(not folder_id)
    action.triggered.connect(lambda _checked=False: dialog._select_folder(action))
    return action


def _create_folder_for_dialog(dialog, folder_creator):
    folder_id, name = create_folder_dialog(dialog, folder_creator, dialog.folder_names)
    if not folder_id:
        return
    dialog.folder_names.add(name)
    action = _add_folder_option(dialog, dialog.folder_button.menu(), folder_id, name)
    dialog._select_folder(action)


class AddRoomDialog(AnimatedDialog):
    """输入房间号或直播间链接。"""

    def __init__(self, parent=None, *, room_id_resolver=None, folders=None, folder_creator=None):
        super().__init__(parent)
        self.setWindowTitle("添加直播间")
        self.resize(400, 170)
        self.room_id = ""
        self.folder_id = ""
        self.room_id_resolver = room_id_resolver
        self.folder_names = {folder['name'] for folder in folders or []}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("房间号或直播间链接"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("输入房间号或链接")
        self.edit.returnPressed.connect(self.accept)
        layout.addWidget(self.edit)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("添加到文件夹"))
        self.folder_button = QPushButton(default_folder(folders)["name"])
        self.folder_button.setObjectName("IconButton")
        self.folder_button.setToolTip("选择普通文件夹；智能文件夹会按规则自动归类")
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

        self.hint = QLabel("支持 B 站房间号")
        self.hint.setObjectName("AppSubtitle")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("添加")
        confirm.setObjectName("PrimaryButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def _select_folder(self, action) -> None:
        self.folder_id = action.data()
        self.folder_button.setText(action.text())
        for option in self.folder_button.menu().actions():
            option.setChecked(option is action)

    def accept(self) -> None:
        text = self.edit.text().strip()
        from .room_input import bili_room_id, extract_room_input, is_bili_short_url
        try:
            text = extract_room_input(text)
        except ValueError as error:
            self.hint.setText(str(error))
            self.hint.setStyleSheet(f"color: {theme.ERROR}")
            return
        if self.room_id_resolver is not None:
            try:
                room_id = self.room_id_resolver(text)
            except ValueError as error:
                self.hint.setText(str(error))
                self.hint.setStyleSheet(f"color: {theme.ERROR}")
                return
            if room_id:
                self.room_id = room_id
                super().accept()
                return
        # Short links are expanded later by the existing background info query.
        room_id = text if is_bili_short_url(text) else bili_room_id(text)
        if not room_id and '://' not in text:
            digits = re.findall(r"\d+", text)
            room_id = digits[0] if len(digits) == 1 else ""
        if not room_id:
            self.hint.setText("没识别到房间号，请检查输入")
            self.hint.setStyleSheet(f"color: {theme.ERROR}")
            return
        self.room_id = room_id
        super().accept()


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
