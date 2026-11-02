"""Windows 无过渡全屏：保持主窗口和 VLC 子窗口的 HWND 不变。"""
import ctypes
from ctypes import wintypes
import sys
import struct

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from . import theme


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _dwm_get(hwnd, attribute):
    value = wintypes.DWORD()
    function = ctypes.windll.dwmapi.DwmGetWindowAttribute
    function.argtypes = (wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
    if function(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
        return value.value
    return None  # Windows 10 does not support the Windows 11 frame attributes.


def _dwm_set(hwnd, attribute, value):
    if value is not None:
        function = ctypes.windll.dwmapi.DwmSetWindowAttribute
        function.argtypes = (wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
        data = wintypes.DWORD(value)
        return function(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))


def sync_titlebar(widget) -> None:
    """Blend the native caption into the app without changing its HWND or styles."""
    if (sys.platform != "win32" or QApplication.platformName() != "windows"
            or not widget.testAttribute(Qt.WA_WState_Created)
            or getattr(widget, "_fullscreen_tile", None) is not None):
        return
    hwnd = int(widget.winId())
    transition = getattr(widget, '_theme_transition', None)
    light, background, text = (getattr(transition, '_titlebar_theme', None)
                              or (theme.is_light(), theme.BG, theme.TEXT1))
    background = theme.qcolor(background)
    text = theme.qcolor(text)
    colorref = lambda color: color.red() | color.green() << 8 | color.blue() << 16
    # Unsupported DWM attributes are ignored by older Windows versions.
    _dwm_set(hwnd, 20, int(not light))            # Immersive dark mode / buttons.
    _dwm_set(hwnd, 35, colorref(background))      # DWMWA_CAPTION_COLOR.
    _dwm_set(hwnd, 36, colorref(text))            # DWMWA_TEXT_COLOR.
    _dwm_set(hwnd, 34, colorref(background))      # DWMWA_BORDER_COLOR.


def caption_snapshot(widget):
    """Capture only the real native caption, without a desktop screenshot."""
    from PySide6.QtGui import QImage, QPixmap

    if (sys.platform != 'win32' or QApplication.platformName() != 'windows'
            or not widget.testAttribute(Qt.WA_WState_Created)):
        return QPixmap()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = (wintypes.HDC, wintypes.LPVOID, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    hwnd = int(widget.winId())
    frame, client = wintypes.RECT(), wintypes.POINT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(frame)) or not user32.ClientToScreen(hwnd, ctypes.byref(client)):
        return QPixmap()
    width, height = frame.right-frame.left, client.y-frame.top
    if height <= 0 or width <= 0:
        return QPixmap()  # Borderless/fullscreen windows have no caption.
    header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
    memory = gdi32.CreateCompatibleDC(None)
    if not memory:
        return QPixmap()
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(None, header, 0, ctypes.byref(bits), None, 0)
    if not bitmap:
        gdi32.DeleteDC(memory)
        return QPixmap()
    previous = gdi32.SelectObject(memory, bitmap)
    try:
        # PW_RENDERFULLCONTENT copies DWM's caption, unlike legacy WM_PRINT.
        # The destination has caption height only; no video pixels are copied.
        if not user32.PrintWindow(hwnd, memory, 2):
            return QPixmap()
        gdi32.GdiFlush()
        scale = widget.devicePixelRatioF()
        image = QImage(ctypes.string_at(bits, width*height*4), width, height,
                       width*4, QImage.Format_RGB32).copy(client.x-frame.left, 0,
                       round(widget.width()*scale), height)
        image.setDevicePixelRatio(scale)
        return QPixmap.fromImage(image)
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)


def enter(widget) -> tuple[int, int, tuple[int, int, int, int], tuple[int | None, int | None]]:
    user32 = ctypes.windll.user32
    user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo))
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)

    hwnd = int(widget.winId())
    style = user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
    original = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(original))
    monitor = _MonitorInfo()
    monitor.cbSize = ctypes.sizeof(monitor)
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor))
    area = monitor.rcMonitor
    frame = (_dwm_get(hwnd, 33), _dwm_get(hwnd, 34))
    if frame[0] is not None:
        _dwm_set(hwnd, 33, 1)  # DWMWA_WINDOW_CORNER_PREFERENCE: DONOTROUND
    if frame[1] is not None:
        _dwm_set(hwnd, 34, 0xFFFFFFFE)  # DWMWA_BORDER_COLOR: COLOR_NONE
    user32.SetWindowLongW(hwnd, -16, (style & ~0x00CF0000) | 0x80000000)
    user32.SetWindowPos(hwnd, None, area.left, area.top,
                        area.right - area.left, area.bottom - area.top, 0x0020 | 0x0004)
    return hwnd, style, (original.left, original.top, original.right, original.bottom), frame


def exit(widget, state: tuple[int, int, tuple[int, int, int, int], tuple[int | None, int | None]]) -> None:
    user32 = ctypes.windll.user32
    hwnd, style, (left, top, right, bottom), frame = state
    user32.SetWindowLongW(hwnd, -16, style)
    user32.SetWindowPos(hwnd, None, left, top, right - left, bottom - top,
                        0x0020 | 0x0004)
    _dwm_set(hwnd, 33, frame[0])
    _dwm_set(hwnd, 34, frame[1])
