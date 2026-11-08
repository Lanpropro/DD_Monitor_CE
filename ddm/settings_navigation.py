"""Follow-style settings categories and a dialog-scoped pointer dwell controller."""
from time import monotonic
import weakref

from PySide6.QtCore import QByteArray, QEvent, QObject, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QCursor, QFont, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                              QListWidgetItem, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)
from shiboken6 import isValid

from . import motion, theme
from .corner_geometry import continuous_path
from .search import matches_text
from .sidebar_navigation import NavigationButton, PATHS


GROUPS = ((0, 2, '基础偏好'), (2, 6, '观看与互动'), (6, 9, '系统与扩展'))
ICONS = {
    'general': PATHS['settings'],
    'appearance': '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    'danmaku': '<path d="M4 4h16v14h-8l-5 3v-3H4ZM8 9h8M8 13h5"/>',
    'recording': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/>',
    'notifications': '<path d="M6 9a6 6 0 0 1 12 0v6l2 3H4l2-3ZM10 21h4M12 2v1"/>',
    'shortcuts': '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M6 9h1M11 9h1M16 9h1M6 12h1M11 12h1M16 12h1M7 16h10"/>',
    'tray': '<path d="M3 13v7h18v-7M12 3v11M8 10l4 4 4-4"/>',
    'plugins': '<path d="M4 4h6V2a2 2 0 0 1 4 0v2h6v6h2a2 2 0 0 1 0 4h-2v6h-6v-2a2 2 0 0 0-4 0v2H4v-6H2a2 2 0 0 1 0-4h2Z"/>',
    'updates': '<path d="M5 8a8 8 0 0 1 14-2l2 2M21 3v5h-5M19 16a8 8 0 0 1-14 2l-2-2M3 21v-5h5"/>',
}


def _icon(painter, key, rect, color):
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color.name()}" stroke-opacity="{color.alphaF()}" '
           'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
           + ICONS[key] + '</svg>')
    QSvgRenderer(QByteArray(svg.encode())).render(painter, rect)


class SettingsCategoryDelegate(QStyledItemDelegate):
    def __init__(self, navigation):
        super().__init__(navigation.nav)
        self.navigation = weakref.proxy(navigation)

    def sizeHint(self, option, index):
        heading = self.navigation.heading(index.row())
        return QSize(40, 44 + (28 if heading and not self.navigation.collapsed else
                              10 if heading and index.row() else 0))

    def paint(self, painter, option, index):
        nav = self.navigation
        heading = nav.heading(index.row())
        header = 28 if heading and not nav.collapsed else 10 if heading and index.row() else 0
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        # Own the complete row, including the group heading, so a selected first
        # row never paints the section title with the item's hover background.
        from .skin_parts import values_for
        surface = values_for('settings.navigation')
        background = surface.get('background', None if surface.get('image') else theme.SIDEBAR)
        if background is not None:
            painter.fillRect(option.rect, theme.qcolor(background))
        font = QFont(option.font)
        if heading and not nav.collapsed:
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(theme.qcolor(theme.TEXT3))
            painter.drawText(QRectF(option.rect).adjusted(12, 0, -8, -44), Qt.AlignVCenter, heading)
        elif header:
            painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
            painter.drawLine(option.rect.left()+12, option.rect.top()+4,
                             option.rect.right()-12, option.rect.top()+4)
        rect = QRectF(option.rect).adjusted(3, header+3, -3, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if selected or hovered:
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1) if selected and not nav.collapsed else Qt.NoPen)
            painter.setBrush(theme.qcolor(theme.TEXT1 if selected and nav.collapsed else
                                         theme.ACCENT_SOFT if selected else theme.CONTENT_HOVER))
            painter.drawPath(continuous_path(rect, theme.RADIUS_MD))
        color = theme.qcolor(theme.BG if selected and nav.collapsed else theme.ACCENT if selected else theme.TEXT2)
        icon_rect = QRectF(rect.left()+10, rect.center().y()-10, 20, 20)
        if nav.collapsed:
            icon_rect.moveCenter(rect.center())
        _icon(painter, index.data(Qt.UserRole), icon_rect, color)
        if not nav.collapsed:
            font.setPixelSize(14)
            font.setWeight(QFont.DemiBold if selected else QFont.Normal)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(rect.adjusted(42, 0, -20, 0), Qt.AlignVCenter, index.data())
        if index.data(Qt.UserRole+1):
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(theme.ERROR))
            painter.drawEllipse(QRectF(rect.right()-11, rect.top()+5, 6, 6) if nav.collapsed else
                                QRectF(rect.right()-17, rect.center().y()-3, 6, 6))
        if option.state & QStyle.State_HasFocus:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.qcolor(theme.TEXT1), 1))
            painter.drawPath(continuous_path(rect.adjusted(2, 2, -2, -2), theme.RADIUS_MD-2))
        painter.restore()


