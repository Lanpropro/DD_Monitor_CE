"""本次启动的通知收件箱；仅存内存，不随账号配置落盘。"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QUrl, QVariantAnimation, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from . import motion, theme


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


class NoticeRow(QFrame):
    removed = Signal(object)

    def __init__(self, entry, parent):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName('HistoryNotice')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        header = QHBoxLayout()
        category = {'live': '开播提醒', 'warning': '需要留意', 'update': '更新提醒'}.get(entry.kind, '操作提示')
        label = QLabel(category + ' · ' + entry.time)
        label.setObjectName('NoticeDescription')
        header.addWidget(label, 1)
        self.remove_button = QPushButton('×')
        self.remove_button.setObjectName('NoticeClose')
        self.remove_button.setFixedSize(24, 24)
        self.remove_button.setToolTip('删除这条通知')
        self.remove_button.clicked.connect(self.remove)
        header.addWidget(self.remove_button)
        layout.addLayout(header)
        self.message = QLabel(entry.message)
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        self.message.setMinimumWidth(0)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message)
        if entry.callback is not None:
            self.action = QPushButton(entry.action)
            self.action.setObjectName('IconButton')
            self.action.clicked.connect(self.activate)
            layout.addWidget(self.action, 0, Qt.AlignRight)
        self._paper = None
        self._progress = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(240)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self.finish_removal)

    def activate(self):
        self.window().hide()
        self.entry.callback()

    def remove(self):
        if self._paper is not None:
            return
        if not self.isVisible() or self.visibleRegion().isEmpty() or not motion.enabled():
            self.removed.emit(self.entry)
            return
        self._paper = self.grab()
        self.setFixedHeight(self.height())
        for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            child.hide()
        self.animation.start()

    def _frame(self, progress):
        self._progress = progress
        self.update()

    def finish_removal(self):
        self.animation.stop()
        self.removed.emit(self.entry)

    def paintEvent(self, event):
        if self._paper is None:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        progress = self._progress
        painter.setOpacity(min(1.0, (1.0 - progress) * 3))
        width, height = self.width(), self.height()
        # Horizontal strips bend and narrow toward the bottom-right paper slot.
        for index in range(12):
            top, bottom = height * index / 12, height * (index + 1) / 12
            points = []
            for x, y in ((0, top), (width, top), (width, bottom), (0, bottom)):
                bend = progress * (0.5 + 0.5 * y / height)
                points.append(QPointF(x + (width - 12 - x) * bend,
                                      y + (height - 4 - y) * progress))
            source = QPolygonF([QPointF(0, top), QPointF(width, top),
                                QPointF(width, bottom), QPointF(0, bottom)])
            transform = QTransform()
            if QTransform.quadToQuad(source, QPolygonF(points), transform):
                painter.setTransform(transform)
                scale = self._paper.devicePixelRatio()
                painter.drawPixmap(QRectF(0, top, width, bottom - top), self._paper,
                                   QRectF(0, top * scale, width * scale, (bottom - top) * scale))


class NotificationCenter(QFrame):
    changed = Signal()

    def __init__(self, button):
        super().__init__(button, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName('NotificationCenter')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.button = button
        self.entries = []
        self._seen_keys = set()
        self.rows = {}
        self._owner = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        heading = QHBoxLayout()
        title = QLabel('通知 · 本次启动')
        title.setObjectName('PluginName')
        heading.addWidget(title, 1)
        self.clear_button = QPushButton('清空')
        self.clear_button.setObjectName('IconButton')
        self.clear_button.clicked.connect(self.clear)
        heading.addWidget(self.clear_button)
        close = QPushButton('×')
        close.setObjectName('NoticeClose')
        close.setFixedSize(24, 24)
        close.setToolTip('收起通知面板')
        close.clicked.connect(self.hide)
        heading.addWidget(close)
        layout.addLayout(heading)
        self.empty = QLabel('本次启动还没有通知')
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName('NoticeDescription')
        layout.addWidget(self.empty)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('NotificationList')
        self.list_layout = QVBoxLayout(content)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        self.scroll.setWidget(content)
        layout.addWidget(self.scroll, 1)
        self._sync()

    def add(self, message, *, kind='info', callback=None, action='查看详情', key=None):
        if key is not None:
            if key in self._seen_keys:
                return
            self._seen_keys.add(key)
        entry = NoticeEntry(str(message), kind, datetime.now().strftime('%H:%M:%S'),
                            callback, action, not self.isVisible())
        self.entries.append(entry)
        if self.isVisible():
            self._add_row(entry)
            self.scroll.verticalScrollBar().setValue(0)
        self._sync()

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
        self._sync()

    def clear(self):
        for entry in tuple(self.entries):
            row = self.rows.get(entry)
            if row is not None:
                row.remove()
            else:
                self._remove(entry)

    def _sync(self):
        self.empty.setVisible(not self.entries)
        self.scroll.setVisible(bool(self.entries))
        self.clear_button.setEnabled(bool(self.entries))
        self.changed.emit()

    def showEvent(self, event):
        for entry in self.entries:
            entry.unread = False
            if entry not in self.rows:
                self._add_row(entry)
        self._owner = self.button.window()
        QApplication.instance().installEventFilter(self)
        self.reposition()
        self._sync()
        super().showEvent(event)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.button.setChecked(False)
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
        width = min(420, owner.width() - 24, bounds.width() - 24)
        anchor = self.button.mapToGlobal(QPoint(self.button.width(), self.button.height() + 8))
        left = max(bounds.left() + 12, owner.mapToGlobal(QPoint(12, 0)).x())
        right = min(bounds.right() - 12, owner.mapToGlobal(QPoint(owner.width() - 12, 0)).x())
        x = max(left, min(anchor.x() - width, right - width))
        height = min(480, max(120, bounds.bottom() - anchor.y() - 12))
        self.resize(max(180, width), height)
        self.move(x, min(anchor.y(), bounds.bottom() - height - 12))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(theme.qcolor(theme.ELEVATED))
        painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 12, 12)

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
        painter.setPen(QPen(theme.qcolor(theme.TEXT2), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
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
        if self._unread:
            painter.setPen(QPen(theme.qcolor(theme.ELEVATED), 1))
            painter.setBrush(theme.qcolor(theme.PINK))
            painter.drawEllipse(QPointF(6, -6), 3, 3)


def remember_result(parent, message, *, kind='info', on_click=None, file_path=None):
    sidebar = getattr(parent, 'sidebar', None)
    while sidebar is None and parent.parentWidget() is not None:
        parent = parent.parentWidget()
        sidebar = getattr(parent, 'sidebar', None)
    if getattr(parent, '_closing', False):
        return
    if sidebar is None or not hasattr(sidebar, 'notification_button'):
        return
    if file_path:
        callback = lambda path=str(file_path): reveal_file(path)
        action = '打开文件位置'
        message = message + str(file_path)
    else:
        callback = on_click
        action = '放入画面墙' if kind == 'live' else ('前往登录' if '登录' in message else '查看详情')
    sidebar.notification_button.center.add(message, kind=kind, callback=callback, action=action)
