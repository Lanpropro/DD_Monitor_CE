"""在同一窗口内切换平台、登录和勾选关注。"""
import os
from copy import deepcopy

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QDialog, QGridLayout, QLabel,
                              QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import bili, theme
from .bili import FollowLoader
from .dialogs import FollowImportDialog
from .widgets import AccountRow, BRAND_ASSETS_DIR


class FollowAccountResolver(QThread):
    updated = Signal(dict)
    progress = Signal(int, int)

    def __init__(self, platform, accounts, parent, *, start_index=0):
        super().__init__(parent)
        self.platform = platform
        self.accounts = deepcopy(accounts)
        self.next_index = start_index
        self.failures = 0

    def run(self):
        cancelled = self.isInterruptionRequested
        for index in range(self.next_index, len(self.accounts)):
            if cancelled():
                break
            account = self.accounts[index]
            if account.get("follow_account_ref") or not account.get("room_id") or account.get("live_known") is False:
                error_kind = ""
                try:
                    resolved = self.platform.resolve_follow_account(account, cancelled)
                except Exception as error:  # 单个账号失败不影响其余关注，也不覆盖原身份。
                    self.failures += 1
                    error_kind = type(error).__name__
                    resolved = dict(account)
                if cancelled():
                    break
                if resolved is not None:
                    resolved = dict(resolved, follow_resolve_error=error_kind,
                                    follow_resolve_note="未取得房间号" if not resolved.get("room_id") else
                                    "未取得直播状态" if resolved.get("live_known") is False else "")
                    self.updated.emit(resolved)
            self.next_index = index + 1
            self.progress.emit(self.next_index, len(self.accounts))


