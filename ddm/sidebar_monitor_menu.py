"""Streamer monitoring popup anchored to the sidebar rail."""
from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .sidebar_navigation import NavigationButton
from .streamer_monitor_panel import StreamerMonitorPanel


class StreamerMonitorMenu(QFrame):
    settingsRequested = Signal()

    def __init__(self, button):
        super().__init__(button, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.button = button
        self.read_rows = tuple
        self.setObjectName('StreamerMonitorMenu')
        self.setAccessibleName('主播监控')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel('主播监控', self)
        title.setObjectName('AppTitle')
        header.addWidget(title, 1)
        close = NavigationButton('关闭监控', 'close', self)
        close.setFixedSize(26, 26)
        close.clicked.connect(self._dismiss)
        header.addWidget(close)
        layout.addLayout(header)

        self.panel = StreamerMonitorPanel(self)
        self.panel.read_rows = lambda: self.read_rows()
        layout.addWidget(self.panel)
        self.settings_button = QPushButton('主播监控设置', self, objectName='IconButton')
        self.settings_button.clicked.connect(self._open_settings)
        layout.addWidget(self.settings_button)

        button.setCheckable(True)
        button.clicked.connect(self._toggle)
        button.installEventFilter(self)

    def _toggle(self, checked):
        if not checked:
            self.hide()
            return
        self.panel.refresh()
        button = self.button
        anchor = button.mapToGlobal(QPoint(0, button.height()))
        area = button.screen().availableGeometry().adjusted(8, 8, -8, -8)
        size = self.sizeHint()
        self.resize(min(size.width(), area.width()), min(360, size.height(), area.height()))
        right = anchor.x() + button.width() + 7
        left = right if right + self.width() <= area.right() + 1 else anchor.x() - self.width() - 7
        top = max(area.top(), min(anchor.y(), area.bottom() + 1) - self.height())
        self.move(max(area.left(), left), top)
        self.show()
        self.panel.scroll.setFocus(Qt.PopupFocusReason)

    def _dismiss(self):
        self.hide()
        self.button.setFocus(Qt.PopupFocusReason)

    def _open_settings(self):
        self._dismiss()
        self.settingsRequested.emit()

    def eventFilter(self, watched, event):
        if watched is self.button and event.type() == QEvent.Hide:
            self.hide()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        if self.button.rect().contains(self.button.mapFromGlobal(event.globalPosition().toPoint())):
            self.setAttribute(Qt.WA_NoMouseReplay)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._dismiss()
            event.accept()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self.button.setChecked(False)
        super().hideEvent(event)
