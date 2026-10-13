"""Interruptible wave reveal of UI snapshots, leaving live video uncovered."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import motion, theme
from .video_surface import VideoSurface


def wave_path(progress, width, height):
    amplitude = min(52.0, width * .035)
    edge = progress * (width + amplitude * 2) - amplitude
    path = QPainterPath()
    path.moveTo(0, 0)
    path.lineTo(edge, 0)
    path.cubicTo(edge + amplitude, height * .18,
                 edge - amplitude, height * .35, edge, height * .5)
    path.cubicTo(edge + amplitude, height * .68,
                 edge - amplitude, height * .85, edge, height)
    path.lineTo(0, height)
    path.closeSubpath()
    return path


def ui_snapshot(window):
    snapshot = window.grab().toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    # Native VLC output cannot be captured by QWidget.grab(). A hole leaves the
    # real output playing beneath the transition, rather than freezing a frame.
    painter = QPainter(snapshot)
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    for surface in window.findChildren(VideoSurface):
        if surface.isVisible():
            painter.fillRect(QRect(surface.mapTo(window, QPoint()), surface.size()), Qt.transparent)
    painter.end()
    painter = QPainter(snapshot)
    for tile in getattr(getattr(window, 'wall', None), 'tiles', []):
        for badge in (tile.stream_badge, tile.title_badge, tile.time_badge, tile.controls):
            if badge.isVisible():
                painter.drawPixmap(badge.mapTo(window, QPoint()), badge.grab())
    painter.end()
    return QPixmap.fromImage(snapshot)


class WaveOverlay(QWidget):
    def __init__(self, window, dark, light):
        super().__init__(window, Qt.Tool | Qt.FramelessWindowHint |
            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.dark, self.light = dark, light
        self.progress = 0.0
        self.target_light = True
        self.setGeometry(QRect(window.mapToGlobal(QPoint()), window.size()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        visible = wave_path(self.progress, self.width(), self.height())
        if self.target_light:
            full = QPainterPath()
            full.addRect(0, 0, self.width(), self.height())
            visible = full.subtracted(visible)
        painter.setClipPath(visible)
        painter.drawPixmap(0, 0, self.dark if self.target_light else self.light)


class ThemeTransition(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.overlays = []
        self._watched = []
        self._changing = False
        self._keyboard = False
        self.progress = float(theme.is_light())
        self.animation = QVariantAnimation(self)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self.finish)
        QApplication.instance().installEventFilter(self)
        theme.signals().changed.connect(self._external_change)

    def _windows(self):
        windows = []
        for widget in QApplication.topLevelWidgets():
            parent = widget
            while parent is not None and parent is not self.window:
                parent = parent.parentWidget()
            if (parent is self.window and widget.isVisible()
                    and not isinstance(widget, WaveOverlay)
                    and widget.windowType() not in (Qt.Popup, Qt.ToolTip, Qt.Tool)):
                windows.append(widget)
        return windows

    def change(self, mode):
        if not motion.enabled() or self._keyboard or not self.window.isVisible():
            self.finish()
            self._apply(mode)
            return
        previous_light = theme.is_light()
        windows = self._windows()
        running = bool(self.overlays)
        before = [] if running else [(window, ui_snapshot(window)) for window in windows]
        self._apply(mode)
        target_light = theme.is_light()
        if target_light == previous_light:
            return
        if not running:
            self.progress = float(previous_light)
            for window, old in before:
                new = ui_snapshot(window)
                dark, light = (old, new) if target_light else (new, old)
                overlay = WaveOverlay(window, dark, light)
                self.overlays.append(overlay)
                self._watched.extend([window] + window.findChildren(VideoSurface))
        target = float(target_light)
        start = self.progress
        self.animation.blockSignals(True)
        self.animation.stop()
        for overlay in self.overlays:
            overlay.target_light = target_light
            overlay.progress = start
            overlay.show()
            overlay.raise_()
        self.animation.setDuration(max(1, round(motion.THEME_WAVE_MS * abs(target-start))))
        self.animation.setStartValue(start)
        self.animation.setEndValue(target)
        self.animation.setCurrentTime(0)
        self.animation.blockSignals(False)
        self.progress = start
        self.animation.start()

    def _apply(self, mode):
        self._changing = True
        try:
            theme.apply(mode)
        finally:
            self._changing = False

    def _frame(self, progress):
        self.progress = float(progress)
        for overlay in self.overlays:
            overlay.progress = self.progress
            overlay.update()

    def finish(self):
        self.animation.stop()
        for overlay in self.overlays:
            overlay.hide()
            overlay.dark = overlay.light = QPixmap()
            overlay.deleteLater()
        self.overlays.clear()
        self._watched.clear()
        self.progress = float(theme.is_light())

    def _external_change(self, _mode):
        if not self._changing:
            self.finish()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress:
            self._keyboard = True
        elif event.type() == QEvent.MouseButtonPress:
            self._keyboard = False
        if watched in self._watched and event.type() in (
                QEvent.Resize, QEvent.Move, QEvent.Hide, QEvent.Close,
                QEvent.DevicePixelRatioChange, QEvent.WindowStateChange):
            self.finish()
        return False
