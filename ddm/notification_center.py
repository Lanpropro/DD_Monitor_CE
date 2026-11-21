"""本次启动的通知收件箱；仅存内存，不随账号配置落盘。"""
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QElapsedTimer, QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QPushButton,
                               QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget)

from .corner_geometry import continuous_path
from . import motion, theme
from .dock_feedback import icon_color
from .settings_material import normalize as normalize_material
from .settings_material_paint import glass_tint, paint_glass_border, window_background_tint
from .ui import NavigationButton


def _draw_bell(painter, color):
    painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    path = QPainterPath()
    path.moveTo(-6, 4)
    path.lineTo(-4.5, 1)
    path.lineTo(-4.5, -2)
    path.cubicTo(-4.5, -8, 4.5, -8, 4.5, -2)
    path.lineTo(4.5, 1)
    path.lineTo(6, 4)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawArc(QRectF(-2, 4, 4, 4), 180 * 16, 180 * 16)


class _NotificationBell(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(38, 38)

    def paintEvent(self, _event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillPath(continuous_path(QRectF(self.rect()), 11), theme.qcolor(theme.ACCENT_SOFT))
            painter.translate(self.width() / 2, self.height() / 2)
            painter.scale(1.23, 1.23)
            _draw_bell(painter, theme.qcolor(theme.ACCENT))


def live_notice_action(parent):
    wall = getattr(parent, 'wall', None)
    if wall is not None and not any(not tile.room.get('room_id') for tile in wall.visible_tiles()):
        return '替换'
    return '放入画面墙'


def reveal_file(path):
    path = Path(path)
    if sys.platform == 'win32' and path.is_file():
        try:
            subprocess.Popen(['explorer.exe', '/select,', str(path)])
            return
        except OSError:
            pass
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


@dataclass(eq=False)
class NoticeEntry:
    message: str
    kind: str
    time: str
    callback: object = None
    action: str = '查看详情'
    unread: bool = True
    rooms: tuple = ()
    key: object = None
    file_path: str = ''
    secondary_callback: object = None
    secondary_action: str = '查看详情'


class NoticeMessage(QTextEdit):
    """Selectable plain text that also wraps long paths without word breaks."""
    def __init__(self, text):
        super().__init__()
        self.setReadOnly(True)
        self.setPlainText(text)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet('background: transparent; border: none; padding: 0;')
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        # Keep width measurement outside the live text layout and owned by this widget.
        self._measurement_document = self.document().clone(self)
        policy = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def text(self):
        return self.toPlainText()

    def heightForWidth(self, width):
        document = self._measurement_document
        document.setDefaultFont(self.document().defaultFont())
        document.setTextWidth(max(1, width))
        return math.ceil(document.size().height())

    def sizeHint(self):
        return QSize(180, self.heightForWidth(180))

    def minimumSizeHint(self):
        return QSize(0, 0)


class NoticeRow(QFrame):
    removed = Signal(object)
    DISMISS_MS = 180
    TYPES = {'live': ('开播提醒', '●'), 'warning': ('需要留意', '!'),
             'error': ('操作失败', '!'), 'update': ('版本更新', '↑'),
             'announcement': ('官方公告', 'i')}

    def __init__(self, entry, parent):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName('HistoryNotice')
        self.setProperty('customControlSurface', True)
        self.setToolTip(entry.file_path)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.avatars = {}
        category, symbol = self.TYPES.get(entry.kind, ('操作提示', 'i'))
        from .room_artwork import RoomArtwork, add_platform_logos, style_room_notice
        if entry.rooms:
            from .images import load_cached_avatar, load_room_avatar
            from .avatar_widgets import Avatar
            identity = QWidget(self)
            identity_layout = QVBoxLayout(identity)
            identity_layout.setContentsMargins(0, 0, 0, 0)
            identity_layout.setSpacing(4)
            strip = QWidget(identity)
            strip.setFixedSize(28 + 12 * (len(entry.rooms) - 1), 28)
            for index, room in enumerate(entry.rooms[:3]):
                room_id = str(room.get('room_id', ''))
                avatar = Avatar(str(room.get('uname') or '?'), index, size=28, parent=strip)
                pixmap = load_cached_avatar(room.get('face')) if room.get('face') else None
                if pixmap is None:
                    pixmap = load_room_avatar(room_id)
                if pixmap is not None:
                    avatar.set_pixmap_image(pixmap)
                avatar.move(index * 12, 0)
                self.avatars[room_id] = avatar
            identity_layout.addWidget(strip, 0, Qt.AlignHCenter)
            platforms = QHBoxLayout()
            platforms.setAlignment(Qt.AlignHCenter)
            platforms.setSpacing(2)
            add_platform_logos(platforms, entry.rooms, identity)
            identity_layout.addLayout(platforms)
            header.addWidget(identity, 0, Qt.AlignTop)
        else:
            icon = QLabel(symbol)
            icon.setObjectName('HistoryNoticeGlyph')
            icon.setProperty('noticeKind', entry.kind)
            icon.setProperty('appearanceLight', theme.is_light())
            icon.setFixedSize(28, 28)
            icon.setAlignment(Qt.AlignCenter)
            header.addWidget(icon, 0, Qt.AlignTop)
        content = QVBoxLayout()
        content.setSpacing(6)
        self.category = QLabel(category)
        self.category.setObjectName('NoticeHeading')
        self.category.setWordWrap(True)
        category_row = QHBoxLayout()
        category_row.setSpacing(4)
        self.artwork = RoomArtwork(entry.rooms)
        theme.signals().changed.connect(self._refresh_artwork_theme)
        category_row.addWidget(self.category)
        category_row.addStretch()
        self.timestamp = QLabel(entry.time[:5])
        self.timestamp.setObjectName('NoticeDescription')
        self.timestamp.setToolTip(entry.time)
        self.timestamp.setAccessibleName(entry.time)
        category_row.addWidget(self.timestamp)
        content.addLayout(category_row)
        self.message = NoticeMessage(entry.message)
        self.message.setObjectName('NoticeText')
        self.message.setToolTip(entry.file_path)
        self.message.setMinimumWidth(0)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content.addWidget(self.message)
        header.addLayout(content, 1)
        self.remove_button = QPushButton('×')
        self.remove_button.setObjectName('NoticeClose')
        self.remove_button.setFixedSize(24, 24)
        self.remove_button.setToolTip('删除这条通知')
        self.remove_button.setAccessibleName('删除这条通知')
        self.remove_button.clicked.connect(self.remove)
        header.addWidget(self.remove_button, 0, Qt.AlignTop)
        layout.addLayout(header)
        if entry.callback is not None or entry.secondary_callback is not None:
            footer = QHBoxLayout()
            footer.addStretch()
            if entry.callback is not None:
                self.action = QPushButton(entry.action)
                self.action.setObjectName('PrimaryButton')
                self.action.clicked.connect(self.activate)
                footer.addWidget(self.action)
            if entry.secondary_callback is not None:
                self.secondary_action = QPushButton(entry.secondary_action)
                self.secondary_action.setObjectName('IconButton')
                self.secondary_action.clicked.connect(self.activate_secondary)
                footer.addWidget(self.secondary_action)
            layout.addLayout(footer)
        self._paper = None
        self._progress = 0.0
        self._collapse_height = 0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(self.DISMISS_MS)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self.finish_removal)
        self._removed = False
        self._close_clock = QElapsedTimer()
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(16)
        self._close_timer.timeout.connect(self._advance_close)
        self.ensurePolished()
        style_room_notice(self, self.artwork)
        self.setMinimumHeight(layout.totalHeightForWidth(max(80, parent.width())))

    def activate(self):
        self.window().hide()
        self.entry.callback()

    def activate_secondary(self):
        self.window().hide()
        self.entry.secondary_callback()

    def set_room_artwork(self, room_id, pixmap, kind):
        from .room_artwork import style_room_notice
        if self.artwork.set_image(room_id, pixmap, kind):
            style_room_notice(self, self.artwork)

    def _refresh_artwork_theme(self, _mode):
        from .room_artwork import style_room_notice
        style_room_notice(self, self.artwork)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._paper is None:
            self.setMinimumHeight(self.layout().totalHeightForWidth(self.width()))
            self.layout().activate()

    def remove(self, *, collapse=True):
        if self._removed or self._paper is not None:
            return
        if not self.isVisible() or self.visibleRegion().isEmpty() or not motion.enabled():
            self.finish_removal()
            return
        self._paper = self.grab()
        height = self.height()
        self._collapse_height = height if collapse else 0
        self.setFixedHeight(height)
        for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            child.hide()
        self.animation.start()
        # The shared Qt animation clock can stall while Qt Quick video is active.
        self.animation.pause()
        self._close_clock.start()
        self._close_timer.start()

    def _advance_close(self):
        elapsed = self._close_clock.elapsed()
        self.animation.setCurrentTime(min(elapsed, self.DISMISS_MS))
        if elapsed >= self.DISMISS_MS and not self._removed:
            self.finish_removal()

    def _frame(self, progress):
        self._progress = progress
        if self._collapse_height:
            self.setFixedHeight(round(self._collapse_height * (1.0 - progress)))
        self.update()

    def finish_removal(self):
        if self._removed:
            return
        self._removed = True
        self._close_timer.stop()
        self.animation.stop()
        self.removed.emit(self.entry)

    def paintEvent(self, event):
        if self._paper is None:
            from .room_artwork import paint_room_background, notice_frost, notice_source
            source = notice_source(self, self.artwork)
            with QPainter(self) as painter:
                painter.setRenderHint(QPainter.Antialiasing)
                rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
                path = continuous_path(rect, theme.RADIUS_LG)
                glass = self.window().property('settings_glass_enabled')
                if glass:
                    painter.fillPath(path, glass_tint(self, card=True))
                else:
                    painter.setBrush(theme.qcolor(theme.ELEVATED))
                    painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
                    painter.drawPath(path)
                if source is not None:
                    paint_room_background(painter, self.rect(), source, theme.RADIUS_LG,
                                          focus=self.artwork.banner is None, frost=notice_frost(self, self.artwork))
                if glass:
                    paint_glass_border(painter, path)
            return
        with QPainter(self) as painter:
            painter.setOpacity(1.0 - self._progress)
            painter.drawPixmap(0, 0, self._paper)


class NotificationCenter(QFrame):
    changed = Signal()
    RADIUS = 16
    MIN_GLASS_OPACITY = 75
    CLEAR_FEEDBACK_MS = 800

    def __init__(self, button):
        super().__init__(button, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName('NotificationCenter')
        self.setAccessibleName('通知')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.button = button
        self.entries = []
        self._seen_keys = set()
        self.rows = {}
        self._owner = None
        self._clear_pending = set()
        self._clear_count = 0
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self.hide)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.heading = QFrame()
        self.heading.setObjectName('NotificationHeader')
        heading = QHBoxLayout(self.heading)
        heading.setContentsMargins(10, 8, 8, 8)
        heading.setSpacing(8)
        heading.addWidget(_NotificationBell())
        labels = QVBoxLayout()
        labels.setSpacing(1)
        title = self.title = QLabel('通知')
        title.setObjectName('NotificationTitle')
        labels.addWidget(title)
        self.summary = QLabel()
        self.summary.setObjectName('NotificationSummary')
        self.summary.setWordWrap(True)
        labels.addWidget(self.summary)
        heading.addLayout(labels, 1)
        self.clear_button = NavigationButton('清空通知', 'clear', self.heading)
        self.clear_button.clicked.connect(self._clear_from_button)
        heading.addWidget(self.clear_button)
        self.close_button = NavigationButton('收起通知面板', 'close', self.heading)
        self.close_button.clicked.connect(self.hide)
        heading.addWidget(self.close_button)
        layout.addWidget(self.heading)
        self.empty = QLabel('暂无通知')
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName('NotificationEmpty')
        self.empty.setWordWrap(True)
        self.empty.setMinimumHeight(78)
        layout.addWidget(self.empty, 1)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('NotificationScroll')
        self.scroll.viewport().setObjectName('NotificationViewport')
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('NotificationList')
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        self._sync()

    def add(self, message, *, kind='info', callback=None, action='查看详情', key=None, rooms=(), replace=False,
            file_path=None, secondary_callback=None, secondary_action='查看详情'):
        unread = not self.isVisible() or bool(self._clear_count)
        if key is not None:
            if key in self._seen_keys:
                entry = next((entry for entry in reversed(self.entries) if entry.key == key), None)
                if not replace:
                    return entry
                row = self.rows.get(entry)
                if (entry is not None and entry not in self._clear_pending
                        and (row is None or row._paper is None)):
                    entry.message, entry.kind = str(message), kind
                    entry.callback, entry.action = callback, action
                    entry.secondary_callback, entry.secondary_action = secondary_callback, secondary_action
                    entry.time = datetime.now().strftime('%H:%M:%S')
                    entry.unread = unread
                    entry.rooms = tuple(dict(room) for room in rooms[:3])
                    entry.file_path = str(file_path or '')
                    row = self.rows.pop(entry, None)
                    if row is not None:
                        self.list_layout.removeWidget(row)
                        row.hide()
                        row.deleteLater()
                    if self.isVisible():
                        self._add_row(entry)
                    self._sync()
                    return entry
        entry = NoticeEntry(str(message), kind, datetime.now().strftime('%H:%M:%S'),
                            callback, action, unread, tuple(dict(room) for room in rooms[:3]), key,
                            str(file_path or ''), secondary_callback, secondary_action)
        self.entries.append(entry)
        if key is not None:
            self._seen_keys.add(key)
        if self.isVisible():
            self._add_row(entry)
            self.scroll.verticalScrollBar().setValue(0)
        self._sync()
        return entry

    def _add_row(self, entry):
        row = NoticeRow(entry, self.scroll.widget())
        row.removed.connect(self._remove)
        self.rows[entry] = row
        self.list_layout.insertWidget(0, row)

    def _remove(self, entry):
        if entry not in self.entries:
            return
        self.entries.remove(entry)
        row = self.rows.pop(entry, None)
        if row is not None:
            self.list_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        if entry in self._clear_pending:
            self._clear_pending.remove(entry)
            if self._clear_pending:
                return
            self._clear_timer.start(self.CLEAR_FEEDBACK_MS)
        self._sync(resize=False)

    def _clear_from_button(self):
        if not self.isVisible() or self._clear_count or not self.entries:
            return
        self._clear_pending.update(self.entries)
        self._clear_count = len(self._clear_pending)
        self.clear_button.setEnabled(False)
        self.clear()

    def clear(self):
        for entry in tuple(self.entries):
            row = self.rows.get(entry)
            if row is not None:
                row.remove(collapse=False)
            else:
                self._remove(entry)

    def _sync(self, *, resize=True):
        count = len(self.entries)
        feedback = f'已清空 {self._clear_count} 条通知' if self._clear_timer.isActive() else ''
        summary = f'本次启动 · {count} 条'
        self.summary.setText(f'{summary} · {feedback}' if count and feedback else summary)
        self.empty.setText(feedback or '暂无通知')
        self.empty.setVisible(not count)
        self.scroll.setVisible(bool(count))
        self.clear_button.setEnabled(bool(count) and not self._clear_count)
        if self.isVisible():
            self.layout().activate()
            if resize and not self._clear_count:
                self.reposition()
        self.changed.emit()

    def showEvent(self, event):
        self._owner = self.button.window()
        for entry in self.entries:
            entry.unread = False
            if entry not in self.rows:
                self._add_row(entry)
        QApplication.instance().installEventFilter(self)
        self._sync()
        super().showEvent(event)
        values = normalize_material(getattr(self._owner, 'settings', {}))
        self.setProperty('settings_glass_enabled', values['settings_glass_enabled'])
        # Keep the full slider range useful while limiting the unblurred video behind the popup.
        opacity = self.MIN_GLASS_OPACITY + (100 - self.MIN_GLASS_OPACITY) * values['settings_glass_opacity'] / 100
        self.setProperty('settings_glass_opacity', round(opacity))
        self.update()

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.button.setChecked(False)
        self._clear_timer.stop()
        self._clear_pending.clear()
        self._clear_count = 0
        for row in tuple(self.rows.values()):
            if row._paper is not None:
                row.finish_removal()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if watched in (self.button, self._owner):
            if event.type() in (QEvent.Hide, QEvent.Close, QEvent.WindowStateChange, QEvent.ParentChange):
                self.hide()
            elif event.type() in (QEvent.Move, QEvent.Resize):
                self.reposition()
        return False

    def reposition(self):
        owner = self.button.window()
        bounds = owner.screen().availableGeometry()
        width = max(180, min(420, owner.width() - 24, bounds.width() - 24))
        anchor = self.button.mapToGlobal(QPoint(self.button.width(), self.button.height() + 8))
        left = max(bounds.left() + 12, owner.mapToGlobal(QPoint(12, 0)).x())
        right = min(bounds.right() - 12, owner.mapToGlobal(QPoint(owner.width() - 12, 0)).x())
        dock = bool(self.button.property('dockRail'))
        top = self.button.mapToGlobal(QPoint(self.button.width(), 0))
        above = top.y() - bounds.top() - 20
        below = bounds.bottom() - anchor.y() - 12
        upwards = dock and (above >= 120 or above > below)
        x = max(left, min(top.x()+8 if dock else anchor.x()-width, right-width))
        height = min(self._preferred_height(), max(120, above if upwards else below))
        self.resize(width, height)
        y = top.y()-height-8 if upwards else anchor.y()
        self.move(x, max(bounds.top()+12, min(y, bounds.bottom()-height-12)))

    def _preferred_height(self):
        layout = self.layout()
        margins = layout.contentsMargins()
        height = margins.top() + margins.bottom() + self.heading.sizeHint().height() + layout.spacing()
        if not self.entries:
            return height + self.empty.minimumHeight()
        row_height = 54 + 2 * self.title.fontMetrics().lineSpacing()
        return min(480, height + len(self.entries) * row_height)

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.Antialiasing)
            path = continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.RADIUS)
            if self.property('settings_glass_enabled'):
                # The native blur can extend beyond this popup's rounded mask.
                painter.fillPath(path, glass_tint(self, window_background_tint(self)))
                painter.fillPath(path, glass_tint(self, card=True))
                paint_glass_border(painter, path)
            else:
                painter.setBrush(theme.qcolor(theme.BG))
                painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
                painter.drawPath(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addPath(continuous_path(QRectF(self.rect()), self.RADIUS))
        from PySide6.QtGui import QRegion
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)


