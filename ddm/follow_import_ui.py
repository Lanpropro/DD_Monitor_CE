"""Follow import list rendering; selection data remains in FollowImportDialog."""
from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QStyle, QStyledItemDelegate,
                              QVBoxLayout, QWidget)

from . import theme
from .account_widgets import AccountRow
from .playback_controls import RefreshButton
from .ui.select import SelectControl


class AccountImportBar(QWidget):
    """Compact import source presentation; AccountPlatformDialog owns platform state."""

    def __init__(self, platforms, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        title = QLabel('导入关注')
        title.setObjectName('AppTitle')
        layout.addWidget(title)
        row = QHBoxLayout()
        self.platform = SelectControl()
        self.platform.setAccessibleName('导入平台')
        self.platform.setMinimumContentsLength(4)
        for kind, label in platforms:
            self.platform.addItem(label, kind)
        row.addWidget(self.platform)
        self.account = AccountRow(self)
        self.account.setMinimumWidth(0)
        self.account.setCursor(Qt.ArrowCursor)
        row.addWidget(self.account, 1)
        self.refresh = RefreshButton(self, size=34, object_name='IconButton')
        self.refresh.setAccessibleName('刷新关注列表')
        self.refresh.setToolTip('重新读取当前平台关注')
        row.addWidget(self.refresh)
        layout.addLayout(row)

    def set_account(self, account, kind):
        self.account.set_account(account.get('uname') or ('已登录' if account else ''),
                                 account.get('_pixmap'), platform=kind)
        self.account.arrow.hide()
        self.account.platform_badge.hide()


class FollowImportDelegate(QStyledItemDelegate):
    """Paint two-line rows without allocating a widget for every follow."""

    checkChanged = Signal()

    def __init__(self, existing, parent):
        super().__init__(parent)
        self.existing = existing

    def sizeHint(self, option, index):
        return QSize(240, max(64, option.fontMetrics.height() * 2 + 22))

    def paint(self, painter, option, index):
        room = index.data(Qt.UserRole)
        checked = index.data(Qt.CheckStateRole) == Qt.Checked.value
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(2, 2, -2, -2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.ACCENT_SOFT if checked else theme.CONTENT))
        painter.drawRoundedRect(QRectF(rect), 10, 10)
        avatar = QRect(rect.left() + 12, rect.center().y() - 16, 32, 32)
        icon = index.data(Qt.DecorationRole)
        if icon is not None and not icon.isNull():
            icon.paint(painter, avatar)
        else:
            painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
            painter.drawEllipse(avatar)
            painter.setPen(theme.qcolor(theme.TEXT2))
            painter.drawText(avatar, Qt.AlignCenter, room['uname'][:1])
        checkbox = QRect(rect.right() - 30, rect.center().y() - 9, 18, 18)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if checked else theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor(theme.ACCENT if checked else theme.CONTENT_HOVER))
        painter.drawRoundedRect(QRectF(checkbox), 5, 5)
        if checked:
            painter.setPen(QPen(theme.qcolor(theme.BG), 2))
            painter.drawLine(checkbox.left() + 4, checkbox.top() + 9, checkbox.left() + 7, checkbox.top() + 12)
            painter.drawLine(checkbox.left() + 7, checkbox.top() + 12, checkbox.left() + 14, checkbox.top() + 5)
        if option.state & QStyle.State_HasFocus:
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(rect).adjusted(1, 1, -1, -1), 10, 10)
        left = avatar.right() + 12
        right = checkbox.left() - 12
        font = option.font
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(theme.qcolor(theme.TEXT1))
        metrics = QFontMetrics(font)
        name_rect = QRect(left, rect.top() + 8, max(0, right - left), metrics.height())
        painter.drawText(name_rect, Qt.AlignVCenter,
                         metrics.elidedText(room['uname'], Qt.ElideRight, name_rect.width()))
        font.setBold(False)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        status = ('待识别' if not room.get('room_id') else '状态待刷新' if room.get('live_known') is False
                  else '直播中' if room['live'] else '未开播')
        if room.get('follow_resolve_error'):
            status += ' · 识别失败'
        elif room.get('title'):
            status += ' · ' + room['title']
        if str(room['room_id']) in self.existing:
            badge = '已关注'
            width = metrics.horizontalAdvance(badge)
            painter.setPen(theme.qcolor(theme.TEXT2))
            painter.drawText(QRect(right - width, name_rect.bottom() + 3, width, metrics.height()),
                             Qt.AlignVCenter, badge)
            right -= width + 12
        painter.setPen(theme.qcolor(theme.PINK if room.get('live') else theme.TEXT2))
        status_rect = QRect(left, name_rect.bottom() + 3, max(0, right - left), metrics.height())
        painter.drawText(status_rect, Qt.AlignVCenter,
                         metrics.elidedText(status, Qt.ElideRight, status_rect.width()))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.parent().setCurrentIndex(index)
            return True
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            toggle = option.rect.contains(event.position().toPoint())
        else:
            return event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)
        if toggle:
            checked = index.data(Qt.CheckStateRole) == Qt.Checked.value
            model.setData(index, Qt.Unchecked if checked else Qt.Checked, Qt.CheckStateRole)
            self.checkChanged.emit()
        return True


class FollowImportList(QListWidget):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentItem() is not None:
            if not event.isAutoRepeat():
                item = self.currentItem()
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
                self.itemDelegate().checkChanged.emit()
            event.accept()
            return
        super().keyPressEvent(event)
