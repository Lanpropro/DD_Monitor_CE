"""Movable tabbed presentation of existing chat panes."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLineEdit, QMenu, QPlainTextEdit,
                               QSizeGrip, QStackedLayout, QTextEdit, QVBoxLayout, QWidget)
from shiboken6 import isValid

from . import config, theme
from .corner_geometry import continuous_path
from .danmaku_float_snap import snapped_position, touching_windows
from .danmaku_float_tabs import DanmakuFloatTabs
from .panel_resize import resize_edges, set_resize_cursor
from .settings_backdrop import apply_blur, apply_frame
from .shortcut_actions import DEFAULT_SHORTCUTS
from .sidebar_navigation import NavigationButton
from .ui import ActionButton
from .widget_support import _repolish
from .window_fullscreen import raise_below_native_windows, set_presentation_owner, set_window_topmost


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


class _ResizeGrip(QSizeGrip):
    def paintEvent(self, event):
        # Keep the platform resize gesture without its square corner decoration.
        pass


class _MoveHandle(QWidget):
    def event(self, event):
        if event.type() in (QEvent.Enter, QEvent.Leave):
            self.update()
        return super().event(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        if self.underMouse():
            painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0, 2, 0, -2), 5, 5)
        painter.setBrush(theme.qcolor(theme.ACCENT if self.underMouse() else theme.TEXT3))
        for x in (-2, 2):
            for y in (-4, 0, 4):
                painter.drawEllipse(QRectF(self.width()/2 + x - 1, self.height()/2 + y - 1, 2, 2))


class DanmakuFloatWindow(QWidget):
    returnRequested = Signal()
    CORNER_RADIUS = 14
    TEXT_MASK_ALPHA = 76

    def __init__(self, owner, controller, area):
        super().__init__(owner, Qt.Window | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.controller = controller
        self._fullscreen_owner = None
        self._hidden_with_owner = False
        self._move_origin = None
        self._move_followers = {}
        self._group_press = None
        self._drag_snapping = False
        self._snap_edges = Qt.Edge(0)
        self._move_watch = QTimer(self, interval=25)
        self._move_watch.timeout.connect(self._check_move_release)
        self._move_frame = QTimer(self, interval=16, singleShot=True, timerType=Qt.PreciseTimer)
        self._move_frame.timeout.connect(self._flush_move)
        self._native_glass = False
        self._native_corners = False
        self._glass_opacity = 100
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
        self.move_handle.setFixedWidth(18)
        self.move_handle.setCursor(Qt.SizeAllCursor)
        self.move_handle.setAccessibleName('单独拖动浮窗')
        self.move_handle.setToolTip('按住单独拖动 · 此次绕过吸附')
        self.move_handle.installEventFilter(self)
        self.tabs = DanmakuFloatTabs(self)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(lambda index: controller.return_floating(self.tabs.tabData(index)))
        self.dock = NavigationButton('拖入画面墙 · 放入空格或替换直播画面', 'import', self)
        self.dock.setFixedSize(24, 24)
        self.dock.setCursor(Qt.OpenHandCursor)
        self.dock.installEventFilter(self.tabs)
        self.pin = NavigationButton('未置顶，点击置顶', 'pin', self)
        self.pin.setFixedSize(24, 24)
        self.pin.setProperty('accentWhenChecked', True)
        self.pin.setCheckable(True)
        self.pin.toggled.connect(self._set_pinned)
        self.more = NavigationButton('浮窗选项', 'more', self)
        self.more.setFixedSize(24, 24)
        self.more.clicked.connect(self._open_menu)
        close = NavigationButton('关闭浮窗', 'close', self)
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        for widget in (self.move_handle, self.tabs, self.dock, self.pin, self.more, close):
            controls.addWidget(widget)
        self.box.addLayout(controls)
        self.stack = QStackedLayout()
        self.box.addLayout(self.stack, 1)
        self.more.hide()
        self._close_shortcut = QShortcut(self)
        self._close_shortcut.setContext(Qt.WindowShortcut)
        self._close_shortcut.setAutoRepeat(False)
        self._close_shortcut.activated.connect(self._activate_close_shortcut)
        self._playback_shortcuts = []
        shortcut_control = getattr(owner, 'shortcut_control', None)
        if shortcut_control is None:
            self.configure_shortcuts(getattr(owner, 'shortcuts', {}).get('close_tile', DEFAULT_SHORTCUTS['close_tile']))
        else:
            shortcut_control.refresh_floating_shortcuts(self)
        self.grip = _ResizeGrip(self)
        self.grip.setToolTip('拖动调整大小')
        screen = QApplication.screenAt(area.center()) or owner.screen()
        available = screen.availableGeometry()
        size = area.size().expandedTo(self.minimumSize()).boundedTo(available.size())
        point = QPoint(max(available.left(), min(area.x(), available.right() - size.width() + 1)),
                       max(available.top(), min(area.y(), available.bottom() - size.height() + 1)))
        self.setGeometry(QRect(point, size))
        self.set_material(getattr(owner, 'settings', {}))
        owner.installEventFilter(self)
        theme.signals().changed.connect(self.update)

    def configure_shortcuts(self, close_sequence, playback_sequences=(), forward=None):
        self._close_sequence = close_sequence
        self._forward_shortcut = forward
        close_key = QKeySequence(close_sequence)
        self._close_shortcut.setKey(close_key)
        for shortcut in self._playback_shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._playback_shortcuts.clear()
        for sequence in dict.fromkeys(playback_sequences):
            key = QKeySequence(sequence)
            if key.isEmpty() or key == close_key:
                continue
            shortcut = QShortcut(key, self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.setEnabled(False)
            shortcut.activated.connect(lambda seq=sequence: forward(seq))
            self._playback_shortcuts.append(shortcut)

    def enable_playback_shortcuts(self, enabled):
        for shortcut in self._playback_shortcuts:
            shortcut.setEnabled(enabled)

    def _activate_close_shortcut(self):
        if self._forward_shortcut is None or not self._forward_shortcut(self._close_sequence):
            self.close_selected_tab()

    def close_selected_tab(self):
        focused = QApplication.focusWidget()
        if isinstance(focused, (QLineEdit, QPlainTextEdit, QTextEdit)) and not focused.isReadOnly():
            return False
        panel = self.stack.currentWidget()
        if panel is None:
            return False
        self.controller.return_floating(panel)
        return True

    def set_material(self, settings):
        enabled, opacity = config.danmaku_float_material(settings)
        if enabled != self.property('danmakuFloatGlass'):
            self.setProperty('danmakuFloatGlass', enabled)
            for panel in self.tabs.panels():
                self._refresh_panel_glass(panel, enabled)
            if self.isVisible():
                self._sync_glass()
        self._glass_opacity = opacity
        self.update()

    @staticmethod
    def _refresh_panel_glass(panel, enabled):
        # The floating window owns the background, including under themed panels.
        panel.setProperty('customControlSurface', bool(enabled))
        _repolish(panel)
        panel.body.viewport().setAutoFillBackground(not enabled)
        panel.update()

    def _sync_glass(self):
        self._native_corners = apply_frame(self, theme.is_light())
        # An accent blur on an unframed layered HWND bleeds past the Qt alpha.
        enabled = self._native_corners and self.property('danmakuFloatGlass')
        self._native_glass = apply_blur(self, enabled) if enabled or self._native_glass else False

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_glass()

    def attach_panel(self, panel, index=-1):
        scroll = panel.scroll_control.scroll_state()
        panel.header.installEventFilter(self)
        panel.title.installEventFilter(self)
        panel.header.setCursor(Qt.SizeAllCursor)
        self.stack.addWidget(panel)
        self._refresh_panel_glass(panel, self.property('danmakuFloatGlass'))
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
        self._refresh_panel_glass(panel, False)
        with QSignalBlocker(self.tabs):
            self.tabs.removeTab(index)
        if self.tabs.count():
            self._tab_changed(self.tabs.currentIndex())
        else:
            self.hide()
        self.more.setVisible(self.tabs.count() > 1)

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
        self.more.setVisible(self.tabs.count() > 1)
        self.update()

    def set_fullscreen_owner(self, owner):
        if owner is self._fullscreen_owner:
            return
        if owner is not None and self._fullscreen_owner is None:
            self._windowed_show_without_activating = self.testAttribute(Qt.WA_ShowWithoutActivating)
        self._fullscreen_owner = owner
        self._sync_presentation_owner()

    def _sync_presentation_owner(self):
        fullscreen = self._fullscreen_owner
        wall_owner = self.parentWidget()
        pinned = self.pin.isChecked()
        behind_fullscreen = fullscreen is not None and not pinned
        owner = fullscreen if fullscreen is not None and pinned else wall_owner
        if fullscreen is wall_owner and not pinned:
            # Windows keeps an owned window above its owner, even without pinning.
            owner = None
        self.setProperty('behindFullscreen', behind_fullscreen)
        self.setAttribute(Qt.WA_ShowWithoutActivating, behind_fullscreen or self._windowed_show_without_activating)
        set_presentation_owner(self, owner)

    def _stack_behind_fullscreen(self):
        owner = self._fullscreen_owner
        if (owner is None or self.pin.isChecked() or not self.isVisible()
                or not owner.isVisible() or owner.isMinimized()):
            return False
        if QApplication.platformName() != 'windows' or not raise_below_native_windows(self, [int(owner.winId())]):
            self.lower()
        return True

    def raise_(self):
        if not self._stack_behind_fullscreen():
            super().raise_()

    def activateWindow(self):
        fullscreen = self._fullscreen_owner
        if fullscreen is not None and not self.pin.isChecked() and fullscreen.isVisible():
            return
        super().activateWindow()

    def _set_pinned(self, pinned):
        set_window_topmost(self, pinned)
        if self._fullscreen_owner is not None:
            self._sync_presentation_owner()
        label = '已置顶，点击取消置顶' if pinned else '未置顶，点击置顶'
        self.pin.setToolTip(label)
        self.pin.setAccessibleName(label)

    def _open_menu(self):
        menu = QMenu(self)
        if self.tabs.count() > 1:
            current = self.tabs.currentIndex()
            panel = self.tabs.tabData(current)
            menu.addAction('关闭当前标签', lambda: self.controller.return_floating(panel))
            menu.addAction('拆出当前标签', lambda: self.controller.split_floating_tab(
                panel, self.frameGeometry().topLeft() + QPoint(28, 28)))
            menu.addSeparator()
            for index, panel in enumerate(self.tabs.panels()):
                action = menu.addAction(self.tabs.tabIcon(index), self.tabs.tabToolTip(index).replace('&', '&&'),
                                        lambda p=panel: self.select_panel(p))
                action.setCheckable(True)
                action.setChecked(index == current)
        menu.exec(self.more.mapToGlobal(QPoint(0, self.more.height())))
        menu.deleteLater()

    def start_move(self, point, *, independent=False):
        handle = self.windowHandle()
        if handle is None:
            return False
        self._move_origin = self.frameGeometry().topLeft()
        self._drag_snapping = not independent
        if self._drag_snapping:
            frames = {window: window.frameGeometry() for window in self._magnetic_windows()}
            frames[self] = self.frameGeometry()
            self._move_followers = touching_windows(self, frames)
        if self._move_followers:
            self._group_press = point
            self.grabMouse(Qt.SizeAllCursor)
            return True
        if not handle.startSystemMove():
            self._move_origin = None
            self._drag_snapping = False
            self._move_followers.clear()
            return False
        if QApplication.platformName() != 'windows':
            self._move_watch.start()
        return True

    def _check_move_release(self):
        if not QApplication.mouseButtons() & Qt.LeftButton:
            self._finish_move()

    def _magnetic_windows(self):
        return [window for window in self.controller.floating_windows()
                if window is not self and window.isVisible() and not window.isMinimized()]

    def _snap_candidate(self):
        screen = QApplication.screenAt(QCursor.pos()) or self.screen()
        neighbors, companions = [], []
        for window in self._magnetic_windows():
            (companions if window in self._move_followers else neighbors).append(window.frameGeometry())
        return snapped_position(self.frameGeometry(), screen.availableGeometry(), neighbors, companions=companions)

    def _move_attached(self, delta):
        for window, origin in self._move_followers.items():
            position = origin + delta
            if isValid(window) and window.isVisible() and window.pos() != position:
                window.move(position)

    def _flush_move(self):
        if self._move_origin is None or not self._drag_snapping:
            return
        _, edges = self._snap_candidate()
        if edges != self._snap_edges:
            self._snap_edges = edges
            self.update()

    def _finish_move(self):
        origin, self._move_origin = self._move_origin, None
        if self._group_press is not None:
            self._group_press = None
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
        self._move_watch.stop()
        self._move_frame.stop()
        if origin is not None and self._drag_snapping:
            position = self.frameGeometry().topLeft()
            if self.isVisible() and position != origin:
                snapped, edges = self._snap_candidate()
                if edges and snapped != position:
                    self.move(snapped)
                    self._move_attached(self.frameGeometry().topLeft() - origin)
        self._drag_snapping = False
        self._move_followers.clear()
        if self._snap_edges:
            self._snap_edges = Qt.Edge(0)
            self.update()

    def nativeEvent(self, event_type, message):
        if event_type == b'windows_generic_MSG' and self._move_origin is not None:
            if wintypes.MSG.from_address(int(message)).message == 0x0232:  # WM_EXITSIZEMOVE
                QTimer.singleShot(0, self, self._finish_move)
        return super().nativeEvent(event_type, message)

    def moveEvent(self, event):
        super().moveEvent(event)
        if (self._move_origin is not None and self._drag_snapping
                and self._group_press is None and not self._move_frame.isActive()):
            self._move_frame.start()

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.parentWidget() and kind in (QEvent.Hide, QEvent.Show, QEvent.WindowStateChange):
            # An unowned float behind the main fullscreen window does not inherit minimization.
            visible = kind != QEvent.Hide and watched.isVisible() and not watched.isMinimized()
            if visible and self._hidden_with_owner:
                self._hidden_with_owner = False
                self.show()
            elif (not visible and self._fullscreen_owner is watched
                  and not self.pin.isChecked() and self.isVisible()):
                self._hidden_with_owner = True
                self.hide()
        if (watched is not self.parentWidget()
                and kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
                and self.start_move(event.globalPosition().toPoint(), independent=watched is self.move_handle)):
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
        if self._group_press is not None:
            self._move_group(event.globalPosition().toPoint() - self._group_press)
            event.accept()
            return
        set_resize_cursor(self, resize_edges(self, event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._group_press is not None and event.button() == Qt.LeftButton:
            self._move_group(event.globalPosition().toPoint() - self._group_press)
            self._finish_move()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _move_group(self, delta):
        # The lead and its followers use the same pointer sample, without a native
        # move loop advancing the lead while a Qt timer waits to move the rest.
        position = self._move_origin + delta
        if self.pos() != position:
            self.move(position)
        self._move_attached(delta)
        self._flush_move()

    def event(self, event):
        kind = event.type()
        if kind in (QEvent.Hide, QEvent.WindowDeactivate) and hasattr(self, 'tabs'):
            self.tabs.cancel_drag()
        if getattr(self, '_group_press', None) is not None:
            if (kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and event.key() == Qt.Key_Escape):
                if kind == QEvent.KeyPress:
                    self._move_group(QPoint())
                    self._finish_move()
                event.accept()
                return True
            if kind in (QEvent.UngrabMouse, QEvent.Hide, QEvent.WindowDeactivate):
                self._finish_move()
        result = super().event(event)
        if kind in (QEvent.Show, QEvent.WindowActivate) and self._fullscreen_owner is not None:
            QTimer.singleShot(0, self, self._stack_behind_fullscreen)
        return result

    def resizeEvent(self, event):
        self.grip.move(self.width() - self.grip.width(), self.height() - self.grip.height())
        super().resizeEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = theme.qcolor(theme.CONTENT)
        if self.property('danmakuFloatGlass'):
            color.setAlpha(max(1, round(255 * self._glass_opacity / 100)))
        if self._native_corners:
            outline = QPainterPath()
            outline.addRect(QRectF(self.rect()))
        else:
            outline = continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.CORNER_RADIUS)
        painter.fillPath(outline, color)
        panel = self.stack.currentWidget()
        if self.property('danmakuFloatGlass') and panel is not None:
            text_top = panel.body.viewport().mapTo(self, QPoint()).y()
            # Fade under the header and share the outer contour so the scrim cannot draw an inner box.
            scrim = QLinearGradient(0, text_top, 0, text_top + self.CORNER_RADIUS)
            color.setAlpha(0)
            scrim.setColorAt(0, color)
            color.setAlpha(self.TEXT_MASK_ALPHA)
            scrim.setColorAt(1, color)
            painter.fillPath(outline, scrim)
        if not self._native_corners:
            painter.strokePath(outline, QPen(theme.qcolor(theme.BORDER_STRONG), 1))
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
