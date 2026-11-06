"""Read-only drag hit testing without masking the input-transparent ghost."""
import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QWidget

_user32 = None
if sys.platform == 'win32':
    _user32 = ctypes.WinDLL('user32')
    _user32.GetDesktopWindow.restype = wintypes.HWND
    _user32.ChildWindowFromPointEx.argtypes = (wintypes.HWND, wintypes.POINT, wintypes.UINT)
    _user32.ChildWindowFromPointEx.restype = wintypes.HWND


def widget_at(position):
    if _user32 is None or QApplication.platformName() != 'windows':
        return QApplication.widgetAt(position)
    screen = QApplication.screenAt(position)
    if screen is None:
        return QApplication.widgetAt(position)
    # Windows screen origins stay in physical pixels; only the offset is scaled.
    origin = screen.geometry().topLeft()
    native = (QPointF(origin) + QPointF(position - origin) * screen.devicePixelRatio()).toPoint()
    desktop = _user32.GetDesktopWindow()
    # CWP_SKIPINVISIBLE | CWP_SKIPTRANSPARENT excludes the ghost without changing it.
    handle = _user32.ChildWindowFromPointEx(desktop, wintypes.POINT(native.x(), native.y()), 0x5)
    if not handle or handle == desktop:
        return None
    window = QWidget.find(handle)
    if window is None:
        return None  # Another application's window occludes our drop targets.
    if window.testAttribute(Qt.WA_TransparentForMouseEvents):
        return QApplication.widgetAt(position)
    return window.childAt(window.mapFromGlobal(position)) or window
