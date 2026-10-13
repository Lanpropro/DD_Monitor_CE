"""Native output growth must not retain its initial small clipping region."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
from PySide6.QtCore import Qt
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication
from ddm.video_surface import VideoSurface


def main():
    app = QApplication([])
    assert app.platformName() == "windows", "Windows native test required"
    surface = VideoSurface()
    surface.setAttribute(Qt.WA_NativeWindow)
    surface.setAttribute(Qt.WA_ShowWithoutActivating)
    surface.resize(800, 500)
    surface.move(-10000, -10000)
    surface.show()
    app.processEvents()
    surface.setMask(QRegion(surface.rect()))
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR,
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
        wintypes.HINSTANCE, wintypes.LPVOID)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
    user32.DestroyWindow.argtypes = (wintypes.HWND,)
    gdi32.CreateRectRgn.restype = wintypes.HANDLE
    gdi32.PtInRegion.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    root = int(surface.winId())
    bounds = wintypes.RECT()
    user32.GetClientRect(root, ctypes.byref(bounds))
    width, height = bounds.right, bounds.bottom
    child = user32.CreateWindowExW(0, "STATIC", "Output test", 0x50000000,
        0, 0, width // 2, height // 2, root, None, None, None)
    assert child
    original_name = user32.GetClassNameW

    def class_name(hwnd, buffer, length):
        if hwnd == child:
            buffer.value = "VLC video output"
            return len(buffer.value)
        return original_name(hwnd, buffer, length)

    def contains(x, y):
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            assert user32.GetWindowRgn(child, region)
            return bool(gdi32.PtInRegion(region, x, y))
        finally:
            gdi32.DeleteObject(region)

    try:
        with patch.object(user32, "GetClassNameW", side_effect=class_name):
            surface.refresh_clip()
            surface._retry_clip()
            assert not surface._clip_timer.isActive(), "Output found: no ongoing polling"
            # VLC expands asynchronously after output creation, without Qt resizing.
            assert user32.SetWindowPos(child, None, 0, 0, width, height, 0x0014)
            assert contains(width * 3 // 4, height * 3 // 4), "Initial clip truncates grown output"
            assert not contains(0, 0), "Rounded corner must remain clipped"
            assert not contains(width, height), "Output must stay inside video surface"
            # Parent layout resize still updates the output boundary.
            surface.resize(600, 400)
            app.processEvents()
            surface.setMask(QRegion(surface.rect()))
            surface._retry_clip()
            user32.GetClientRect(root, ctypes.byref(bounds))
            assert contains(bounds.right // 2, bounds.bottom // 2)
            assert not contains(bounds.right + 10, bounds.bottom // 2)
        print("PASS: native output growth, rounded corners and parent resize")
    finally:
        user32.DestroyWindow(child)
        surface.close()


if __name__ == "__main__":
    main()
