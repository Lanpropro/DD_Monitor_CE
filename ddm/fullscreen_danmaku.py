"""全屏视频上的滚动弹幕。"""
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class FullscreenDanmaku(QWidget):
    """透明原生子窗口：盖在 VLC 视频 HWND 上，鼠标事件交给视频格子。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NativeWindow)
        self._items: list[dict] = []
        self._lane_ready: list[float] = []
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def clear(self) -> None:
        self._timer.stop()
        self._items.clear()
        self._lane_ready.clear()
        self.update()

    def add_message(self, text: str, color: str = "") -> None:
        if not self.isVisible() or not text or self.width() < 100:
            return
        font = QFont()
        font.setPixelSize(max(18, min(28, self.height() // 30)))
        font.setBold(True)
        message = str(text).replace("\n", " ")[:120]
        width = QFontMetrics(font).horizontalAdvance(message)
        lane_height = font.pixelSize() + 12
        lanes = max(1, int(self.height() * 0.72) // lane_height)
        if len(self._lane_ready) != lanes:
            self._lane_ready = [0.0] * lanes
        now = time.monotonic()
        lane = min(range(lanes), key=self._lane_ready.__getitem__)
        if self._lane_ready[lane] > now:
            return
        speed = max(110, self.width() / 8)
        self._lane_ready[lane] = now + (width + 48) / speed
        self._items.append({"text": message, "font": font, "color": QColor(color or "#ffffff"),
                            "width": width, "y": int(self.height() * 0.08) +
                            (lane + 1) * lane_height, "speed": speed, "started": now})
        self._timer.start()
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        self._items = [item for item in self._items
                       if self.width() - (now - item["started"]) * item["speed"]
                       + item["width"] > 0]
        if not self._items:
            self._timer.stop()
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        now = time.monotonic()
        for item in self._items:
            painter.setFont(item["font"])
            x = self.width() - (now - item["started"]) * item["speed"]
            path = QPainterPath()
            path.addText(x, item["y"], item["font"], item["text"])
            painter.setPen(QPen(QColor(0, 0, 0, 210), 3))
            painter.setBrush(item["color"] if item["color"].isValid() else QColor("#ffffff"))
            painter.drawPath(path)
