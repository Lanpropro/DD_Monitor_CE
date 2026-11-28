"""Shared client-side title bar for ordinary host and plugin windows."""
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QDialog, QFileDialog, QMainWindow, QMessageBox, QSizePolicy, QToolButton

from . import theme
from .corner_geometry import continuous_path
from .panel_resize import resize_edges
from .settings_backdrop import apply_frame
from .settings_window import SettingsTitleBar


class WindowTitleBar(SettingsTitleBar):
    def __init__(self, window):
        super().__init__(window, close_action=window.close)
        self.setObjectName('WindowTitleBar')
        self.setFixedHeight(42)
        self.row.setContentsMargins(14, 4, 8, 4)
        self.row.setSpacing(6)
        self.close_button.setAccessibleName('关闭窗口')
        self.close_button.setToolTip('关闭')
        self.breadcrumb.setTextFormat(Qt.PlainText)
        self.breadcrumb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.row.setStretch(0, 1)
        self.row.setStretch(1, 0)
        self.breadcrumb.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.breadcrumb.setText(window.windowTitle())
        window.windowTitleChanged.connect(self.breadcrumb.setText)
        flags = window.windowFlags()
        self.maximize = None
        if flags & Qt.WindowMinimizeButtonHint:
            self._button('−', '最小化', window.showMinimized)
        if flags & Qt.WindowMaximizeButtonHint:
            self.maximize = self._button('□', '最大化', self.toggle_maximized)
        self.original_margins = window.contentsMargins()
        self.uses_menu_slot = isinstance(window, QMainWindow) and window.menuWidget() is None
        self.native_corners = False
        window.installEventFilter(self)

    def _button(self, symbol, name, action):
        button = QToolButton(self)
        button.setFixedSize(34, 34)
        button.setText(symbol)
        button.setAccessibleName(name)
        button.setToolTip(name)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet('QToolButton {border: 1px solid palette(mid); border-radius: 17px;'
                             ' background: palette(base);} QToolButton:hover {background: palette(button);}'
                             ' QToolButton:pressed {background: palette(highlight);}')
        button.clicked.connect(action)
        self.row.insertWidget(self.row.count() - 1, button)
        return button

    def toggle_maximized(self):
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()

    def mouseDoubleClickEvent(self, event):
        if self.maximize is not None and event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def sync(self, window):
        fullscreen = window.isFullScreen() and not window.isMaximized()
        visible = window.isWindow() and not fullscreen and getattr(window, '_fullscreen_tile', None) is None
        if not self.uses_menu_slot:
            margins = self.original_margins
            window.setContentsMargins(margins.left(), margins.top() + (self.height() if visible else 0),
                                      margins.right(), margins.bottom())
            self.setGeometry(0, 0, window.width(), self.height())
        self.setVisible(visible)
        if self.maximize is not None:
            name = '还原' if window.isMaximized() else '最大化'
            self.maximize.setText('❐' if window.isMaximized() else '□')
            self.maximize.setAccessibleName(name)
            self.maximize.setToolTip(name)

    def update_corners(self, window):
        if not window.isWindow() or window.isMaximized() or window.isFullScreen():
            window.clearMask()
        elif not self.native_corners:
            outline = continuous_path(QRectF(window.rect()), theme.RADIUS_MD)
            window.setMask(QRegion(outline.toFillPolygon().toPolygon()))

    def eventFilter(self, window, event):
        kind = event.type()
        if kind in (QEvent.Resize, QEvent.Show, QEvent.WindowStateChange, QEvent.ParentChange):
            if kind == QEvent.Resize:
                if not self.uses_menu_slot:
                    self.resize(window.width(), self.height())
            else:
                self.sync(window)
            if window.isVisible():
                if kind == QEvent.Show and window.isWindow():
                    self.native_corners = apply_frame(window, theme.is_light())
                self.update_corners(window)
        return False


def install_window_chrome(window):
    if not window.isWindow() or isinstance(window, QFileDialog) or getattr(window, 'use_native_title_bar', False):
        return
    if window.windowType() not in (Qt.Window, Qt.Dialog, Qt.Tool, Qt.Sheet):
        return
    if window.windowFlags() & Qt.FramelessWindowHint:
        return window.findChild(WindowTitleBar, 'WindowTitleBar', Qt.FindDirectChildrenOnly)
    if not isinstance(window, QDialog) and not window.windowTitle():
        return
    if isinstance(window, QMessageBox):
        window.setOption(QMessageBox.Option.DontUseNativeDialog)
    window.setWindowFlag(Qt.FramelessWindowHint)
    bar = window.findChild(WindowTitleBar, 'WindowTitleBar', Qt.FindDirectChildrenOnly)
    if bar is None:
        bar = WindowTitleBar(window)
        window.setProperty('appWindowChrome', True)
        if bar.uses_menu_slot:
            window.setMenuWidget(bar)
    bar.sync(window)
    return bar


def start_edge_resize(widget, event):
    window = widget.window()
    if (not window.property('appWindowChrome') or not window.isWindow()
            or window.isMaximized() or window.isFullScreen() or not window.windowHandle()):
        return False
    edges = resize_edges(window, window.mapFromGlobal(event.globalPosition().toPoint()))
    if window.minimumWidth() == window.maximumWidth():
        edges &= ~(Qt.LeftEdge | Qt.RightEdge)
    if window.minimumHeight() == window.maximumHeight():
        edges &= ~(Qt.TopEdge | Qt.BottomEdge)
    return bool(edges and window.windowHandle().startSystemResize(edges))
