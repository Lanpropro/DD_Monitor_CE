"""Interruptible wave reveal of UI snapshots, leaving live video uncovered."""
import sys
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from . import motion, theme
from .video_surface import VideoSurface


def wave_path(progress, width, height, origin=None):
    origin = origin if origin is not None else QPoint()
    radius = max(((x-origin.x())**2 + (y-origin.y())**2)**.5
        for x in (0, width) for y in (0, height)) * progress
    path = QPainterPath()
    path.addEllipse(origin.x()-radius, origin.y()-radius, radius*2, radius*2)
    return path


def ui_snapshot(window):
    scale = window.devicePixelRatioF()
    snapshot = QPixmap(round(window.width()*scale), round(window.height()*scale))
    snapshot.setDevicePixelRatio(scale)
    snapshot.fill(Qt.transparent)
    # Native VLC output cannot be captured by QWidget.grab(). A hole leaves the
    # real output playing beneath the transition, rather than freezing a frame.
    region = QRegion(window.rect())
    for surface in window.findChildren(VideoSurface):
        if surface.isVisible():
            region = region.subtracted(QRegion(QRect(surface.mapTo(window, QPoint()), surface.size())))
    painter = QPainter(snapshot)
    window.render(painter, QPoint(), region, QWidget.DrawWindowBackground | QWidget.DrawChildren)
    for tile in getattr(getattr(window, 'wall', None), 'tiles', []):
        for badge in (tile.stream_badge, tile.title_badge, tile.time_badge, tile.controls):
            if badge.isVisible():
                painter.drawPixmap(badge.mapTo(window, QPoint()), badge.grab())
    painter.end()
    return snapshot


class WaveOverlay(QWidget):
    def __init__(self, window, snapshot, origin):
        super().__init__(window, Qt.Tool | Qt.FramelessWindowHint |
            Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.snapshot = snapshot
        self.origin = window.mapFromGlobal(origin)
        self.progress = 0.0
        self._native_clip = sys.platform == 'win32' and QApplication.platformName() == 'windows'
        self.setGeometry(QRect(window.mapToGlobal(QPoint()), window.size()))

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint(painter, clipped=not self._native_clip)

    def _paint(self, painter, *, clipped):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if clipped:
            revealed = wave_path(self.progress, self.width(), self.height(), self.origin)
            full = QPainterPath()
            full.setFillRule(Qt.OddEvenFill)
            full.addRect(0, 0, self.width(), self.height())
            full.addPath(revealed)
            painter.setClipPath(full)
        painter.drawPixmap(0, 0, self.snapshot)

    def grab(self):
        # Qt's grab does not include a Win32 window region. Compose the visible
        # frame explicitly when a second click interrupts the native reveal.
        if not self._native_clip:
            return super().grab()
        visible = QPixmap(self.snapshot.size())
        visible.setDevicePixelRatio(self.snapshot.devicePixelRatio())
        visible.fill(Qt.transparent)
        painter = QPainter(visible)
        self._paint(painter, clipped=True)
        painter.end()
        return visible

    def reveal(self, progress):
        self.progress = progress
        if self._native_clip:
            if self._clip_native():
                return
            self._native_clip = False
            import ctypes
            ctypes.windll.user32.SetWindowRgn(int(self.winId()), None, False)
        self.update()

    def _clip_native(self):
        import ctypes
        from ctypes import wintypes

        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        gdi32.CreateEllipticRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateEllipticRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
        scale = self.devicePixelRatioF()
        radius = max(((x-self.origin.x())**2 + (y-self.origin.y())**2)**.5
            for x in (0, self.width()) for y in (0, self.height())) * self.progress
        region = gdi32.CreateRectRgn(0, 0, round(self.width()*scale), round(self.height()*scale))
        hole = gdi32.CreateEllipticRgn(round((self.origin.x()-radius)*scale),
            round((self.origin.y()-radius)*scale), round((self.origin.x()+radius)*scale),
            round((self.origin.y()+radius)*scale))
        try:
            if not region or not hole or not gdi32.CombineRgn(region, region, hole, 4):  # RGN_DIFF
                return False
            # DWM clips the already uploaded snapshot; do not invalidate and
            # re-upload its full 4K bitmap for every animation frame.
            if user32.SetWindowRgn(int(self.winId()), region, False):
                region = None  # Ownership transfers to Windows.
                return True
            return False
        finally:
            if hole:
                gdi32.DeleteObject(hole)
            if region:
                gdi32.DeleteObject(region)


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

    def change(self, mode, origin=None):
        if not motion.enabled() or self._keyboard or not self.window.isVisible():
            self.finish()
            self._apply(mode)
            return
        previous_light = theme.is_light()
        windows = self._windows()
        if origin is None:
            origin = self.window.sidebar.appearance_button.mapToGlobal(QPoint())
        before = []
        for window in windows:
            snapshot = ui_snapshot(window)
            # Preserve the visible mixture when another click interrupts a reveal.
            # The next colour still flows from its button, without a full-frame flash.
            for overlay in self.overlays:
                if overlay.parentWidget() is window:
                    painter = QPainter(snapshot)
                    painter.drawPixmap(0, 0, overlay.grab())
                    painter.end()
            before.append((window, snapshot))
        self.finish()
        self._apply(mode)
        if theme.is_light() == previous_light:
            return
        self.progress = 0.0
        for window, old in before:
            overlay = WaveOverlay(window, old, origin)
            self.overlays.append(overlay)
            self._watched.extend([window] + window.findChildren(VideoSurface))
            overlay.show()
            overlay.raise_()
        self.animation.blockSignals(True)
        self.animation.setDuration(motion.THEME_WAVE_MS)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setCurrentTime(0)
        self.animation.blockSignals(False)
        self.animation.start()

    def _apply(self, mode):
        self._changing = True
        app = QApplication.instance()
        app.removeEventFilter(self)
        updates_enabled = self.window.updatesEnabled()
        self.window.setUpdatesEnabled(False)
        try:
            theme.apply(mode)
        finally:
            self.window.setUpdatesEnabled(updates_enabled)
            app.installEventFilter(self)
            self._changing = False

    def _frame(self, progress):
        self.progress = float(progress)
        for overlay in self.overlays:
            overlay.reveal(self.progress)

    def finish(self):
        self.animation.stop()
        for overlay in self.overlays:
            overlay.hide()
            overlay.snapshot = QPixmap()
            overlay.deleteLater()
        self.overlays.clear()
        self._watched.clear()
        self.progress = float(theme.is_light())

    def _external_change(self, _mode):
        if not self._changing:
            self.finish()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.KeyPress:
            self._keyboard = True
        elif kind == QEvent.MouseButtonPress:
            self._keyboard = False
        if watched in self._watched and kind in (
                QEvent.Resize, QEvent.Move, QEvent.Hide, QEvent.Close,
                QEvent.DevicePixelRatioChange, QEvent.WindowStateChange):
            self.finish()
        return False
