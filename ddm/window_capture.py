"""Capture a specific Windows window into a memory-only Qt image."""
import ctypes
from ctypes import wintypes
import struct

from PySide6.QtGui import QImage


def print_window(hwnd, width, height, *, client_only=False):
    if width <= 0 or height <= 0:
        return QImage()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = (wintypes.HDC, wintypes.LPVOID, wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
    memory = gdi32.CreateCompatibleDC(None)
    if not memory:
        return QImage()
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(None, header, 0, ctypes.byref(bits), None, 0)
    if not bitmap:
        gdi32.DeleteDC(memory)
        return QImage()
    previous = gdi32.SelectObject(memory, bitmap)
    try:
        # PW_RENDERFULLCONTENT includes the DWM composition, including thumbnails.
        if not user32.PrintWindow(hwnd, memory, 3 if client_only else 2):
            return QImage()
        gdi32.GdiFlush()
        return QImage(ctypes.string_at(bits, width*height*4), width, height,
                      width*4, QImage.Format_RGB32).copy()
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
