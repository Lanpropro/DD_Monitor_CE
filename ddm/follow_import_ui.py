"""Follow import list rendering; selection data remains in FollowImportDialog."""
import os
from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QListView, QListWidget, QListWidgetItem, QMenu, QPushButton,
                              QLayout, QSizePolicy, QStyle, QStyledItemDelegate,
                              QVBoxLayout, QWidget)

from . import theme
from .account_widgets import AccountRow
from .playback_controls import RefreshButton
from .corner_geometry import continuous_path
from .widget_support import BRAND_ASSETS_DIR
from .settings_window import SettingsTitleBar


class ImportPlatformTabs(QWidget):
    """Reflect the host's selected platform; overflow keeps every provider reachable."""

    selectionRequested = Signal(str)

    def __init__(self, platforms, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumHeight(theme.CONTROL_HEIGHT)
        self._current = ''
        self.buttons = {}
        self.group = QButtonGroup(self)
        self.actions = {}
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)
        self._row.setSizeConstraint(QLayout.SetNoConstraint)
        self.menu = QMenu(self)
        for kind, label in platforms:
            button = QPushButton(label)
            button.setObjectName('IconButton')
            button.setCheckable(True)
            button.setAutoDefault(False)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(label)
            path = os.path.join(BRAND_ASSETS_DIR, 'platforms', 'huya.png' if kind == 'huya' else kind + '.ico')
            if not os.path.isfile(path):
                path = os.path.join(BRAND_ASSETS_DIR, 'platforms', 'generic.svg')
            button.setIcon(QIcon(path))
            button.setIconSize(QSize(18, 18))
            button.setFixedSize(min(148, max(64, button.fontMetrics().horizontalAdvance(label) + 44)),
                                theme.CONTROL_HEIGHT)
            button.clicked.connect(lambda _checked=False, key=kind: self.selectionRequested.emit(key))
            self._row.addWidget(button, 0, Qt.AlignTop)
            self.group.addButton(button)
            self.buttons[kind] = button
            action = self.menu.addAction(button.icon(), label)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, key=kind: self.selectionRequested.emit(key))
            self.actions[kind] = action
        self.more = QPushButton('…')
        self.more.setObjectName('IconButton')
        self.more.setAutoDefault(False)
        self.more.setFixedSize(34, theme.CONTROL_HEIGHT)
        self.more.setToolTip('其他平台')
        self.more.setAccessibleName('其他导入平台')
        self.more.setMenu(self.menu)
        self.more.setStyleSheet('QPushButton#IconButton {padding:0;} '
                               'QPushButton#IconButton::menu-indicator {image:none; width:0;}')
        self._row.addWidget(self.more, 0, Qt.AlignTop)
        self._row.addStretch(1)

    def set_current(self, kind):
        self._current = kind
        for key, button in self.buttons.items():
            button.setChecked(key == kind)
            self.actions[key].setChecked(key == kind)
        self._reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self):
        gap = self._row.spacing()
        available = self.width()
        total = sum(button.width() for button in self.buttons.values()) + gap * max(0, len(self.buttons) - 1)
        visible = set(self.buttons)
        if total > available:
            budget = max(0, available - self.more.width() - gap)
            visible = set()
            # The active platform remains visible even when it was chosen in overflow.
            order = ([self._current] if self._current in self.buttons else [])
            order += [key for key in self.buttons if key != self._current]
            for key in order:
                needed = self.buttons[key].width() + (gap if visible else 0)
                if needed <= budget:
                    visible.add(key)
                    budget -= needed
        for key, button in self.buttons.items():
            button.setVisible(key in visible)
            self.actions[key].setVisible(key not in visible)
        self.more.setVisible(len(visible) < len(self.buttons))


