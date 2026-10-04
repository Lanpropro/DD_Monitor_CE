"""在同一窗口内切换平台、登录和勾选关注。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel,
                              QPushButton, QVBoxLayout, QWidget)

from . import bili
from .bili import FollowLoader
from .dialogs import FollowImportDialog
from .widgets import BRAND_ASSETS_DIR


class AccountPlatformDialog(QDialog):
    def __init__(self, owner, providers, *, import_follows=False, platform_kind="bilibili"):
        super().__init__(owner)
        self.owner = owner
        self.providers = {p.kind: p for p in providers.values()}
        self.import_follows = import_follows
        self.rooms = []
        self.kind = ""
        self.page = None
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
        self.select_platform(platform_kind)

    def _busy(self, busy):
        for button in self.platform_buttons.values():
            button.setEnabled(not busy)

    def _clear_page(self):
        if self.page is not None:
            old = self.page
            old.blockSignals(True)
            if isinstance(old, QDialog):
                old.reject()
            self.layout_box.removeWidget(old)
            old.hide()
            old.deleteLater()
            self.page = None

    def _set_page(self, page):
        self._clear_page()
        self.page = page
        size = page.size()
        page.setParent(self, Qt.Widget)
        self.layout_box.addWidget(page, 1)
        if isinstance(page, QDialog):
            page.finished.connect(self._page_finished)
        page.show()
        self.resize(size.width() + 24, size.height() + 65)

    def select_platform(self, kind):
        if self._closing_result is not None or kind == self.kind:
            return
        if not self.platform_buttons[kind].isEnabled():
            return
        self._clear_page()
        self.kind = kind
        self.platform_buttons[kind].setChecked(True)
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
            page = PlatformFollowDialog(self.providers[kind], self.owner,
                                        login_only=not self.import_follows)
            page.accountCleared.connect(self.owner._clear_platform_account)
            page.busyChanged.connect(self._busy)
            self._set_page(page)

    def _page_finished(self, result):
        if self._closing_result is not None:
            super().done(self._closing_result)
            return
        if result != QDialog.Accepted:
            self.reject()
            return
        if isinstance(self.page, FollowImportDialog):
            self.rooms = self.page.selected()
            self.accept()
            return
        if self.kind != "bilibili" and self.page.account:
            self.owner._accounts[self.kind] = dict(self.page.account)
            self.owner._render_account()
        if not self.import_follows:
            self.accept()
        elif self.kind == "bilibili":
            self._load_bili()
        else:
            self._show_rooms(self.page.rooms)

    def _load_bili(self):
        page = QWidget()
        page.resize(520, 620)
        layout = QVBoxLayout(page)
        self.status = QLabel("正在读取 B 站关注…")
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.retry_button = QPushButton("重新读取")
        self.retry_button.setObjectName("PrimaryButton")
        self.retry_button.clicked.connect(self._load_bili)
        self.retry_button.setEnabled(False)
        layout.addWidget(self.retry_button)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        self._set_page(page)
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
            self.status.setText("读取关注失败：" + reason)

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
        page = FollowImportDialog(rooms, existing, self.owner)
        self._set_page(page)
        faces = {str(room["room_id"]): room.get("face") for room in rooms if room.get("face")}
        self.owner._start_avatar_loader(faces, page.set_avatar)

    def done(self, result):
        if self._closing_result is not None:
            return
        self._closing_result = result
        self._busy(True)
        if isinstance(self.page, QDialog) and not self.page.isHidden():
            self.page.reject()
            # 平台请求取消后，子窗口的 finished 信号再结束主窗口。
            return
        super().done(result)
