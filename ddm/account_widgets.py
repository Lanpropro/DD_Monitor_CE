"""Account rows and account-menu drawing; authentication stays with the host."""
import os
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPalette
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QStyle, QStyleOptionMenuItem, QVBoxLayout,
    QWidget, QWidgetAction
)

from . import theme
from .avatar_widgets import Avatar
from .ui.labels import ElidedLabel
from .widget_support import BRAND_ASSETS_DIR, _allow_shrink, _ignore_mouse


class AccountPopupMenu(QMenu):
    def paintEvent(self, event):
        painter = QPainter(self)
        for action in self.actions():
            if not action.isVisible() or isinstance(action, QWidgetAction):
                continue
            option = QStyleOptionMenuItem()
            self.initStyleOption(option, action)
            option.rect = self.actionGeometry(action)
            text, option.text = option.text, ''
            self.style().drawControl(QStyle.CE_MenuItem, option, painter, self)
            if text and not action.isSeparator():
                self.style().drawItemText(painter, option.rect, Qt.AlignCenter, option.palette,
                                          bool(option.state & QStyle.State_Enabled), text, QPalette.Text)


class AccountRow(QFrame):
    """侧栏底部的已登录账号：头像 + 昵称，点击弹出菜单。"""

    clicked = Signal()
    logoutClicked = Signal()

    def __init__(self, parent=None, *, allow_logout=False):
        super().__init__(parent)
        self.setObjectName("AccountRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)          # 和底部两个按钮同高、同圆角
        self.uname = ""
        self.platform = ""
        self.uid = ""
        self._allow_logout = allow_logout

        layout = QHBoxLayout(self)
        # 头像 26px：上下各留 4px 正好 34px 高，内容才能真的垂直居中
        # （原来留 6px，26 的头像塞不进 22 的空间，整行看着是偏的）
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        self.avatar = Avatar("?", 3, 26)
        layout.addWidget(self.avatar)
        self.platform_badge = QLabel(self)
        self.platform_badge.setFixedSize(12, 12)
        self.platform_badge.setStyleSheet("background: transparent; border: none;")
        _ignore_mouse(self.platform_badge)
        self.platform_badge.hide()
        self.account_text = QWidget()
        text_layout = QVBoxLayout(self.account_text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self.name = ElidedLabel("")
        self.name.setObjectName("AccountName")
        _ignore_mouse(self.name)
        _allow_shrink(self.name)
        text_layout.addWidget(self.name)
        self.account_id = ElidedLabel("")
        self.account_id.setObjectName("AccountId")
        self.account_id.setStyleSheet("font-size: 10px;")
        self.account_id.setFixedHeight(12)
        _ignore_mouse(self.account_id)
        _allow_shrink(self.account_id)
        text_layout.addWidget(self.account_id)
        self.account_id.hide()
        _allow_shrink(self.account_text)
        _ignore_mouse(self.account_text)
        layout.addWidget(self.account_text, 1)
        layout.addWidget(self.platform_badge)
        self.arrow = QLabel("⋯")
        self.arrow.setObjectName("NavSub")
        _ignore_mouse(self.arrow)
        layout.addWidget(self.arrow)
        self.logout_button = QPushButton("退出", self)
        self.logout_button.setObjectName("AccountLogoutButton")
        self.logout_button.setStyleSheet(f"""#AccountLogoutButton {{padding: 0; min-height: 22px; min-width: 46px; text-align: center;
            font-size: 11px; color: {theme.TEXT2}; background: {theme.CONTENT};
            border: 1px solid {theme.BORDER}; border-radius: 8px;}}
            #AccountLogoutButton:hover {{background: {theme.CONTENT_HOVER}; color: {theme.TEXT1};}}""")
        self.logout_button.setFixedSize(48, 24)
        self.logout_button.clicked.connect(self.logoutClicked)
        layout.addWidget(self.logout_button)
        self.logout_button.hide()
        self._layout = layout
        self._compact_spacer = False

    def set_account(self, uname: str, pixmap=None, *, platform="bilibili", uid="") -> None:
        self.uname = uname or ""
        self.platform = platform if self.uname else ""
        self.uid = str(uid or "") if self.uname else ""
        self.logout_button.setVisible(self._allow_logout and bool(self.uname)
                                      and not getattr(self, "_compact", False))
        self.account_id.setText("ID: " + self.uid if self.uid else "")
        self.account_id.setVisible(bool(self.uid))
        self.name.setStyleSheet("font-size: 11px;" if self.uid else "")
        self.name.setMaximumHeight(14 if self.uid else 16_777_215)
        if pixmap is None:
            self.avatar._source = None
            self.avatar.clear()
        if self.uname:
            self.name.setText(self.uname)
            self.arrow.setVisible(not self._allow_logout and not getattr(self, "_compact", False))
            self.setToolTip(self.uname + (" · ID: " + self.uid if self.uid else ""))
            icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms",
                                     "huya.png" if platform == "huya" else platform + ".ico")
            if not os.path.isfile(icon_path):
                icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms", "generic.svg")
            self.platform_badge.setPixmap(QIcon(icon_path).pixmap(12, 12))
            self.platform_badge.setAccessibleName(platform)
            self.platform_badge.setVisible(not getattr(self, "_compact", False))
            self.avatar.set_color(None)          # 回到彩色（哈希取的）
            if pixmap is not None:
                self.avatar.set_pixmap_image(pixmap)
            else:
                self.avatar.setText(self.uname[0])
            return
        # 未登录：这一格当「登录」按钮（用户要求：没登录也放出来）。
        # 底色用中性色，别像彩色头像那么显眼
        self.name.setText("登录")
        self.avatar.setText("登")
        self.avatar.set_color(theme.CONTENT_HOVER)
        self.arrow.setVisible(False)
        self.platform_badge.hide()
        self.setToolTip("选择平台并登录账号")

    def set_compact(self, compact: bool, *, avatar: int | None = None,
                    margin: int = 6) -> None:
        """侧栏收起后只留头像：尺寸跟列表里的主播头像一样，同样居中。

        avatar / margin：竖屏横栏收起时账号头像要和头排头像同尺寸、同一行
        （那边一行只有 36px），所以允许指名头像大小和上下留白。
        """
        compact = bool(compact)
        size = theme.AVATAR_SIZE if avatar is None else int(avatar)
        state = (compact, size, int(margin))
        if state == getattr(self, "_compact_state", None):
            return
        self._compact_state = state
        self._compact = compact
        self.account_text.setVisible(not compact)
        # 未登录时这一格是「登录」按钮，不该带菜单那个 ⋯
        self.arrow.setVisible(not self._allow_logout and not compact and bool(self.uname))
        self.logout_button.setVisible(self._allow_logout and not compact and bool(self.uname))
        self.avatar.set_size(size if compact else 26)
        self.platform_badge.setVisible(not compact and bool(self.uname))
        self.setFixedHeight(size + margin * 2 if compact else 34)
        if compact and not self._compact_spacer:
            self._layout.insertStretch(0, 1)
            self._layout.addStretch(1)
            self._compact_spacer = True
        elif not compact and self._compact_spacer:
            item = self._layout.takeAt(self._layout.count() - 1)
            del item
            item = self._layout.takeAt(0)
            del item
            self._compact_spacer = False
        if compact:
            self._layout.setContentsMargins(0, margin, 0, margin)
        else:
            # 展开态：34 高的行里放 26 的头像，上下各 4 才真的居中
            self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(0 if compact else 8)
        self.setToolTip(self.uname + (" · ID: " + self.uid if self.uid else "") if self.uname else
                       "选择平台并登录账号")

    def mouseReleaseEvent(self, event) -> None:
        # 未登录时这一格是「登录」按钮，也要能点 —— 以前这里卡了 `and self.uname`，
        # 登录按钮点下去什么也不发生（用户实测）
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