class AccountImportBar(QWidget):
    """Compact import header; AccountPlatformDialog owns account and platform state."""

    def __init__(self, platforms, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)
        self.titlebar = SettingsTitleBar(parent)
        self.titlebar.setMinimumHeight(38)
        self.titlebar.row.setContentsMargins(0, 0, 0, 0)
        self.titlebar.row.setSpacing(8)
        self.titlebar.breadcrumb.setText('导入关注')
        self.titlebar.close_button.setAccessibleName('关闭导入关注')
        self.titlebar.close_button.setToolTip('关闭导入关注')
        self.account = AccountRow(self)
        self.account.setObjectName('ImportAccount')
        self.account.setStyleSheet('QFrame#ImportAccount {background:transparent; border:none;}')
        self.account.setMinimumWidth(0)
        self.account.setCursor(Qt.ArrowCursor)
        self.refresh = RefreshButton(self, size=30, object_name='IconButton')
        self.refresh.setAccessibleName('刷新关注列表')
        self.refresh.setToolTip('重新读取当前平台关注')
        self.titlebar.row.insertWidget(self.titlebar.row.count() - 1, self.account)
        self.titlebar.row.insertWidget(self.titlebar.row.count() - 1, self.refresh)
        layout.addWidget(self.titlebar)
        self.platform = ImportPlatformTabs(platforms, self)
        layout.addWidget(self.platform)

    def set_account(self, account, kind):
        self.account.set_account(account.get('uname') or ('已登录' if account else ''),
                                 account.get('_pixmap'), platform=kind)
        self.account.arrow.hide()
        self.account.platform_badge.hide()
        text_width = self.account.name.fontMetrics().horizontalAdvance(self.account.name.text())
        self.account.setFixedWidth(min(160, max(78, text_width + 52)))


def paint_import_surface(widget):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    path = continuous_path(QRectF(widget.rect()).adjusted(.5, .5, -.5, -.5), 22)
    painter.fillPath(path, theme.qcolor(theme.BG))
    painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
    painter.drawPath(path)


class FollowImportItem(QListWidgetItem):
    def __lt__(self, other):
        return self.data(Qt.UserRole + 3) < other.data(Qt.UserRole + 3)


class FollowImportDelegate(QStyledItemDelegate):
    """Paint two-line rows without allocating a widget for every follow."""

    checkChanged = Signal()

    def __init__(self, existing, parent):
        super().__init__(parent)
        self.existing = existing

    def sizeHint(self, option, index):
        listing = self.parent()
        return QSize(max(240, listing.cell_width() - 8), listing.row_height())

    def paint(self, painter, option, index):
        room = index.data(Qt.UserRole)
        checked = index.data(Qt.CheckStateRole) == Qt.Checked.value
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(2, 2, -2, -2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.ACCENT_SOFT if checked else theme.CONTENT))
        painter.drawPath(continuous_path(QRectF(rect), 12))
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

class FollowImportList(QListWidget):
    """Own row input independently of delegate hit rectangles after scrolling."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(True)
        self.setFlow(QListView.LeftToRight)
        self.setSpacing(4)
        self.columns = 1

    def cell_width(self):
        return max(1, (self.viewport().width() - 2 * self.spacing() - 4) // self.columns)

    def row_height(self):
        return max(78 if self.columns == 2 else 64, self.fontMetrics().height() * 2 + 22)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.columns = 2 if self.viewport().width() >= 620 else 1
        self.setGridSize(QSize(self.cell_width(), self.row_height() + 8))
        self.doItemsLayout()

    def mousePressEvent(self, event):
        self._pressed_item = None
        if event.button() == Qt.LeftButton:
            self._pressed_item = self.itemAt(event.position().toPoint())
            self._press_position = event.position().toPoint()
            if self._pressed_item is not None:
                self.setCurrentItem(self._pressed_item)
                self.setFocus(Qt.MouseFocusReason)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        item = getattr(self, '_pressed_item', None)
        self._pressed_item = None
        if event.button() == Qt.LeftButton and item is not None:
            position = event.position().toPoint()
            if (self.itemAt(position) is item and
                    (position - self._press_position).manhattanLength() < QApplication.startDragDistance()):
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
                self.itemDelegate().checkChanged.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentItem() is not None:
            if not event.isAutoRepeat():
                item = self.currentItem()
                item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
                self.itemDelegate().checkChanged.emit()
            event.accept()
            return
        super().keyPressEvent(event)
