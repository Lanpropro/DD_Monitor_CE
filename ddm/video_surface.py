"""Keep libmpv's native rendering children inside the Qt video mask on Windows."""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QTransform
from PySide6.QtWidgets import QApplication, QFrame

from . import theme
from .badge_surface import BadgeSurface


class VideoCorner(BadgeSurface):
    """Small alpha-blended corners above libmpv's binary native clipping region."""
    def __init__(self, parent, *, right=False):
        super().__init__(parent)
        self.right = right
        self._mask_path = QPainterPath()
        self.setFixedSize(12, 12)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_NativeWindow)

    def refresh_theme(self):
        self.update()

    def _render_badge(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        if self.right:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        # Only blend the one-pixel rim. Filling the whole inverse corner would
        # cover the skin background outside the rounded tile with a solid block.
        rim = 1 / self.devicePixelRatioF()
        outside = QPainterPath()
        outside.addRoundedRect(QRectF(-rim, -rim, 24 + rim * 2, 24 + rim * 2),
                               9 + rim, 9 + rim)
        inside = QPainterPath()
        inside.addRoundedRect(QRectF(0, 0, 24, 24), 9, 9)
        painter.fillPath(outside.subtracted(inside),
                         theme.qcolor('#FFFFFF' if theme.is_light() else theme.TILE_BG))

    def paintEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self._paint_layered()
        else:
            painter = QPainter(self)
            self._render_badge(painter)


class VideoSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._clip_timer = QTimer(self)
        self._clip_timer.setInterval(100)
        self._clip_timer.timeout.connect(self._retry_clip)
        self._clip_attempts = 0
        self._mask_clip_state = None

    def _clip_state(self):
        return (self.mask(), self.size(), self.devicePixelRatioF(),
                int(self.internalWinId()))

    def setMask(self, region):
        state = self._clip_state()
        if region == state[0] and state == self._mask_clip_state:
            return
        super().setMask(region)
        self.refresh_clip()
        self._clip_native_video()
        self._mask_clip_state = self._clip_state()

    def clearMask(self):
        self._mask_clip_state = None
        super().clearMask()

    def refresh_clip(self):
        self._mask_clip_state = None
        self._clip_attempts = 0
        if self._clip_timer.interval() != 100:
            self._clip_timer.setInterval(100)
        if not self._clip_timer.isActive():
            self._clip_timer.start()

    def _retry_clip(self):
        self._clip_attempts += 1
        if (not self.isVisible() or sys.platform != "win32"
                or QApplication.platformName() != "windows" or self.mask().isEmpty()):
            self._clip_timer.stop()
            return
        if self._clip_native_video():
            # libmpv may reset the region or replace nested output windows later.
            self._clip_attempts = 0
            self._clip_timer.setInterval(500)
        elif self._clip_attempts >= 300:
            self._clip_timer.stop()
        else:
            self._clip_timer.setInterval(100)

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.WinIdChange, QEvent.Type.Resize,
                            QEvent.Type.DevicePixelRatioChange, QEvent.Type.Show):
            timer = getattr(self, "_clip_timer", None)
            if timer is not None:
                self.refresh_clip()
                if event.type() != QEvent.Type.Resize:
                    self._clip_native_video()
        return result

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0210 and msg.wParam & 0xffff == 1:  # WM_PARENTNOTIFY / WM_CREATE
                self.refresh_clip()  # libmpv creates/replaces its output after binding.
        return super().nativeEvent(event_type, message)

    def _clip_native_video(self, *, apply_root=True):
        if (sys.platform != "win32" or QApplication.platformName() != "windows"
                or not self.testAttribute(Qt.WidgetAttribute.WA_NativeWindow) or self.mask().isEmpty()):
            return True
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)
        user32.EnableWindow.argtypes = (wintypes.HWND, wintypes.BOOL)
        user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user32.MapWindowPoints.argtypes = (wintypes.HWND, wintypes.HWND,
                                          ctypes.POINTER(wintypes.POINT), wintypes.UINT)
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
        user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int)
        gdi32.OffsetRgn.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
        gdi32.EqualRgn.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        root = int(self.winId())
        # Qt 与 libmpv 使用同一份区域，避免两种圆角算法在高 DPI 下偏离。
        scale = self.devicePixelRatioF()
        mask = QTransform().scale(scale, scale).map(self.mask())
        native_mask = gdi32.CreateRectRgn(0, 0, 0, 0)
        for rect in mask:
            part = gdi32.CreateRectRgn(rect.x(), rect.y(),
                rect.x() + rect.width(), rect.y() + rect.height())
            try:
                gdi32.CombineRgn(native_mask, native_mask, part, 2)  # RGN_OR
            finally:
                gdi32.DeleteObject(part)

        output_found = []
        def clip(hwnd, _unused):
            if hwnd != root:
                name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, name, len(name))
                if not name.value.lower().startswith("mpv"):
                    return True
                if name.value.lower().startswith("mpv"):
                    output_found.append(hwnd)
                    user32.EnableWindow(hwnd, False)
            origin = wintypes.POINT()
            user32.MapWindowPoints(root, hwnd, ctypes.byref(origin), 1)
            # libmpv can grow its output after creation without resizing this Qt
            # surface. Windows already clips to the child's current bounds;
            # intersecting with its initial bounds would freeze a small mask.
            region = gdi32.CreateRectRgn(0, 0, 0, 0)
            gdi32.CombineRgn(region, native_mask, None, 5)  # RGN_COPY
            gdi32.OffsetRgn(region, origin.x, origin.y)
            try:
                if region:
                    current = gdi32.CreateRectRgn(0, 0, 0, 0)
                    try:
                        unchanged = bool(current and user32.GetWindowRgn(hwnd, current)
                                         and gdi32.EqualRgn(current, region))
                    finally:
                        if current:
                            gdi32.DeleteObject(current)
                    if not unchanged and user32.SetWindowRgn(hwnd, region, True):
                        region = None  # Ownership transfers to Windows.
            finally:
                if region:
                    gdi32.DeleteObject(region)
            return True

        try:
            if apply_root:
                clip(root, 0)
            user32.EnumChildWindows(root, callback_type(clip), 0)
        finally:
            gdi32.DeleteObject(native_mask)
        return bool(output_found)
