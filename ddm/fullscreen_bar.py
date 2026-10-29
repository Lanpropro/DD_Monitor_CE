"""Interactive bottom bar with per-pixel alpha above native video on Windows."""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget, QLabel

from .badge_surface import BadgeSurface


class FullscreenBar(BadgeSurface):
    def __init__(self, parent):
        super().__init__(parent)
        self.setProperty('fullscreen', False)
        self._masked_labels = set()

    def set_fullscreen(self, enabled):
        if enabled == self.property('fullscreen'):
            return
        self.setProperty('fullscreen', enabled)
        if enabled:
            self.setAttribute(Qt.WA_NativeWindow)
        else:
            self._mask_label_windows(False)
            self._clear_layered()
        for widget in (self, *self.findChildren(QWidget)):
            widget.setProperty('fullscreen', enabled)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.refresh_theme()

    def refresh_theme(self):
        if self.property('fullscreen'):
            self._schedule_layered_paint_if_native()
        else:
            self._clear_layered()
        self.update()

    def _schedule_layered_paint_if_native(self):
        if (self.property('fullscreen') and sys.platform == 'win32'
                and QApplication.platformName() == 'windows' and self.isVisible()):
            self._schedule_layered_paint()

    def _render_badge(self, painter):
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0, 150))
        painter.fillRect(self.rect(), shade)

    def _render_layered(self, painter):
        # Capture actual controls too, preserving text, hover, focus and editor caret.
        # This runs after Qt's paint stack, under BadgeSurface's coalescing guard.
        self.render(painter, QPoint(), QRegion(), QWidget.DrawChildren)

    def _paint_layered(self):
        super()._paint_layered()
        # Read-only native labels otherwise draw opaque rectangles above the
        # composited bar. Their text is already included in the uploaded frame.
        self._mask_label_windows(True)

    def _mask_label_windows(self, hide):
        if sys.platform != 'win32' or QApplication.platformName() != 'windows':
            return
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HRGN
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN, wintypes.BOOL)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        for label in self.findChildren(QLabel):
            if not (label.testAttribute(Qt.WA_NativeWindow)
                    and label.testAttribute(Qt.WA_TransparentForMouseEvents)):
                continue
            hwnd = int(label.winId())
            if hide and hwnd not in self._masked_labels:
                region = gdi32.CreateRectRgn(0, 0, 0, 0)
                if user32.SetWindowRgn(hwnd, region, True):
                    self._masked_labels.add(hwnd)
                elif region:
                    gdi32.DeleteObject(region)
            elif not hide and hwnd in self._masked_labels:
                user32.SetWindowRgn(hwnd, None, True)
        if not hide:
            self._masked_labels.clear()

    def paintEvent(self, event):
        if not self.property('fullscreen'):
            QWidget.paintEvent(self, event)
            return
        painter = QPainter(self)
        self._render_badge(painter)
        painter.end()
        self._schedule_layered_paint_if_native()

    def event(self, event):
        if event.type() == QEvent.ChildAdded and isinstance(event.child(), QWidget):
            event.child().installEventFilter(self)
        result = QWidget.event(self, event)
        if event.type() in (QEvent.Show, QEvent.WinIdChange, QEvent.DevicePixelRatioChange):
            QTimer.singleShot(0, self, self._schedule_layered_paint_if_native)
        return result

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ChildAdded and isinstance(event.child(), QWidget):
            event.child().installEventFilter(self)
        if event.type() in (QEvent.Paint, QEvent.Show, QEvent.Hide, QEvent.Move, QEvent.Resize):
            self._schedule_layered_paint_if_native()
        return super().eventFilter(watched, event)
