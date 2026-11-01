"""Defer native DPI scaling only while a Windows title-bar move is active."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication


class DpiDragGuard(QAbstractNativeEventFilter):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.hwnd = int(window.winId())
        self.pending = None
        self.children = {}
        self.active = True
        self.user32 = ctypes.windll.user32
        self.user32.IsChild.argtypes = (wintypes.HWND, wintypes.HWND)
        self.user32.IsWindow.argtypes = (wintypes.HWND,)
        self.user32.IsZoomed.argtypes = (wintypes.HWND,)
        self.user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM)
        self.user32.SendMessageW.restype = ctypes.c_ssize_t
        QApplication.instance().installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message not in (0x02E0, 0x02E3):
            return False, 0
        if msg.message == 0x02E0 and msg.hWnd == self.hwnd and msg.lParam:
            rect = wintypes.RECT.from_address(msg.lParam)
            self.pending = (int(msg.wParam), rect.right-rect.left, rect.bottom-rect.top)
            self.window._begin_display_transition()
            return True, 0
        if msg.message == 0x02E3 and self.user32.IsChild(self.hwnd, msg.hWnd):
            # PMv2 sends these top-down even if the parent's DPI message was held.
            self.children[int(msg.hWnd)] = None
            return True, 0
        return False, 0

    def finish(self):
        if not self.active:
            return
        self.active = False
        QApplication.instance().removeNativeEventFilter(self)
        pending, self.pending = self.pending, None
        children, self.children = self.children, {}
        if pending is not None:
            dpi, width, height = pending
            rect = wintypes.RECT()
            if self.user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
                # The old suggested position is stale after further mouse movement.
                if not self.user32.IsZoomed(self.hwnd):
                    rect.right, rect.bottom = rect.left+width, rect.top+height
                self.user32.SendMessageW(self.hwnd, 0x02E0, dpi, ctypes.addressof(rect))
        for hwnd in children:
            if self.user32.IsWindow(hwnd) and self.user32.IsChild(self.hwnd, hwnd):
                self.user32.SendMessageW(hwnd, 0x02E3, 0, 0)
