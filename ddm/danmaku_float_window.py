"""Movable tabbed presentation of existing chat panes."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCursor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QMenu, QSizeGrip,
                               QStackedLayout, QVBoxLayout, QWidget)

from . import theme
from .corner_geometry import continuous_path
from .danmaku_float_snap import snapped_position
from .danmaku_float_tabs import DanmakuFloatTabs
from .panel_resize import resize_edges, set_resize_cursor
from .pip_window import PictureInPictureButton
from .sidebar_navigation import NavigationButton
from .ui import ActionButton
from .window_fullscreen import set_window_topmost


class DanmakuFloatSlot(QFrame):
    def __init__(self, parent, restore):
        super().__init__(parent)
        self.setObjectName('DanmakuPanel')
        self.setAttribute(Qt.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        button = ActionButton('收回弹幕栏', self)
        button.clicked.connect(restore)
        layout.addWidget(button)
        self.hide()


class _MoveHandle(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.TEXT3))
        for x in (-2, 2):
            for y in (-4, 0, 4):
                painter.drawEllipse(QRectF(self.width()/2 + x - 1, self.height()/2 + y - 1, 2, 2))


class DanmakuFloatWindow(QWidget):
    returnRequested = Signal()

    def __init__(self, owner, controller, area):
        super().__init__(owner, Qt.Window | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.controller = controller
        self._move_origin = None
        self._snap_edges = Qt.Edge(0)
        self._move_watch = QTimer(self, interval=25)
        self._move_watch.timeout.connect(self._check_move_release)
        self.setWindowTitle('弹幕 · DD监控室CE')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('floatingDanmaku', True)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 120)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(7, 7, 7, 7)
        self.box.setSpacing(5)
        controls = QHBoxLayout()
        controls.setSpacing(3)
        self.move_handle = _MoveHandle(self)
        self.move_handle.setFixedWidth(14)
        self.move_handle.setCursor(Qt.SizeAllCursor)
        self.move_handle.setToolTip('拖动浮窗')
        self.move_handle.installEventFilter(self)
        self.tabs = DanmakuFloatTabs(self)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(lambda index: controller.return_floating(self.tabs.tabData(index)))
        self.pin = PictureInPictureButton('pin', '未置顶，点击置顶', self)
        self.pin.setCheckable(True)
        self.pin.toggled.connect(self._set_pinned)
        self.more = NavigationButton('浮窗选项', 'more', self)
        self.more.setFixedSize(24, 24)
        self.more.clicked.connect(self._open_menu)
        close = PictureInPictureButton('close', '关闭浮窗', self)
        close.clicked.connect(self.close)
        for widget in (self.move_handle, self.tabs, self.pin, self.more, close):
            controls.addWidget(widget)
        self.box.addLayout(controls)
        self.stack = QStackedLayout()
        self.box.addLayout(self.stack, 1)
        self.snap = QAction('拖动时吸附', self, checkable=True, checked=True)
        self.grip = QSizeGrip(self)
        self.grip.setToolTip('拖动调整大小')
        screen = QApplication.screenAt(area.center()) or owner.screen()
        available = screen.availableGeometry()
        size = area.size().expandedTo(self.minimumSize()).boundedTo(available.size())
        point = QPoint(max(available.left(), min(area.x(), available.right() - size.width() + 1)),
                       max(available.top(), min(area.y(), available.bottom() - size.height() + 1)))
        self.setGeometry(QRect(point, size))
        theme.signals().changed.connect(self.update)

    def attach_panel(self, panel, index=-1):
        scroll = panel.scroll_control.scroll_state()
        panel.header.installEventFilter(self)
        panel.title.installEventFilter(self)
        panel.header.setCursor(Qt.SizeAllCursor)
        self.stack.addWidget(panel)
        with QSignalBlocker(self.tabs):
            index = self.tabs.insertTab(index, '弹幕')
            self.tabs.setTabData(index, panel)
        self.select_panel(panel)
        panel.scroll_control.restore_scroll_state(scroll)
        self.grip.raise_()

    def release_panel(self, panel, parent):
        panels = self.tabs.panels()
        if panel not in panels:
            return
        index = panels.index(panel)
        self.tabs.cancel_drag()
        panel.source_picker.set_expanded(False, animate=False)
        panel.header.unsetCursor()
        panel.header.removeEventFilter(self)
        panel.title.removeEventFilter(self)
        panel.hide()
        self.stack.removeWidget(panel)
        panel.setParent(parent)
        with QSignalBlocker(self.tabs):
            self.tabs.removeTab(index)
        if self.tabs.count():
            self._tab_changed(self.tabs.currentIndex())
        else:
            self.hide()

    def select_panel(self, panel):
        index = self.tabs.panels().index(panel)
        if index == self.tabs.currentIndex():
            self._tab_changed(index)
        else:
            self.tabs.setCurrentIndex(index)

    def _tab_changed(self, index):
        if index < 0:
            return
        panel = self.tabs.tabData(index)
        previous = self.stack.currentWidget()
        if previous is not panel:
            if previous is not None and previous.source_picker.expanded:
                previous.source_picker.set_expanded(False, animate=False)
            scroll = panel.scroll_control.scroll_state()
            self.stack.setCurrentWidget(panel)
            panel.scroll_control.restore_scroll_state(scroll)
        panel.source_picker.refresh()
        self.tabs.refresh_source(panel)
        self.tabs.refresh_close_button()

    def _set_pinned(self, pinned):
        set_window_topmost(self, pinned)
        label = '已置顶，点击取消置顶' if pinned else '未置顶，点击置顶'
        self.pin.setToolTip(label)
        self.pin.setAccessibleName(label)

    def _open_menu(self):
        menu = QMenu(self)
        menu.addAction(self.snap)
        if self.tabs.count() > 1:
            current = self.tabs.currentIndex()
            panel = self.tabs.tabData(current)
            menu.addAction('拆出当前标签', lambda: self.controller.split_floating_tab(
                panel, self.frameGeometry().topLeft() + QPoint(28, 28)))
            menu.addSeparator()
            for index, panel in enumerate(self.tabs.panels()):
                action = menu.addAction(self.tabs.tabIcon(index), self.tabs.tabText(index),
                                        lambda p=panel: self.select_panel(p))
                action.setCheckable(True)
                action.setChecked(index == current)
        menu.exec(self.more.mapToGlobal(QPoint(0, self.more.height())))
        menu.deleteLater()

    def start_move(self):
        handle = self.windowHandle()
        if handle is None:
            return False
        self._move_origin = self.frameGeometry().topLeft()
        if not handle.startSystemMove():
            self._move_origin = None
            return False
        if QApplication.platformName() != 'windows':
            self._move_watch.start()
        return True

    def _check_move_release(self):
        if not QApplication.mouseButtons() & Qt.LeftButton:
            self._finish_move()

    def _snap_candidate(self):
        screen = QApplication.screenAt(QCursor.pos()) or self.screen()
        neighbors = [window.frameGeometry() for window in self.controller.floating_windows()
                     if window is not self and window.isVisible() and not window.isMinimized()]
        return snapped_position(self.frameGeometry(), screen.availableGeometry(), neighbors)

    def _finish_move(self):
        origin, self._move_origin = self._move_origin, None
        self._move_watch.stop()
        if origin is not None and self.isVisible() and self.snap.isChecked() and self.frameGeometry().topLeft() != origin:
            position, edges = self._snap_candidate()
            if edges:
                self.move(position)
        self._snap_edges = Qt.Edge(0)
        self.update()

    def nativeEvent(self, event_type, message):
        if event_type == b'windows_generic_MSG' and self._move_origin is not None:
            if wintypes.MSG.from_address(int(message)).message == 0x0232:  # WM_EXITSIZEMOVE
                QTimer.singleShot(0, self, self._finish_move)
        return super().nativeEvent(event_type, message)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._move_origin is not None and self.snap.isChecked():
            _, self._snap_edges = self._snap_candidate()
            self.update()

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and self.start_move()):
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.windowHandle() is not None:
            edges = resize_edges(self, event.position().toPoint())
            if edges and self.windowHandle().startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        set_resize_cursor(self, resize_edges(self, event.position().toPoint()))
        super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        self.grip.move(self.width() - self.grip.width(), self.height() - self.grip.height())
        super().resizeEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(theme.qcolor(theme.CONTENT))
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 14))
        if self._snap_edges:
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 2, Qt.SolidLine, Qt.RoundCap))
            right, bottom = self.width()-2, self.height()-2
            for edge, points in ((Qt.LeftEdge, (2, 14, 2, bottom-14)),
                                 (Qt.RightEdge, (right, 14, right, bottom-14)),
                                 (Qt.TopEdge, (14, 2, right-14, 2)),
                                 (Qt.BottomEdge, (14, bottom, right-14, bottom))):
                if self._snap_edges & edge:
                    painter.drawLine(*points)

    def closeEvent(self, event):
        self.returnRequested.emit()
        super().closeEvent(event)
