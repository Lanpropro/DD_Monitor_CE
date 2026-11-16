"""Settings progress control using the shared theme tokens."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QProgressBar
from .. import theme
from ..corner_geometry import continuous_path


class SettingsProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(8)
        self.setProperty('customControlSurface', True)
        self.setAccessibleName('下载进度')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
        painter.drawPath(continuous_path(rect, 4))
        portion = max(0, min(1, self.value() / 100))
        if portion:
            painter.setClipPath(continuous_path(rect, 4))
            rect.setWidth(rect.width() * portion)
            painter.setBrush(theme.qcolor(theme.ACCENT))
            painter.drawPath(continuous_path(rect, 4))
