"""在同一窗口内切换平台、登录和勾选关注。"""
import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel,
                              QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import bili
from .bili import FollowLoader
from .dialogs import FollowImportDialog
from .widgets import AccountRow, BRAND_ASSETS_DIR


class AccountPlatformDialog(QDialog):
    def __init__(self, owner, providers, *, import_follows=False, platform_kind="bilibili"):
        super().__init__(owner)
        self.owner = owner
        self.providers = {p.kind: p for p in providers.values()}
        self.import_follows = import_follows
        self.rooms = []
        self.folder_id = ""
        self.kind = ""
        self.page = None
        # 保留浏览器的控件树，避免切换时销毁或迁移窗口的图形渲染层。
        self._platform_pages = {}
        self._follow_pages = {}
        self._bili_loader = None
        self._pending_rooms = None
        self._closing_result = None
        self.setWindowTitle("导入关注" if import_follows else "登录")
        self.layout_box = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("平台"))
        self.platform_buttons = {}
        self.group = QButtonGroup(self)
        for kind, label in [("bilibili", "B站"), *[(p.kind, p.label) for p in providers.values()]]:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setObjectName("IconButton")
            icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms", kind + ".ico")
            button.setIcon(QIcon(icon_path))
            button.clicked.connect(lambda _checked=False, k=kind: self.select_platform(k))
            self.group.addButton(button)
            self.platform_buttons[kind] = button
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.layout_box.addLayout(toolbar)
        self.pages = QStackedWidget(self)
        self.layout_box.addWidget(self.pages, 1)
        self.select_platform(platform_kind)

    def _busy(self, busy):
        for button in self.platform_buttons.values():
            button.setEnabled(not busy)

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
            if browser_page:
                old.browser.stop()
            if not retained:
                old.deleteLater()
            self.page = None

    def _set_page(self, page):
        self._clear_page()
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
        self.resize(size.width() + 24, size.height() + 65)
        self.layout_box.activate()

    def select_platform(self, kind):
        if self._closing_result is not None or kind == self.kind:
            return
        if not self.platform_buttons[kind].isEnabled():
            return
        self._clear_page()
        self.kind = kind
        self.platform_buttons[kind].setChecked(True)
        if not self.import_follows and (bili.SESSION_DATA if kind == "bilibili"
                                        else kind in self.owner._accounts):
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
        if self.import_follows and kind in self._follow_pages:
            self._set_page(self._follow_pages[kind])
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
            page = self._platform_pages.get(kind)
            if page is None:
                auto_read = self.import_follows and kind in self.owner._accounts
                page = PlatformFollowDialog(self.providers[kind], self.pages, owner=self.owner,
                                            login_only=not self.import_follows, embedded=True,
                                            defer_login=auto_read)
                page.accountCleared.connect(self.owner._clear_platform_account)
                page.busyChanged.connect(self._busy)
                page.finished.connect(lambda result, p=page: self._page_finished(result, p))
                page.readFailed.connect(lambda _reason, p=page: self._platform_failed(p))
                self._platform_pages[kind] = page
                if auto_read:
                    self._show_loading(f"读取 {self.providers[kind].label}关注")
                    page._read()
                    return
            else:
                page.status.setText("请在官方页面完成登录，然后点击「读取关注」" if self.import_follows else
                                    "请在官方页面完成登录，然后点击「确认登录」")
                page.browser.load(QUrl(page._login_url))
            self._set_page(page)

    def _platform_failed(self, page):
        if self._closing_result is None and self.page.property("loading"):
            self._set_page(page)
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
            self.rooms = page.selected()
            self.folder_id = page.folder_id
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
        page = FollowImportDialog(rooms, existing, self.owner,
                                  folders=self.owner.sidebar.folder_state())
        page.finished.connect(self._page_finished)
        self._follow_pages[self.kind] = page
        self._set_page(page)
        faces = {str(room["room_id"]): room.get("face") for room in rooms if room.get("face")}
        self.owner._start_avatar_loader(faces, page.set_avatar)

    def done(self, result):
        if self._closing_result is not None:
            return
        self._closing_result = result
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