class AccountPlatformDialog(QDialog):
    def __init__(self, owner, providers, *, import_follows=False, platform_kind="bilibili", reauthenticate=False):
        super().__init__(owner)
        self.owner = owner
        self.providers = {p.kind: p for p in providers.values()}
        self.import_follows = import_follows
        self.reauthenticate = reauthenticate
        self._reauthenticate_kind = platform_kind
        self.rooms = []
        self._account_resolver = None
        self.folder_id = ""
        self.folder_changed = False
        self.folder_room_ids = []
        self.removed_ids = []
        self.pending_count = 0
        self.kind = ""
        self.page = None
        # 保留浏览器的控件树，避免切换时销毁或迁移窗口的图形渲染层。
        self._platform_pages = {}
        self._follow_pages = {}
        self._bili_loader = None
        self._pending_rooms = None
        self._closing_result = None
        self._pending_platform = ""
        self.setWindowTitle("导入关注" if import_follows else "登录")
        self.layout_box = QVBoxLayout(self)
        toolbar = QGridLayout()
        toolbar.addWidget(QLabel("平台"), 0, 0)
        self.platform_buttons = {}
        self.group = QButtonGroup(self)
        groups = [[("bilibili", "B站")]]
        owners = getattr(owner.plugins, "_platform_owner", {})
        plugin_rows = {}
        for provider in providers.values():
            plugin = owners.get(provider.kind, "domestic" if provider.kind in ("huya", "douyu", "douyin") else "global")
            if plugin not in plugin_rows:
                if provider.kind in ("huya", "douyu", "douyin"):
                    plugin_rows[plugin] = 0
                else:
                    plugin_rows[plugin] = len(groups)
                    groups.append([])
            groups[plugin_rows[plugin]].append((provider.kind, provider.label))
        for row, platforms in enumerate(groups):
            for column, (kind, label) in enumerate(platforms, 1):
                button = QPushButton(label)
                button.setFixedWidth(112)
                button.setProperty("platformLabel", label)
                button.setCheckable(True)
                button.setAutoDefault(False)
                button.setCursor(Qt.PointingHandCursor)
                button.setObjectName("IconButton")
                icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms",
                                         "huya.png" if kind == "huya" else kind + ".ico")
                button.setIcon(QIcon(icon_path))
                button.clicked.connect(lambda _checked=False, k=kind: self.select_platform(k))
                self.group.addButton(button)
                self.platform_buttons[kind] = button
                toolbar.addWidget(button, row, column)
        toolbar.setColumnStretch(max(map(len, groups)) + 1, 1)
        self.layout_box.addLayout(toolbar)
        self._update_platform_labels()
        self.pages = QStackedWidget(self)
        self.layout_box.addWidget(self.pages, 1)
        self.select_platform(platform_kind)

    def _update_platform_labels(self):
        for kind, button in self.platform_buttons.items():
            label = button.property("platformLabel")
            logged = bool(bili.SESSION_DATA) if kind == "bilibili" else (
                kind in self.owner._accounts and not self.owner._accounts[kind].get("_login_expired"))
            button.setText(label)
            button.setProperty("loggedIn", logged)
            button.setToolTip("已登录" if logged else "")
            button.setStyleSheet(f"""
                QPushButton#IconButton[loggedIn="true"] {{
                    background: {theme.CONTENT}; border-color: {theme.PINK};
                }}
                QPushButton#IconButton[loggedIn="true"]:hover {{
                    background: {theme.CONTENT_HOVER};
                }}
                QPushButton#IconButton[loggedIn="true"]:checked {{ border: 2px solid {theme.ACCENT}; }}
            """)

    def _busy(self, busy):
        self._update_platform_labels()
        page = self._platform_pages.get(self.kind)
        can_switch = page is not None and page._interactive_read and self._closing_result is None
        for button in self.platform_buttons.values():
            button.setEnabled(not busy or can_switch)
        if not busy and self._pending_platform and self._closing_result is None:
            kind, self._pending_platform = self._pending_platform, ""
            self.select_platform(kind)

    def _clear_page(self):
        if self.page is not None:
            old = self.page
            browser_page = old in self._platform_pages.values()
            retained = browser_page or old in self._follow_pages.values()
            if not retained:
                old.blockSignals(True)
                if isinstance(old, QDialog):
                    old.reject()
            self.pages.removeWidget(old)
            old.hide()
            if browser_page and hasattr(old, "browser"):
                old.browser.stop()
            if not retained:
                old.deleteLater()
            self.page = None

    def _set_page(self, page):
        self._clear_page()
        self._update_platform_labels()
        self.page = page
        size = page.property("preferredSize") or page.size()
        page.setProperty("preferredSize", size)
        if page.parentWidget() is not self.pages or page.isWindow():
            page.setParent(self.pages, Qt.Widget)
        self.pages.addWidget(page)
        self.pages.setCurrentWidget(page)
        if (isinstance(page, QDialog) and page not in self._platform_pages.values()
                and page not in self._follow_pages.values()):
            page.finished.connect(self._page_finished)
        page.show()
        self.resize(size.width() + 24, size.height() + self.layout_box.itemAt(0).sizeHint().height() + 24)
        self.layout_box.activate()
        if self.isVisible():
            self._center_on_owner()

    def _center_on_owner(self):
        screen = self.owner.screen().availableGeometry()
        target = self.owner.frameGeometry().center() if self.owner.isVisible() else screen.center()
        frame = self.frameGeometry()
        frame.moveCenter(target)
        x = max(screen.left(), min(frame.left(), screen.right() - frame.width() + 1))
        y = max(screen.top(), min(frame.top(), screen.bottom() - frame.height() + 1))
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._center_on_owner()

    def select_platform(self, kind, *, reread=False):
        if self._closing_result is not None or (kind == self.kind and not reread):
            return
        if not self.platform_buttons[kind].isEnabled():
            return
        page = self._platform_pages.get(self.kind)
        if page is not None and page._worker is not None:
            self._pending_platform = kind
            self.platform_buttons[self.kind].setChecked(True)
            page.cancel_read()
            return
        if self._account_resolver is not None:
            self._account_resolver.requestInterruption()
            old_page = self._follow_pages.get(self.kind)
            if hasattr(old_page, "resolve_button"):
                old_page._resolve_cursor = self._account_resolver.next_index
                old_page.resolve_button.setText("继续识别")
                old_page.resolve_button.setEnabled(True)
            self._account_resolver = None
        if reread:
            self._follow_pages.pop(kind, None)
        self._clear_page()
        self.kind = kind
        self.platform_buttons[kind].setChecked(True)
        notice = getattr(self.providers.get(kind), "account_login_notice", "")
        if notice:
            page = QWidget()
            page.resize(560, 220)
            layout = QVBoxLayout(page)
            label = QLabel(notice)
            label.setWordWrap(True)
            layout.addWidget(label)
            layout.addStretch()
            self._set_page(page)
            return
        if not self.import_follows and not (self.reauthenticate and kind == self._reauthenticate_kind) and (bili.SESSION_DATA if kind == "bilibili"
                                        else kind in self.owner._accounts and
                                        not self.owner._accounts[kind].get("_login_expired")):
            account = self.owner._accounts.get(kind, {"uname": "B站账号"})
            page = QWidget()
            page.resize(560, 220)
            layout = QVBoxLayout(page)
            layout.addWidget(QLabel("此平台已登录"))
            row = AccountRow(page)
            row.set_account(account.get("uname") or str(account.get("uid") or "已登录"),
                            account.get("_pixmap"), platform=kind, uid=account.get("uid"))
            row.arrow.hide()
            layout.addWidget(row)
            layout.addStretch()
            self._set_page(page)
            return
        if self.import_follows and not reread and kind in self._follow_pages:
            self._set_page(self._follow_pages[kind])
            return
        if self.import_follows and kind == "douyin" and not reread:
            cache = getattr(self.owner, "_douyin_follow_cache", None)
            uid = self.owner._accounts.get(kind, {}).get("uid")
            if uid and cache is not None and cache["uid"] == str(uid):
                self._show_rooms(deepcopy(cache["rooms"]))
                return
        if kind == "bilibili":
            if self.import_follows and bili.SESSION_DATA:
                self._load_bili()
            else:
                from .login import LoginWindow
                page = LoginWindow(self.owner)
                page.sessionData.connect(self.owner._on_login)
                self._set_page(page)
        else:
            from .platform_login import PlatformFollowDialog
            from .oauth_login import OAuthAccountDialog
            from .browser_account_dialog import BrowserAccountDialog, prefer_browser_login
            page = self._platform_pages.get(kind)
            if page is None:
                auto_read = self.import_follows and kind in self.owner._accounts
                dialog_type = (BrowserAccountDialog if prefer_browser_login(self.providers[kind], self.owner) else
                               OAuthAccountDialog if getattr(self.providers[kind], "oauth_provider", "") else
                               PlatformFollowDialog)
                page = dialog_type(self.providers[kind], self.pages, owner=self.owner,
                                   login_only=not self.import_follows, embedded=True,
                                   defer_login=auto_read)
                page.accountCleared.connect(self.owner._clear_platform_account)
                page.accountCleared.connect(lambda _kind: self._update_platform_labels())
                page.busyChanged.connect(self._busy)
                page.finished.connect(lambda result, p=page: self._page_finished(result, p))
                page.readFailed.connect(lambda _reason, p=page: self._platform_failed(p))
                self._platform_pages[kind] = page
                if (self.reauthenticate and kind == self._reauthenticate_kind
                        and dialog_type is PlatformFollowDialog):
                    page._forget()
                    self.reauthenticate = False
                elif (self.reauthenticate and kind == self._reauthenticate_kind
                        and dialog_type is BrowserAccountDialog):
                    page._cookies = []
                    self.reauthenticate = False
                if auto_read:
                    if (getattr(self.providers[kind], "follow_browser_init_script", "")
                            or getattr(self.providers[kind], "oauth_provider", "")):
                        self._set_page(page)
                        if hasattr(page, "browser"):
                            page.status.setText("正在读取官网关注列表；如出现验证，请在页面内完成")
                    else:
                        self._show_loading(f"读取 {self.providers[kind].label}关注")
                    page._read()
                    return
            else:
                if isinstance(page, BrowserAccountDialog):
                    page.status.setText("点击「登录并读取关注」复用登录状态或打开官方登录窗口" if self.import_follows else
                                        "点击「打开网页登录」，在独立浏览器完成登录")
                elif getattr(self.providers[kind], "oauth_provider", ""):
                    page.status.setText("点击「读取关注」复用授权或在系统浏览器授权" if self.import_follows else
                                        "点击「开始授权」，在系统浏览器完成登录")
                else:
                    page.status.setText("请在官方页面完成登录，然后点击「读取关注」" if self.import_follows else
                                        "请在官方页面完成登录，然后点击「确认登录」")
                if hasattr(page, "browser"):
                    page.browser.load(QUrl(page._login_url))
            self._set_page(page)
            if reread:
                page._read()

    def _platform_failed(self, page):
        if self._closing_result is None and self.page.property("loading"):
            self._set_page(page)
            if hasattr(page, "browser"):
                page.browser.load(QUrl(page._login_url))

    def _page_finished(self, result, page=None):
        if self._closing_result is not None:
            super().done(self._closing_result)
            return
        if result != QDialog.Accepted:
            self.reject()
            return
        page = page if page is not None else self.page
        if isinstance(page, FollowImportDialog):
            selected = page.selected()
            self.rooms = [room for room in selected if room.get("room_id")]
            if self.kind == "douyin" and callable(getattr(self.owner, "_cache_douyin_follows", None)):
                pending = [dict(room, pending_folder_id=(page.folder_id if page.folder_changed else
                                room.get("pending_folder_id", page.folder_id)))
                           for room in selected if not room.get("room_id")]
                self.pending_count = len(pending)
                self.owner._cache_douyin_follows(page.rooms, pending=pending)
            self.folder_id = page.folder_id
            self.folder_changed = page.folder_changed
            self.folder_room_ids = page.folder_room_ids()
            self.removed_ids = page.deselected_existing()
            self.accept()
            return
        if self.kind != "bilibili" and page.account:
            self.owner._accounts[self.kind] = dict(page.account)
            self.owner._render_account()
        if not self.import_follows:
            self.accept()
        elif self.kind == "bilibili":
            self._load_bili()
        else:
            self._show_rooms(page.rooms)

    def _show_loading(self, title):
        existing = {str(room.get("room_id")) for room in self.owner.sidebar.rooms()}
        page = FollowImportDialog([], existing, self.owner)
        page.setProperty("loading", True)
        page.header.setText(title)
        page.import_button.setEnabled(False)
        for button in page.filter_buttons:
            button.setEnabled(False)
        layout = QVBoxLayout(page.list.viewport())
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addStretch(1)
        self.status = QLabel("正在加载关注列表…")
        self.status.setObjectName("AppSubtitle")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.retry_button = QPushButton("重新读取")
        self.retry_button.setObjectName("IconButton")
        self.retry_button.setCursor(Qt.PointingHandCursor)
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self._load_bili)
        self.retry_button.setEnabled(False)
        self.retry_button.hide()
        layout.addWidget(self.retry_button, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self._set_page(page)

    def _load_bili(self):
        self._show_loading("读取 B 站关注")
        self._busy(True)
        self._pending_rooms = None
        loader = FollowLoader(self.owner)
        self._bili_loader = loader
        self.owner._follow_loader = loader
        loader.loaded.connect(self._bili_loaded)
        loader.failed.connect(self._bili_failed)
        loader.finished.connect(self._bili_finished)
        loader.finished.connect(loader.deleteLater)
        loader.start()

    def _bili_loaded(self, rooms):
        if self._closing_result is None and not self.owner._closing:
            self._pending_rooms = rooms

    def _bili_failed(self, reason):
        if self._closing_result is None:
            self.page.header.setText("关注读取失败")
            self.status.setText("读取关注失败：" + reason)
            self.retry_button.show()

    def _bili_finished(self):
        if self.owner._follow_loader is self._bili_loader:
            self.owner._follow_loader = None
        self._bili_loader = None
        if self._closing_result is not None or self.owner._closing:
            return
        self._busy(False)
        self.retry_button.setEnabled(True)
        if self._pending_rooms is not None:
            self._show_rooms(self._pending_rooms)

    def _show_rooms(self, rooms):
        existing = {str(room.get("room_id")) for room in self.owner.sidebar.rooms()}
        if self.kind == "douyin":
            cache = getattr(self.owner, "_douyin_follow_cache", None) or {}
            pending = {room.get("anchor_uid"): room for room in cache.get("pending", [])}
            if cache.get("uid") != str(self.owner._accounts.get("douyin", {}).get("uid") or ""):
                pending = {}
            rooms = [{key: value for key, value in room.items() if key != "pending_import"} for room in rooms]
            rooms = [dict(room, pending_import=True,
                          pending_folder_id=pending[room.get("anchor_uid")].get("pending_folder_id", ""))
                     if room.get("anchor_uid") in pending else dict(room) for room in rooms]
            reference = getattr(self.providers.get("douyin"), "follow_account_reference", None)
            if callable(reference):
                existing_accounts = {str(room.get("anchor_uid")): room for room in self.owner.sidebar.rooms()
                                     if room.get("platform") == "douyin" and room.get("anchor_uid")}
                converted = []
                for room in rooms:
                    saved = existing_accounts.get(str(room.get("anchor_uid")))
                    if saved is not None:
                        room = dict(room, room_id=saved["room_id"],
                                    follow_account_ref=saved.get("follow_account_ref", False))
                    if not room.get("room_id") or room.get("follow_account_ref"):
                        room = reference(room)
                    if saved is None and room.get("resolved_room_id") in existing:
                        room = dict(room, room_id=room["resolved_room_id"], follow_account_ref=False)
                    converted.append(room)
                rooms = converted
        page = FollowImportDialog(rooms, existing, self.owner,
                                  folders=self.owner.sidebar.folder_state(),
                                  folder_creator=self.owner.sidebar.create_folder,
                                  room_menu=self.kind == "douyin")
        if self.kind == "douyin":
            uid = self.owner._accounts.get(self.kind, {}).get("uid")
            if uid:
                cache_follows = getattr(self.owner, "_cache_douyin_follows", None)
                if callable(cache_follows):
                    cache_follows(rooms)
                else:
                    self.owner._douyin_follow_cache = {"uid": str(uid), "rooms": deepcopy(rooms)}
            page.reread_button = QPushButton("重新读取", page)
            page.reread_button.setObjectName("IconButton")
            page.reread_button.setCursor(Qt.PointingHandCursor)
            page.reread_button.setAutoDefault(False)
            page.reread_button.clicked.connect(lambda: self.select_platform("douyin", reread=True))
            page.layout().itemAt(page.layout().count() - 1).layout().insertWidget(0, page.reread_button)
            page.platform_notice = QLabel("受抖音网页接口及访问验证限制，部分未开播账号的直播间资料可能暂时无法完整获取。"
                                          "你仍可直接勾选账号导入，软件会随后台刷新继续查询", page)
            page.platform_notice.setObjectName("SettingsHint")
            page.platform_notice.setWordWrap(True)
            page.layout().insertWidget(1, page.platform_notice)
        page.finished.connect(self._page_finished)
        self._follow_pages[self.kind] = page
        page.avatarRequested.connect(lambda faces: self.owner._start_avatar_loader(faces, page.set_avatar))
        if self.kind == "douyin" and callable(getattr(self.providers.get("douyin"), "resolve_follow_account", None)):
            page._resolve_cursor = 0
            page.resolve_status = QLabel("列表已读取，可勾选导入。", page)
            if not callable(getattr(self.providers["douyin"], "follow_account_reference", None)):
                page.resolve_status.setText("待识别账号仅保存选择，取得房间号前不会加入关注栏；更新插件可直接按账号导入。")
            page.resolve_status.setObjectName("SettingsHint")
            page.resolve_status.setWordWrap(True)
            page.layout().insertWidget(2, page.resolve_status)
            page.resolve_status.setVisible(not callable(getattr(self.providers["douyin"], "follow_account_reference", None)))
            page.resolve_button = QPushButton("补充识别", page)
            page.resolve_button.setObjectName("IconButton")
            page.resolve_button.setCursor(Qt.PointingHandCursor)
            page.resolve_button.setAutoDefault(False)
            page.resolve_button.clicked.connect(lambda: self._resolve_accounts(page))
            page.layout().itemAt(page.layout().count() - 1).layout().insertWidget(1, page.resolve_button)
        self._set_page(page)
        page.request_visible_avatars()
        # 打开磁盘缓存不触发网络；新读取的列表才自动补充。
        if hasattr(page, "resolve_button") and "douyin" in self._platform_pages:
            self._resolve_accounts(page)

    def _resolve_accounts(self, page):
        if self._account_resolver is not None:
            self._account_resolver.requestInterruption()
            page.resolve_button.setText("正在停止…")
            page.resolve_button.setEnabled(False)
            return
        start = page._resolve_cursor if page._resolve_cursor < len(page.rooms) else 0
        worker = FollowAccountResolver(self.providers["douyin"], page.rooms, self.owner, start_index=start)
        self._account_resolver = worker
        running = getattr(self.owner, "_platform_info_running", None)
        if running is not None:
            running.add(worker)
        page.resolve_button.setText("停止识别")
        page.resolve_status.setText(f"正在识别直播间：已处理 {start}/{len(page.rooms)} 个关注。")
        page.resolve_status.show()
        def update(account):
            if (self._account_resolver is not worker or worker.isInterruptionRequested()
                    or self._closing_result is not None or getattr(self.owner, "_closing", False)):
                return
            page.update_account(account)
            cache = getattr(self.owner, "_cache_douyin_follows", None)
            if callable(cache):
                cache(page.rooms)
        def progress(current, total):
            if self._account_resolver is worker and self._closing_result is None:
                page.resolve_status.setText(f"正在识别直播间：已处理 {current}/{total} 个关注，"
                                            "已识别的直播间可随时勾选导入。")
        def finished():
            if running is not None:
                running.discard(worker)
            if self._account_resolver is worker:
                self._account_resolver = None
                page._resolve_cursor = worker.next_index
                page.resolve_button.setEnabled(True)
                page.resolve_button.setText("继续识别" if worker.next_index < len(page.rooms) else "补充识别")
                state = "识别已停止" if worker.isInterruptionRequested() else "识别完成"
                pending = sum(not room.get("room_id") or (bool(room.get("follow_account_ref")) and
                              not room.get("resolved_room_id")) for room in page.rooms)
                unknown = sum(bool(room.get("room_id")) and room.get("live_known") is False for room in page.rooms)
                page.resolve_status.hide()
                print(f"[抖音关注识别] 状态={state} 已处理={worker.next_index}/{len(page.rooms)} "
                      f"待识别={pending} 状态未知={unknown} 失败={worker.failures}")
        worker.progress.connect(progress)
        worker.updated.connect(update)
        worker.finished.connect(finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def done(self, result):
        if self._closing_result is not None:
            return
        self._closing_result = result
        if self._account_resolver is not None:
            self._account_resolver.requestInterruption()
            self._account_resolver = None
        self._busy(True)
        platform_page = self._platform_pages.get(self.kind)
        if platform_page is not None and platform_page._worker is not None:
            platform_page.reject()
            return
        if isinstance(self.page, QDialog) and not self.page.isHidden():
            self.page.reject()
            # 平台请求取消后，子窗口的 finished 信号再结束主窗口。
            return
        super().done(result)
