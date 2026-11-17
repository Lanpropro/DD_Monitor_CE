"""Account-menu coordination; identity, signals and Qt children belong to the sidebar."""
from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QWidget, QWidgetAction

from . import theme
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from .avatar_widgets import RoomStrip
from . import follow_folders, layouts, motion, theme, version as version_module


class SidebarAccountControl:
    def __init__(self, host):
        self.host = host

    def set_account(self, uname: str, pixmap=None, *, platform="bilibili", uid="") -> None:
        host = self.host
        host.account_row.set_account(uname, pixmap, platform=platform, uid=uid)
        host._sync_account_row_shape()
        host.account_row.setVisible(host._account_row_should_show())
        host._sync_account_row_width()
        host.refresh_strip()

    def clear_account(self) -> None:
        # 退出登录后**不隐藏**：这一格要当「登录」按钮继续露着（用户要求）
        host = self.host
        host.account_row.set_account("")
        host.account_row.setVisible(host._account_row_should_show())
        host._sync_account_row_shape()
        host._sync_account_row_width()

    def account_menu(self, *, popup_type, row_type) -> QMenu:
        """Account actions and only the shortcuts absent from the current toolbar."""
        host = self.host
        AccountPopupMenu = popup_type
        AccountRow = row_type
        menu = AccountPopupMenu(host)
        menu.setObjectName("AccountPopup")
        menu.setStyleSheet(f"""
            QMenu#AccountPopup {{ background: transparent; border: none; padding: 0; }}
            QMenu#AccountPopup::item {{ background: {theme.CONTENT}; border: 1px solid {theme.BORDER};
                           border-radius: 17px; padding: 8px 12px; margin: 3px 0; }}
            QMenu#AccountPopup::item:selected {{ background: {theme.CONTENT_HOVER}; }}
            QMenu#AccountPopup::separator {{ height: 6px; margin: 0; background: transparent; }}
        """)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        popup_width = host.account_row.width() if host.side == 'left' and not host.collapsed else 240
        menu.setFixedWidth(popup_width)
        account_actions = []
        if not host.account_row.uname:
            # 未登录时这一格就是「登录」按钮（用户要求：没登录也要放出来）
            menu.addAction("登录")
            menu.addSeparator()
        else:
            action = QWidgetAction(menu)
            action.setText("登录其他平台" if getattr(host, "can_login_other", True)
                           else "所有平台均已登录")
            button = QPushButton(action.text(), menu)
            button.setCursor(Qt.PointingHandCursor)
            button.setObjectName("AccountPopupButton")
            button.setFixedSize(popup_width, host.account_row.height() if not host.collapsed else 34)
            button.setStyleSheet(f"""QPushButton {{ padding: 0; min-height: 32px; text-align: center;
                background: {theme.CONTENT}; border: 1px solid {theme.BORDER};
                border-radius: {theme.CONTROL_HEIGHT // 2}px; }}
                QPushButton:hover {{ background: {theme.CONTENT_HOVER}; border-color: {theme.ACCENT}; }}
                QPushButton:pressed {{ background: {theme.ACCENT_SOFT}; }}""")
            def activate(_checked=False):
                menu.close()
                # 等 QMenu.exec 和当前鼠标回调退出，再构造模态登录窗口。
                # 否则窗口/浏览器初始化会重入尚未收尾的原生弹出菜单。
                QTimer.singleShot(0, host, host.loginRequested.emit)
            button.clicked.connect(activate)
            action.setDefaultWidget(button)
            menu.addAction(action)
            menu.addSeparator()
            for kind, account in reversed(getattr(host, "logged_accounts", [])):
                if kind == host.account_row.platform:
                    continue
                action = QWidgetAction(menu)
                item = QWidget(menu)
                item.setObjectName("AccountPopupItem")
                item.setStyleSheet("#AccountPopupItem { background: transparent; }")
                layout = QHBoxLayout(item)
                layout.setContentsMargins(0, 3, 0, 3)
                row = AccountRow(item, allow_logout=True)
                item.setFixedSize(popup_width, host.account_row.height() + 6 if not host.collapsed else 40)
                row.setFixedHeight(host.account_row.height() if not host.collapsed else 34)
                row.set_account(account.get("uname") or str(account.get("uid") or "已登录"),
                                account.get("_pixmap"), platform=kind, uid=account.get("uid"))
                row.name.setAlignment(Qt.AlignCenter)
                row.account_id.setAlignment(Qt.AlignCenter)
                if account.get("_login_expired"):
                    row.account_id.setText("登录已失效 · 请重新登录")
                    row.account_id.setStyleSheet(f"color: {theme.PINK};")
                    row.setToolTip("登录已失效，请通过上方登录按钮重新登录")
                row.arrow.hide()
                layout.addWidget(row, 1)
                button = row.logout_button
                button.setProperty("platform", kind)
                def logout(_checked=False, k=kind):
                    menu.close()
                    host.platformLogoutRequested.emit(k)
                row.logoutClicked.connect(logout)
                action.setDefaultWidget(item)
                menu.addAction(action)
                account_actions.append(action)
        if host.side == "top" and host.collapsed:
            menu.addSeparator()
            menu.addAction("导入关注")
            menu.addAction("+ 添加直播间")
        for action in account_actions:
            menu.removeAction(action)
            menu.addAction(action)
        return menu

    def open_account_menu(self) -> None:
        host = self.host
        if not host.account_row.uname and not host.collapsed:
            host.loginRequested.emit()
            return
        menu = host.account_menu()
        texts = [action.text() for action in menu.actions() if action.text()]
        size = menu.sizeHint()
        if host.side == "top":
            # 竖屏：贴着头排右侧那个账号头像弹（展开/收起都在）
            anchor = QRect(host.account_row.mapToGlobal(
                host.account_row.rect().topLeft()), host.account_row.size())
            position = QPoint(anchor.left(), anchor.bottom() + 6)
        elif host.collapsed:
            # 横屏收起：只剩头像，菜单贴着头像右侧展开
            anchor = host.account_row.mapToGlobal(host.account_row.rect().topRight())
            position = QPoint(anchor.x() + 6, anchor.y() - size.height() - 6)
        else:
            # 账号栏在最底部，菜单往上弹、右对齐整行
            anchor = host.account_row.mapToGlobal(host.account_row.rect().topRight())
            position = QPoint(anchor.x() - size.width(), anchor.y() - size.height() - 6)
        chosen = menu.exec(position)
        if chosen is None:
            return
        label = chosen.text()
        if label in ("退出登录", "登录", "登录其他平台", "所有平台均已登录"):
            if label != "退出登录":
                host.loginRequested.emit()
            else:
                host.logoutRequested.emit()
        elif label == "布局预设":
            host.open_layout_picker()
        elif label == '画中画':
            host.pictureInPictureRequested.emit()
        elif label == "设置":
            host.settingsRequested.emit()
        elif label == "导入关注":
            host.importFollowsClicked.emit()
        elif label == "+ 添加直播间":
            host.addRoomClicked.emit()

    def account_row_should_show(self) -> bool:
        """账号按钮什么时候露出来。

        用户 2026-09-18：**没登录也要露**（显示「登录」，点了弹扫码登录）；
        登录后横屏在侧栏底部、竖屏在横栏右侧那一块 / 收起态头像排旁边。
        """
        host = self.host
        return not host.select_mode

    def sync_account_row_shape(self) -> None:
        """Use an avatar in the portrait header; retain the original left-column shape."""
        host = self.host
        if host.side == "top":
            host.account_row.set_compact(True, avatar=RoomStrip.AVATAR, margin=1)
        else:
            host.account_row.set_compact(host.collapsed)

    def sync_account_row_width(self) -> None:
        """Keep portrait account access compact and release its width in landscape."""
        host = self.host
        row = host.account_row
        if host.side != "top":
            row.setMinimumWidth(0)
            row.setMaximumWidth(16_777_215)
            return
        row.setFixedWidth(row.avatar.width() + 2)
