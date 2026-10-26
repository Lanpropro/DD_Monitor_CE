"""Per-pixel alpha for light badges above Windows native video windows."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QEvent, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from . import theme


class BitmapInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG),
        ("height", wintypes.LONG), ("planes", wintypes.WORD),
        ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
        ("bytes", wintypes.DWORD), ("xppm", wintypes.LONG),
        ("yppm", wintypes.LONG), ("used", wintypes.DWORD),
        ("important", wintypes.DWORD)]


class Blend(ctypes.Structure):
    _fields_ = [("operation", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
        ("alpha", ctypes.c_ubyte), ("format", ctypes.c_ubyte)]


class BadgeSurface(QWidget):
    @property
    def badge_path(self):
        if not theme.is_light():
            return self._mask_path
        path = QPainterPath()
        path.addRoundedRect(QRectF(.5, .5, self.width()-1, self.height()-1),
            (self.height()-1)/2, (self.height()-1)/2)
        return path

    def _render_badge(self, painter):
        self.paint_badge(painter)
        if theme.is_light():
            painter.setPen(QPen(QColor("#D7DDE7"), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.badge_path)

    def refresh_theme(self):
        if not hasattr(self, "_mask_path"):
            return
        if theme.is_light():
            self.clearMask()
        else:
            self._clear_layered()
            self.setMask(QRegion(self._mask_path.toFillPolygon().toPolygon()))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._render_badge(painter)
        painter.end()
        if (theme.is_light() and sys.platform == "win32"
                and QApplication.platformName() == "windows"
                and self.testAttribute(Qt.WA_NativeWindow) and self.isVisible()):
            self._paint_layered()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.WinIdChange, QEvent.DevicePixelRatioChange, QEvent.Show):
            if hasattr(self, "_mask_path"):
                QTimer.singleShot(0, self, self.refresh_theme)
        return result

    def _clear_layered(self):
        self._last_alpha_state = None
        hwnd = getattr(self, "_layered_hwnd", None)
        if hwnd and sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
            style = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, style & ~0x00080000)
            self._layered_hwnd = None

    def _layered_render_key(self):
        return None

    def _paint_layered(self):
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        hwnd = int(self.winId())
        user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        bounds = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(bounds)) or not bounds.right or not bounds.bottom:
            return
        key = self._layered_render_key()
        state = (hwnd, bounds.right, bounds.bottom, self.devicePixelRatioF(), key)
        if key is not None and state == getattr(self, '_last_alpha_state', None):
            return
        image = QImage(bounds.right, bounds.bottom, QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.devicePixelRatioF())
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self._render_badge(painter)
        painter.end()

        user32.GetDC.argtypes = (wintypes.HWND,)
        user32.GetDC.restype = wintypes.HDC
        user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        user32.UpdateLayeredWindow.argtypes = (wintypes.HWND, wintypes.HDC,
            ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
            ctypes.POINTER(wintypes.POINT), wintypes.DWORD, ctypes.POINTER(Blend), wintypes.DWORD)
        gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.POINTER(BitmapInfo),
            wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
        gdi32.CreateDIBSection.restype = wintypes.HANDLE
        gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
        gdi32.SelectObject.restype = wintypes.HANDLE
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        gdi32.DeleteDC.argtypes = (wintypes.HDC,)
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        info = BitmapInfo(40, image.width(), -image.height(), 1, 32, 0, 0, 0, 0, 0, 0)
        data = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(screen, ctypes.byref(info), 0, ctypes.byref(data), None, 0)
        try:
            if not memory or not bitmap:
                return
            previous = gdi32.SelectObject(memory, bitmap)
            try:
                ctypes.memmove(data, bytes(image.constBits()), image.sizeInBytes())
                style = user32.GetWindowLongW(hwnd, -20)
                user32.SetWindowLongW(hwnd, -20, style | 0x00080000)
                size = wintypes.SIZE(image.width(), image.height())
                origin = wintypes.POINT(0, 0)
                blend = Blend(0, 0, 255, 1)
                self._alpha_uploaded = bool(user32.UpdateLayeredWindow(hwnd, screen, None,
                    ctypes.byref(size), memory, ctypes.byref(origin), 0, ctypes.byref(blend), 2))
                self._layered_hwnd = hwnd
                if self._alpha_uploaded:
                    self._last_alpha_state = state
            finally:
                gdi32.SelectObject(memory, previous)
        finally:
            if bitmap:
                gdi32.DeleteObject(bitmap)
            if memory:
                gdi32.DeleteDC(memory)
            user32.ReleaseDC(None, screen)
