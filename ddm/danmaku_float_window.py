"""Movable and independently resizable presentation of an existing chat pane."""
from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QSizeGrip, QVBoxLayout, QWidget

from . import theme
from .corner_geometry import continuous_path
from .panel_resize import resize_edges, set_resize_cursor
from .ui import ActionButton


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


class DanmakuFloatWindow(QWidget):
    returnRequested = Signal()

    def __init__(self, owner, panel, area):
        super().__init__(owner, Qt.Window | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.panel = panel
        self.setWindowTitle('弹幕 · DD监控室CE')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('floatingDanmaku', True)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 120)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(7, 7, 7, 7)
        self.grip = QSizeGrip(self)
        self.grip.setToolTip('拖动调整大小')
        panel.header.installEventFilter(self)
        panel.title.installEventFilter(self)
        screen = QApplication.screenAt(area.center()) or owner.screen()
        available = screen.availableGeometry()
        size = area.size().expandedTo(self.minimumSize()).boundedTo(available.size())
        point = QPoint(max(available.left(), min(area.x(), available.right() - size.width() + 1)),
                       max(available.top(), min(area.y(), available.bottom() - size.height() + 1)))
        self.setGeometry(QRect(point, size))
        theme.signals().changed.connect(self.update)

    def attach_panel(self):
        self.box.addWidget(self.panel)
        self.panel.header.setCursor(Qt.SizeAllCursor)
        self.panel.show()
        self.grip.raise_()

    def release_panel(self, parent):
        self.panel.header.unsetCursor()
        self.panel.header.removeEventFilter(self)
        self.panel.title.removeEventFilter(self)
        self.panel.setParent(parent)

    def eventFilter(self, watched, event):
        if (watched in (self.panel.header, self.panel.title) and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton and self.windowHandle() is not None
                and self.windowHandle().startSystemMove()):
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

    def closeEvent(self, event):
        self.returnRequested.emit()
        super().closeEvent(event)
