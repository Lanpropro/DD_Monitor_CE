"""Native settings corners and compositor blur of the content behind the HWND."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication


class _Margins(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('left', 'right', 'top', 'bottom')]


class _AccentPolicy(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in ('state', 'flags', 'color', 'animation')]


class _CompositionData(ctypes.Structure):
    _fields_ = [('attribute', ctypes.c_int), ('data', ctypes.c_void_p), ('size', ctypes.c_size_t)]


def blur_available():
    return (sys.platform == 'win32' and QApplication.platformName() == 'windows'
            and hasattr(ctypes.windll.user32, 'SetWindowCompositionAttribute'))


def apply_blur(widget, enabled):
    """Leave flags, HWND ownership and the Qt layered-window surface unchanged."""
    if not blur_available():
        return False
    hwnd = int(widget.winId())
    state = (hwnd, bool(enabled))
    if getattr(widget, '_blur_state', None) == state:
        return bool(enabled)
    # WCA_ACCENT_POLICY / ACCENT_ENABLE_BLURBEHIND. DWM's system backdrop
    # (DWMSBT_TRANSIENTWINDOW) does not render behind Qt's layered surface.
    policy = _AccentPolicy(3 if enabled else 0, 0, 0, 0)
    data = _CompositionData(19, ctypes.addressof(policy), ctypes.sizeof(policy))
    function = ctypes.windll.user32.SetWindowCompositionAttribute
    function.argtypes = (wintypes.HWND, ctypes.POINTER(_CompositionData))
    function.restype = wintypes.BOOL
    if not function(hwnd, ctypes.byref(data)):
        return False
    widget._blur_state = state
    return bool(enabled)


def set_blur_clip(widget, path):
    """Clip the compositor in device pixels without masking Qt's backing store."""
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN, wintypes.BOOL)
    user32.SetWindowRgn.restype = ctypes.c_int
    hwnd = int(widget.winId())
    if path is None:
        return bool(user32.SetWindowRgn(hwnd, None, True))
    scale = widget.devicePixelRatioF()
    polygon = QTransform.fromScale(scale, scale).map(path).toFillPolygon().toPolygon()
    points = (wintypes.POINT * polygon.size())(*(wintypes.POINT(p.x(), p.y()) for p in polygon))
    gdi32.CreatePolygonRgn.argtypes = (ctypes.POINTER(wintypes.POINT), ctypes.c_int, ctypes.c_int)
    gdi32.CreatePolygonRgn.restype = wintypes.HRGN
    region = gdi32.CreatePolygonRgn(points, len(points), 2)  # WINDING
    if not region:
        return False
    if user32.SetWindowRgn(hwnd, region, True):
        return True
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    gdi32.DeleteObject(region)
    return False


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
