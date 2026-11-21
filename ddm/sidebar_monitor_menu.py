"""Read-only status menu anchored to the sidebar rail."""
from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .sidebar_navigation import NavigationButton
from .ui.labels import ElidedLabel


STATUS_LABELS = {
    'recording': '正在录制',
    'reconnecting': '等待重连',
    'preparing': '准备录制',
    'stopping': '正在收尾',
    'failed': '录制启动失败',
    'monitoring': '监控中',
}


class StreamerMonitorMenu(QFrame):
    def __init__(self, button):
        super().__init__(button, Qt.Popup | Qt.FramelessWindowHint)
        self.button = button
        self.setObjectName('StreamerMonitorMenu')
        self.setAccessibleName('主播监控')
        self.read_rows = tuple
        self._snapshot = None

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

        self.scroll = QScrollArea(self)
        self.scroll.setAccessibleName('主播与录制状态')
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(4)
        self.rows.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(holder)
        layout.addWidget(self.scroll)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        button.setCheckable(True)
        button.clicked.connect(self._toggle)
        button.installEventFilter(self)

    def refresh(self):
        rows = self.read_rows()
        if rows == self._snapshot:
            return
        self._snapshot = rows
        scrollbar = self.scroll.verticalScrollBar()
        position = scrollbar.value()
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        if not rows:
            empty = QLabel('暂无监控或录制中的主播')
            empty.setObjectName('SettingsHint')
            empty.setWordWrap(True)
            self.rows.addWidget(empty)
        for name, state in rows:
            row = QWidget()
            box = QHBoxLayout(row)
            box.setContentsMargins(4, 3, 6, 3)
            label = ElidedLabel(name, row)
            label.setTextFormat(Qt.PlainText)
            label.setToolTip(name)
            label.setAccessibleName(name)
            box.addWidget(label, 1)
            status = QLabel(STATUS_LABELS[state], row)
            status.setObjectName('BadgeLive' if state == 'recording' else 'BadgeOff')
            box.addWidget(status)
            self.rows.addWidget(row)
        self.rows.activate()
        scrollbar.setValue(position)

    def _toggle(self, checked):
        if not checked:
            self.hide()
            return
        self.refresh()
        button = self.button
        anchor = button.mapToGlobal(QPoint(0, button.height()))
        area = button.screen().availableGeometry().adjusted(8, 8, -8, -8)
        height = min(320, 64 + max(22, self.rows.sizeHint().height()), area.height())
        self.resize(min(300, area.width()), height)
        right = anchor.x() + button.width() + 7
        left = right if right + self.width() <= area.right() + 1 else anchor.x() - self.width() - 7
        top = max(area.top(), min(anchor.y(), area.bottom() + 1) - self.height())
        self.move(max(area.left(), left), top)
        self.show()
        self.scroll.setFocus(Qt.PopupFocusReason)
        self._timer.start()

    def _dismiss(self):
        self.hide()
        self.button.setFocus(Qt.PopupFocusReason)

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
        self._timer.stop()
        self.button.setChecked(False)
        super().hideEvent(event)