class SettingsNavigation(QWidget):
    EXPANDED_WIDTH = 224
    COMPACT_WIDTH = 58

    def __init__(self, pages, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsNavigation')
        self.setProperty('skinPart', 'settings.navigation')
        self.setAttribute(Qt.WA_StyledBackground)
        self.collapsed = False
        self.setFixedWidth(self.EXPANDED_WIDTH)
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 12, 8, 12)
        box.setSpacing(8)
        row = QHBoxLayout()
        self.title = QLabel('设置')
        self.title.setObjectName('SettingsNavigationTitle')
        self.rail_button = NavigationButton('展开设置分类', 'list', self)
        self.rail_button.clicked.connect(self.expand)
        self.rail_button.hide()
        row.addWidget(self.title)
        row.addWidget(self.rail_button)
        box.addLayout(row)
        self.search = QLineEdit(self)
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('搜索设置分类')
        self.search.setAccessibleName('搜索设置分类')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        box.addWidget(self.search)
        self.nav = QListWidget(self)
        self.nav.setObjectName('SettingsNav')
        self.nav.setProperty('customItemSurface', True)
        self.nav.setAccessibleName('设置分类')
        self.nav.setFocusPolicy(Qt.StrongFocus)
        self.nav.setMouseTracking(True)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.nav.setItemDelegate(SettingsCategoryDelegate(self))
        for key, label in pages:
            item = QListWidgetItem(label, self.nav)
            item.setData(Qt.UserRole, key)
            item.setToolTip(label)
        box.addWidget(self.nav, 1)
        self.empty_hint = QLabel('没有匹配的设置分类')
        self.empty_hint.setObjectName('SettingsHint')
        self.empty_hint.hide()
        box.addWidget(self.empty_hint)
        self.footer = QLabel('DD监控室CE')
        self.footer.setObjectName('SectionLabel')
        box.addWidget(self.footer)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(200)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.valueChanged.connect(self._set_width)

    def heading(self, row):
        for start, end, name in GROUPS:
            if start <= row < end:
                first = next((i for i in range(start, end) if not self.nav.isRowHidden(i)), None)
                return name if first == row else None

    def _filter(self, query):
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            item.setHidden(not all(matches_text(item.text(), word) for word in query.split()))
        self.empty_hint.setVisible(all(self.nav.isRowHidden(i) for i in range(self.nav.count())))
        self.nav.doItemsLayout()

    def _set_width(self, width):
        self.setFixedWidth(round(width))

    def expand(self):
        self.set_collapsed(False)

    def set_collapsed(self, collapsed, *, animate=True):
        target = self.COMPACT_WIDTH if collapsed else self.EXPANDED_WIDTH
        if collapsed == self.collapsed and (self.animation.state() == QVariantAnimation.Running or self.width() == target):
            if animate:
                return
        self.animation.stop()
        self.collapsed = collapsed
        if collapsed:
            self.search.clear()
        self.title.setVisible(not collapsed)
        self.search.setVisible(not collapsed)
        self.footer.setVisible(not collapsed)
        self.rail_button.setVisible(collapsed)
        self.nav.doItemsLayout()
        if animate and motion.enabled() and self.isVisible():
            self.animation.setStartValue(self.width())
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self.setFixedWidth(target)


class SettingsPointerNavigation(QObject):
    """Only poll while this settings dialog is visible; never install OS hooks."""
    DWELL_SECONDS = 2.0

    def __init__(self, dialog, navigation, content):
        super().__init__(dialog)
        self.dialog = weakref.ref(dialog)
        self.navigation = weakref.proxy(navigation)
        self.content = weakref.proxy(content)
        self.since = None
        self.keyboard = False
        self.last_position = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.sample)
        dialog.installEventFilter(self)

    def eventFilter(self, watched, event):
        dialog = self.dialog()
        if dialog is None or not isValid(dialog):
            if isValid(self.timer):
                self.timer.stop()
            QApplication.instance().removeEventFilter(self)
            return False
        kind = event.type()
        if watched == dialog:
            if kind == QEvent.Show:
                QApplication.instance().installEventFilter(self)
                self.timer.start()
            elif kind in (QEvent.Hide, QEvent.Close):
                self.timer.stop()
                self.since = self.last_position = None
                self.keyboard = False
                QApplication.instance().removeEventFilter(self)
                self.navigation.set_collapsed(False, animate=False)
            elif kind == QEvent.WindowDeactivate:
                self.since = None
        if (kind == QEvent.KeyPress and isinstance(watched, QWidget)
                and (watched == dialog or dialog.isAncestorOf(watched))):
            self.keyboard = True
            self.since = None
            self.navigation.set_collapsed(False, animate=False)
        elif kind in (QEvent.MouseMove, QEvent.Enter, QEvent.Leave) and self.timer.isActive():
            self.sample()
        return False

    def sample(self):
        dialog = self.dialog()
        if dialog is None or not isValid(dialog):
            self.timer.stop()
            QApplication.instance().removeEventFilter(self)
            return
        position = QCursor.pos()
        if self.last_position is not None and position != self.last_position:
            self.keyboard = False
        self.last_position = position
        if (not dialog.isActiveWindow() or QApplication.activePopupWidget() is not None
                or QApplication.mouseButtons() != Qt.NoButton
                or self.keyboard):
            self.since = None
            return
        if self.navigation.rect().contains(self.navigation.mapFromGlobal(position)):
            self.since = None
            self.navigation.set_collapsed(False)
        elif self.content.rect().contains(self.content.mapFromGlobal(position)):
            now = monotonic()
            if self.since is None:
                self.since = now
            elif now-self.since >= self.DWELL_SECONDS:
                self.navigation.set_collapsed(True)
        else:
            self.since = None
