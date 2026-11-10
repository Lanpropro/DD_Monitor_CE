"""Native settings corners and caption colours, without a system backdrop."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtWidgets import QApplication


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]


def apply_frame(widget, light):
    if (sys.platform != 'win32' or QApplication.platformName() != 'windows'
            or sys.getwindowsversion().build < 22621):
        return False
    from .window_fullscreen import _dwm_set
    hwnd = int(widget.winId())
    _dwm_set(hwnd, 20, int(not light))
    if getattr(widget, '_frame_hwnd', None) == hwnd:
        return widget._native_corners
    function = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea
    function.argtypes = (wintypes.HWND, ctypes.POINTER(_Margins))
    margins = _Margins(0, 0, 0, 0)
    widget._native_corners = _dwm_set(hwnd, 33, 2) == 0  # DWMWCP_ROUND.
    _dwm_set(hwnd, 34, 0xFFFFFFFE)  # COLOR_NONE: no second native frame outline.
    extended = function(hwnd, ctypes.byref(margins)) == 0
    applied = _dwm_set(hwnd, 38, 1) == 0 and extended  # DWMSBT_NONE.
    if applied:
        widget._frame_hwnd = hwnd
    return widget._native_corners
