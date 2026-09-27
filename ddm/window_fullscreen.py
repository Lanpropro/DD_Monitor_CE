"""Windows 无过渡全屏：保持主窗口和 VLC 子窗口的 HWND 不变。"""
import ctypes
from ctypes import wintypes


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class _WindowPlacement(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", wintypes.RECT)]


def orient_restore_geometry(widget, portrait: bool) -> None:
    """Keep a maximized window's restore rectangle in its current orientation."""
    user32 = ctypes.windll.user32
    user32.GetWindowPlacement.argtypes = (wintypes.HWND, ctypes.POINTER(_WindowPlacement))
    user32.SetWindowPlacement.argtypes = (wintypes.HWND, ctypes.POINTER(_WindowPlacement))
    user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo))

    hwnd = int(widget.winId())
    placement = _WindowPlacement()
    placement.length = ctypes.sizeof(placement)
    if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)) or placement.showCmd != 3:
        return
    old = placement.rcNormalPosition
    old_width, old_height = old.right - old.left, old.bottom - old.top
    if (old_width <= old_height * 0.9) == portrait:
        return

    monitor = _MonitorInfo()
    monitor.cbSize = ctypes.sizeof(monitor)
    if not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor)):
        return
    work = monitor.rcWork
    work_width, work_height = work.right - work.left, work.bottom - work.top
    if portrait:
        height = min(max(old_width, old_height), work_height)
        width = min(work_width, int(height * 9 / 16))
        height = min(height, int(width * 16 / 9))
    else:
        width = min(max(old_width, old_height), work_width)
        height = min(work_height, int(width * 9 / 16))
        width = min(width, int(height * 16 / 9))
    left = work.left + (work_width - width) // 2
    top = work.top + (work_height - height) // 2
    placement.rcNormalPosition = wintypes.RECT(left, top, left + width, top + height)
    user32.SetWindowPlacement(hwnd, ctypes.byref(placement))


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
