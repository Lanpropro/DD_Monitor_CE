"""Windows 无过渡全屏：保持主窗口和 VLC 子窗口的 HWND 不变。"""
import ctypes
from ctypes import wintypes


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def enter(widget) -> tuple[int, int, tuple[int, int, int, int]]:
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
    user32.SetWindowLongW(hwnd, -16, (style & ~0x00CF0000) | 0x80000000)
    user32.SetWindowPos(hwnd, None, area.left, area.top,
                        area.right - area.left, area.bottom - area.top, 0x0020 | 0x0004)
    return hwnd, style, (original.left, original.top, original.right, original.bottom)


def exit(widget, state: tuple[int, int, tuple[int, int, int, int]]) -> None:
    user32 = ctypes.windll.user32
    hwnd, style, (left, top, right, bottom) = state
    user32.SetWindowLongW(hwnd, -16, style)
    user32.SetWindowPos(hwnd, None, left, top, right - left, bottom - top,
                        0x0020 | 0x0004)
