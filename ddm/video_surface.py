"""Keep VLC's native rendering children inside the Qt video mask on Windows."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QApplication, QFrame


class VideoSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._clip_timer = QTimer(self)
        self._clip_timer.setInterval(100)
        self._clip_timer.timeout.connect(self._retry_clip)
        self._clip_attempts = 0

    def setMask(self, region):
        super().setMask(region)
        self._clip_native_video()
        self.refresh_clip()

    def refresh_clip(self):
        self._clip_attempts = 0
        self._clip_timer.start()

    def _retry_clip(self):
        self._clip_attempts += 1
        if (not self.isVisible() or self._clip_native_video(apply_root=False)
                or self._clip_attempts >= 300):
            self._clip_timer.stop()

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.WinIdChange, QEvent.Resize, QEvent.DevicePixelRatioChange):
            timer = getattr(self, "_clip_timer", None)
            if timer is not None:
                self.refresh_clip()
        return result

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0210 and msg.wParam & 0xffff == 1:  # WM_PARENTNOTIFY / WM_CREATE
                self.refresh_clip()  # VLC creates/replaces its output after binding.
        return super().nativeEvent(event_type, message)

    def _clip_native_video(self, *, apply_root=True):
        if (sys.platform != "win32" or QApplication.platformName() != "windows"
                or not self.testAttribute(Qt.WA_NativeWindow) or self.mask().isEmpty()):
            return True
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)
        user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user32.MapWindowPoints.argtypes = (wintypes.HWND, wintypes.HWND,
                                          ctypes.POINTER(wintypes.POINT), wintypes.UINT)
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
        gdi32.CreateRoundRectRgn.argtypes = (ctypes.c_int,) * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        root = int(self.winId())
        bounds = wintypes.RECT()
        if not user32.GetClientRect(root, ctypes.byref(bounds)):
            return
        diameter = round(18 * self.devicePixelRatioF())

        output_found = []
        def clip(hwnd, _unused):
            if hwnd != root:
                name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, name, len(name))
                if not name.value.startswith("VLC video"):
                    return True
                if name.value.startswith("VLC video output"):
                    output_found.append(hwnd)
            origin = wintypes.POINT()
            user32.MapWindowPoints(root, hwnd, ctypes.byref(origin), 1)
            client = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(client)):
                return True
            region = gdi32.CreateRoundRectRgn(origin.x, origin.y,
                origin.x + bounds.right, origin.y + bounds.bottom, diameter, diameter)
            rectangle = gdi32.CreateRectRgn(0, 0, client.right, client.bottom)
            try:
                if region and rectangle and gdi32.CombineRgn(region, region, rectangle, 1):  # RGN_AND
                    if user32.SetWindowRgn(hwnd, region, True):
                        region = None  # Ownership transfers to Windows.
            finally:
                if region:
                    gdi32.DeleteObject(region)
                if rectangle:
                    gdi32.DeleteObject(rectangle)
            return True

        if apply_root:
            clip(root, 0)
        user32.EnumChildWindows(root, callback_type(clip), 0)
        return bool(output_found)
