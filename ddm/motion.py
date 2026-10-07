"""轻量界面动效；尊重 Windows 的系统动画开关。"""
import ctypes
import sys

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPoint, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QGraphicsOpacityEffect, QStackedWidget


def enabled() -> bool:
    if sys.platform == "win32":
        allowed = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(allowed), 0):
            return bool(allowed.value)
    return True


class AnimatedDialog(QDialog):
    """窗口入场；不对窗口内容或视频施加图形效果。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._entrance = QVariantAnimation(self)
        self._entrance.setDuration(240)
        self._entrance.setEasingCurve(QEasingCurve.OutCubic)
        self._entrance.setStartValue(0.0)
        self._entrance.setEndValue(1.0)
        self._entrance.valueChanged.connect(self._reveal)
        self._moving = False

    def _reveal(self, progress):
        self.setWindowOpacity(0.35 + 0.65 * progress)
        self._moving = True
        self.move(self._entrance_target + QPoint(0, round(20 * (1 - progress))))
        self._moving = False

    def showEvent(self, event):
        super().showEvent(event)
        if enabled():
            self._entrance_target = self.pos()
            self._entrance.setCurrentTime(0)
            self._reveal(0.0)
            self._entrance.start()

    def moveEvent(self, event):
        if not self._moving and self._entrance.state() == QAbstractAnimation.Running:
            self._entrance.stop()
            self.setWindowOpacity(1.0)
        super().moveEvent(event)

    def hideEvent(self, event):
        interrupted = self._entrance.state() == QAbstractAnimation.Running
        self._entrance.stop()
        self.setWindowOpacity(1.0)
        if interrupted:
            self.move(self._entrance_target)
        super().hideEvent(event)


def lifted_drag(pixmap, hotspot):
    """拖影放大并留出阴影空间，保持鼠标在卡片上的相对位置。"""
    if not enabled():
        return pixmap, hotspot
    scale, padding = 1.055, 10
    ratio = pixmap.devicePixelRatio()
    lifted = pixmap.scaled(round(pixmap.width() * scale), round(pixmap.height() * scale),
                           Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    margin = round(padding * ratio)
    result = QPixmap(lifted.width() + 2 * margin, lifted.height() + 2 * margin)
    result.setDevicePixelRatio(ratio)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 18))
    width, height = lifted.width() / ratio, lifted.height() / ratio
    for spread in (8, 6, 4, 2):
        painter.drawRoundedRect(padding - spread, padding + 3 - spread,
                                round(width + 2 * spread), round(height + 2 * spread), 12, 12)
    painter.drawPixmap(QPoint(padding, padding), lifted)
    painter.end()
    return result, QPoint(round(hotspot.x() * scale) + padding,
                          round(hotspot.y() * scale) + padding)


class PageRevealEffect(QGraphicsOpacityEffect):
    """只移动绘制内容，不改变设置页布局或控件的最终位置。"""
    def draw(self, painter):
        offset = QPoint()
        pixmap = self.sourcePixmap(Qt.LogicalCoordinates, offset)
        painter.save()
        painter.setOpacity(self.opacity())
        shift = round(24 * (1 - self.opacity()) / 0.75)
        painter.drawPixmap(offset + QPoint(shift, 0), pixmap)
        painter.restore()


class SettingsStack(QStackedWidget):
    """鼠标切换设置页时滑入并淡入，连续切换从当前透明度接续。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(260)
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
            self._effect = PageRevealEffect(self)
            self._effect.setOpacity(0.25)
            self.setGraphicsEffect(self._effect)
        start = self._effect.opacity()
        self._fade.setCurrentTime(0)
        self._fade.setStartValue(start)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def hideEvent(self, event):
        self.finish_transition()
        super().hideEvent(event)
