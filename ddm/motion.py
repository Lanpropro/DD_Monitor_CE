"""轻量界面动效；尊重 Windows 的系统动画开关。"""
import ctypes
import sys

from PySide6.QtCore import QEasingCurve, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QStackedWidget


def enabled() -> bool:
    if sys.platform == "win32":
        allowed = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(allowed), 0):
            return bool(allowed.value)
    return True


class SettingsStack(QStackedWidget):
    """鼠标切换设置页时轻微淡入，连续切换从当前透明度接续。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self._set_opacity)
        self._fade.finished.connect(self.finish_transition)
        self._effect = None

    def _set_opacity(self, value):
        if self._effect is not None:
            self._effect.setOpacity(value)

    def finish_transition(self):
        self._fade.stop()
        self.setGraphicsEffect(None)
        self._effect = None

    def show_page(self, index: int, animate=False):
        if index == self.currentIndex():
            return
        self._fade.stop()
        self.setCurrentIndex(index)
        if not animate or not self.isVisible() or not enabled():
            self.finish_transition()
            return
        if self._effect is None:
            self._effect = QGraphicsOpacityEffect(self)
            self._effect.setOpacity(0.65)
            self.setGraphicsEffect(self._effect)
        start = self._effect.opacity()
        self._fade.setCurrentTime(0)
        self._fade.setStartValue(start)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def hideEvent(self, event):
        self.finish_transition()
        super().hideEvent(event)
