"""Windows system material for the settings shell; no desktop capture."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtWidgets import QApplication


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]


def apply_backdrop(widget, light, enabled=True):
    if (sys.platform != 'win32' or QApplication.platformName() != 'windows'
            or sys.getwindowsversion().build < 22621):
        return False
    from .window_fullscreen import _dwm_set
    hwnd = int(widget.winId())
    _dwm_set(hwnd, 20, int(not light))
    key = (hwnd, enabled)
    if getattr(widget, '_backdrop_key', None) == key:
        return enabled
    function = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
    function.argtypes = (wintypes.HWND, ctypes.POINTER(_Margins))
    margins = _Margins(*([-1 if enabled else 0] * 4))
    widget._native_corners = _dwm_set(hwnd, 33, 2) == 0  # DWMWCP_ROUND.
    _dwm_set(hwnd, 34, 0xFFFFFFFE)  # COLOR_NONE: no second native frame outline.
    extended = function(hwnd, ctypes.byref(margins)) == 0
    # DWMSBT_TRANSIENTWINDOW: Desktop Acrylic across the whole window.
    applied = _dwm_set(hwnd, 38, 3 if enabled else 1) == 0 and extended
    if applied:
        widget._backdrop_key = key
    return applied and enabled
