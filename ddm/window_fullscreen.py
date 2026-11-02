"""Windows 无过渡全屏：保持主窗口和 VLC 子窗口的 HWND 不变。"""
import ctypes
from ctypes import wintypes
import sys

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
    transition = getattr(widget, "_theme_transition", None)
    light, background, text = (getattr(transition, "_titlebar_theme", None)
                              or (theme.is_light(), theme.BG, theme.TEXT1))
    hwnd = int(widget.winId())
    background = theme.qcolor(background)
    text = theme.qcolor(text)
    colorref = lambda color: color.red() | color.green() << 8 | color.blue() << 16
    # Unsupported DWM attributes are ignored by older Windows versions.
    _dwm_set(hwnd, 20, int(not light))            # Immersive dark mode / buttons.
    _dwm_set(hwnd, 35, colorref(background))      # DWMWA_CAPTION_COLOR.
    _dwm_set(hwnd, 36, colorref(text))            # DWMWA_TEXT_COLOR.
    _dwm_set(hwnd, 34, colorref(background))      # DWMWA_BORDER_COLOR.


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
