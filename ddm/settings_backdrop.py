"""Windows system material for the settings shell; no desktop capture."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtWidgets import QApplication


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]


def apply_backdrop(widget, light):
    if (sys.platform != 'win32' or QApplication.platformName() != 'windows'
            or sys.getwindowsversion().build < 22621):
        return False
    from .window_fullscreen import _dwm_set
    hwnd = int(widget.winId())
    _dwm_set(hwnd, 20, int(not light))
    if getattr(widget, '_backdrop_hwnd', None) == hwnd:
        return True
    function = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
    function.argtypes = (wintypes.HWND, ctypes.POINTER(_Margins))
    margins = _Margins(-1, -1, -1, -1)
    _dwm_set(hwnd, 33, 2)  # DWMWCP_ROUND.
    _dwm_set(hwnd, 34, 0xFFFFFFFE)  # COLOR_NONE: no second native frame outline.
    extended = function(hwnd, ctypes.byref(margins)) == 0
    # DWMSBT_TRANSIENTWINDOW: Desktop Acrylic across the whole window.
    enabled = _dwm_set(hwnd, 38, 3) == 0 and extended
    if enabled:
        widget._backdrop_hwnd = hwnd
    return enabled


def align_embedded_content(container, foreign):
    """Reconcile a layered host's first show with the worker-owned viewport."""
    if sys.platform != 'win32' or QApplication.platformName() != 'windows':
        return
    from PySide6.QtCore import QPoint
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = (wintypes.HWND,)
    user32.GetParent.restype = wintypes.HWND
    user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT)
    window = container.window()
    origin = wintypes.POINT()
    user32.ClientToScreen(int(window.winId()), ctypes.byref(origin))
    offset = container.mapTo(window, QPoint())
    scale = window.devicePixelRatioF()
    point = wintypes.POINT(origin.x + round(offset.x() * scale), origin.y + round(offset.y() * scale))
    hwnd = int(foreign.winId())
    user32.ScreenToClient(user32.GetParent(hwnd), ctypes.byref(point))
    user32.SetWindowPos(hwnd, None, point.x, point.y, round(container.width() * scale),
                        round(container.height() * scale), 0x14)  # No activation or z-order change.
