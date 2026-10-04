"""轻量画面弹幕：有界轨道、匀速滚动，原生视频窗口上的鼠标穿透浮层。"""
import math
import sys
import time
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import theme


@dataclass
class _Comment:
    image: QPixmap
    x: float
    lane: int
    speed: float


class VideoDanmaku(QWidget):
    MAX_COMMENTS = 80
    GAP = 24
    COLOR_KEY = QColor(1, 2, 3)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.enabled = False
        self.active = False
        self.paused = False
        self.settings = {}
        self.comments: list[_Comment] = []
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._last_tick = 0.0
        self.hide()

    def apply_settings(self, settings: dict) -> None:
        values = {key: settings.get(key) for key in (
            "danmaku_font", "video_danmaku_size", "video_danmaku_speed",
            "video_danmaku_opacity", "video_danmaku_area", "video_danmaku_scale")}
        if values != self.settings:
            self.settings = values
            self.clear()
            if self.isVisible():
                self._apply_layered()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._sync_visible()

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        self._sync_visible()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        if self.paused:
            self.timer.stop()
        elif self.comments and self.isVisible():
            self._start_timer()

    def _sync_visible(self) -> None:
        visible = self.enabled and self.active
        self.setVisible(visible)
        if not visible:
            self.clear()
        elif self.comments and not self.paused:
            self._start_timer()

    def font_pixels(self) -> int:
        size = int(self.settings.get("video_danmaku_size") or 28)
        if self.settings.get("video_danmaku_scale", True):
            size = round(size * self.height() / 720)
        return max(10, min(144, size))

    def lane_height(self) -> int:
        return self.font_pixels() + 8

    def lane_count(self) -> int:
        area = int(self.settings.get("video_danmaku_area") or 50)
        return max(0, int(self.height() * area / 100) // self.lane_height())

    def add_event(self, event: dict) -> bool:
        if (not self.enabled or not self.active or self.paused or not self.isVisible()
                or (event.get("kind") or "danmaku") != "danmaku"
                or len(self.comments) >= self.MAX_COMMENTS):
            return False
        text = " ".join(str(event.get("text") or "").split())[:300]
        if not text or not self.lane_count():
            return False
        self._tick()
        font = QFont(str(self.settings.get("danmaku_font") or theme.FONT_DEFAULT))
        font.setPixelSize(self.font_pixels())
        font.setBold(True)
        metrics = QFontMetrics(font)
        text = metrics.elidedText(text, Qt.ElideRight, max(128, self.width() * 2))
        width = metrics.horizontalAdvance(text) + 8
        speed = (self.width() + width) / 8 * int(
            self.settings.get("video_danmaku_speed") or 100) / 100
        lane = next((lane for lane in range(self.lane_count())
                     if self._lane_available(lane, speed)), None)
        if lane is None:
            return False  # 满轨道时丢弃，不积压过时的弹幕。
        scale = self.devicePixelRatioF()
        image = QPixmap(math.ceil(width * scale), math.ceil(self.lane_height() * scale))
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addText(4, 4 + metrics.ascent(), font, text)
        color = QColor(str(event.get("color") or "#ffffff"))
        if not color.isValid():
            color = QColor("#ffffff")
        painter.setPen(QPen(QColor("#000000"), 2))
        painter.setBrush(color)
        painter.drawPath(path)
        painter.end()
        self.comments.append(_Comment(image, float(self.width()), lane, speed))
        self._start_timer()
        return True

    def _lane_available(self, lane: int, speed: float) -> bool:
        for comment in self.comments:
            if comment.lane != lane:
                continue
            right = comment.x + comment.image.width() / comment.image.devicePixelRatioF()
            gap = self.width() - right
            if gap < self.GAP:
                return False
            # 后发的长弹幕更快；必须在前一条离开画面之前追不上它。
            if speed > comment.speed and gap / (speed - comment.speed) < right / comment.speed:
                return False
        return True

    def _start_timer(self) -> None:
        if not self.timer.isActive():
            self._last_tick = time.monotonic()
            self.timer.start()

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_tick if self._last_tick else 0.0
        self._last_tick = now
        for comment in self.comments:
            comment.x -= elapsed * comment.speed
        self.comments = [comment for comment in self.comments
                         if comment.x + comment.image.width() /
                         comment.image.devicePixelRatioF() > 0]
        self.update()
        if not self.comments:
            self.timer.stop()

    def clear(self) -> None:
        self.timer.stop()
        self.comments.clear()
        self._last_tick = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._native_layered():
            painter.fillRect(self.rect(), self.COLOR_KEY)
        else:
            painter.setOpacity(int(self.settings.get("video_danmaku_opacity") or 80) / 100)
        for comment in self.comments:
            painter.drawPixmap(round(comment.x), comment.lane * self.lane_height(), comment.image)

    def _native_layered(self) -> bool:
        return sys.platform == "win32" and QApplication.platformName() == "windows"

    def _apply_layered(self) -> None:
        if not self._native_layered():
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        hwnd = int(self.winId())
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        key = self.COLOR_KEY.red() | self.COLOR_KEY.green() << 8 | self.COLOR_KEY.blue() << 16
        alpha = round(int(self.settings.get("video_danmaku_opacity") or 80) * 255 / 100)
        user32.SetLayeredWindowAttributes(hwnd, key, alpha, 0x00000001 | 0x00000002)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._native_layered():
            self.setAttribute(Qt.WA_OpaquePaintEvent, True)
            self.setAttribute(Qt.WA_NativeWindow, True)
            self._apply_layered()
        if self.comments and not self.paused:
            self._start_timer()
        self.raise_()

    def hideEvent(self, event) -> None:
        self.clear()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self.clear()
        super().resizeEvent(event)