class NotificationButton(QPushButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('BarIcon')
        self.setProperty('sidebarCompact', True)
        self.setCheckable(True)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.center = NotificationCenter(self)
        self.center.changed.connect(self._sync)
        self.clicked.connect(self._toggle)
        self._sync()

    def _toggle(self):
        self.center.setVisible(self.isChecked())

    def _sync(self):
        unread = sum(entry.unread for entry in self.center.entries)
        self._unread = unread
        text = f'通知（{unread} 条未读）' if unread else '通知（本次启动）'
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        if hasattr(self, '_dock_feedback'):
            self._dock_feedback.transform(painter)
        color = icon_color(self) if self.property('dockRail') else theme.qcolor(theme.TEXT2)
        _draw_bell(painter, color)
        if self._unread:
            painter.setPen(QPen(theme.qcolor(theme.ELEVATED), 1))
            painter.setBrush(theme.qcolor(theme.PINK))
            painter.drawEllipse(QPointF(6, -6), 3, 3)


def remember_result(parent, message, *, kind='info', on_click=None, file_path=None, rooms=(),
                    notice_key=None, pending=False):
    sidebar = getattr(parent, 'sidebar', None)
    while sidebar is None and parent.parentWidget() is not None:
        parent = parent.parentWidget()
        sidebar = getattr(parent, 'sidebar', None)
    if getattr(parent, '_closing', False):
        return
    if sidebar is None or not hasattr(sidebar, 'notification_button'):
        return
    if file_path:
        callback = None if pending else lambda path=str(file_path): reveal_file(path)
        action = '打开文件位置'
        message = message + Path(str(file_path).replace('\\', '/')).name
    else:
        callback = on_click
        action = live_notice_action(parent) if kind == 'live' else (
            '前往登录' if kind != 'announcement' and '登录' in message else '查看详情')
    center = sidebar.notification_button.center
    entry = center.add(message, kind=kind, callback=callback, action=action, rooms=rooms,
                       key=notice_key, replace=notice_key is not None, file_path=file_path)
    return center, entry
