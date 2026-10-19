"""Offline native mask deduplication, invalidation and renderer recovery checks."""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QApplication

from ddm.video_surface import VideoSurface


def main():
    app = QApplication([])
    assert sys.platform == "win32" and app.platformName() == "windows"
    surface = VideoSurface()
    surface.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    surface.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    surface.resize(800, 500)
    surface.move(-10000, -10000)
    surface.show()
    app.processEvents()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = (wintypes.HWND,)
    user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
    user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
    gdi32.CreateRectRgn.restype = wintypes.HANDLE
    gdi32.GetRgnBox.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.RECT))
    gdi32.PtInRegion.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    root = int(surface.winId())
    children = []
    original_name = user32.GetClassNameW

    def create_child():
        child = user32.CreateWindowExW(
            0, "STATIC", "Offline mpv stand-in", 0x50000000,
            0, 0, 800, 500, root, None, None, None)
        assert child
        children.append(child)
        return child

    def class_name(hwnd, buffer, length):
        if hwnd in children:
            buffer.value = "mpv"
            return len(buffer.value)
        return original_name(hwnd, buffer, length)

    def region_width(hwnd):
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            if not user32.GetWindowRgn(hwnd, region):
                return 0
            bounds = wintypes.RECT()
            assert gdi32.GetRgnBox(region, ctypes.byref(bounds))
            assert not gdi32.PtInRegion(region, 0, 0)
            assert gdi32.PtInRegion(region, bounds.right // 2, bounds.bottom // 2)
            return bounds.right - bounds.left
        finally:
            gdi32.DeleteObject(region)

    path = QPainterPath()
    path.addRoundedRect(QRectF(surface.rect()), 9, 9)
    mask = QRegion(path.toFillPolygon().toPolygon())
    try:
        with patch.object(user32, "GetClassNameW", side_effect=class_name):
            child = create_child()
            with patch.object(user32, "EnumChildWindows", wraps=user32.EnumChildWindows) as enum:
                surface.setMask(mask)
                assert enum.call_count == 1
                surface._retry_clip()
                assert surface._clip_timer.interval() == 500
                count = enum.call_count
                surface._clip_attempts = 7
                with patch.object(surface._clip_timer, "start", wraps=surface._clip_timer.start) as start:
                    for _ in range(100):
                        surface.setMask(QRegion(mask))
                    assert enum.call_count == count, "Same mask enumerates native windows twice"
                    assert not start.called, "Duplicate masks restart the timer"
                assert surface._clip_attempts == 7
                assert surface._clip_timer.interval() == 500

                smaller = mask.intersected(QRegion(0, 0, 600, 400))
                surface.setMask(smaller)
                assert enum.call_count == count + 1, "Changed mask was not clipped immediately"
                assert region_width(child) == round(600 * surface.devicePixelRatioF())
                surface.setMask(mask)
                count = enum.call_count
                width = region_width(child)
                with patch.object(surface, "devicePixelRatioF", return_value=surface.devicePixelRatioF() * 2):
                    surface.setMask(mask)
                    assert enum.call_count == count + 1, "DPI change did not invalidate mask"
                    assert region_width(child) == width * 2
                surface.setMask(mask)
                assert region_width(child) == width

                surface.clearMask()
                count = enum.call_count
                surface.setMask(mask)
                assert enum.call_count == count + 1, "clearMask did not invalidate mask"
                for event_type in (QEvent.Type.WinIdChange, QEvent.Type.DevicePixelRatioChange,
                                   QEvent.Type.Show):
                    count = enum.call_count
                    QApplication.sendEvent(surface, QEvent(event_type))
                    assert enum.call_count > count, f"{event_type} did not clip immediately"
                    count = enum.call_count
                    surface.setMask(mask)
                    assert enum.call_count == count + 1

                with patch.object(surface, "internalWinId", return_value=root + 1):
                    count = enum.call_count
                    surface.setMask(mask)
                    assert enum.call_count == count + 1, "Native root change reused stale state"
                surface.setMask(mask)
                for size in ((720, 430), (640, 360), (800, 500)):
                    count = enum.call_count
                    surface.resize(*size)
                    assert enum.call_count == count, "Resize clipped the old mask"
                    assert surface._mask_clip_state is None
                    assert surface._clip_timer.isActive(), "Resize lost timer fallback"
                    resized_path = QPainterPath()
                    resized_path.addRoundedRect(QRectF(surface.rect()), 9, 9)
                    resized_mask = QRegion(resized_path.toFillPolygon().toPolygon())
                    surface.setMask(resized_mask)
                    assert enum.call_count == count + 1, "Committed size must enumerate exactly once"
                    assert region_width(child) == round(size[0] * surface.devicePixelRatioF())
                    surface.setMask(QRegion(resized_mask))
                    assert enum.call_count == count + 1, "Repeated committed mask enumerates again"

                count = enum.call_count
                surface.resize(700, 400)
                assert enum.call_count == count
                surface.setMask(mask)
                assert enum.call_count == count + 1, "Geometry change reused stale state"
                count = enum.call_count
                surface.resize(680, 380)
                assert enum.call_count == count
                surface._retry_clip()
                assert enum.call_count == count + 1, "Resize without setMask lost timer fallback"
                assert surface._clip_timer.interval() == 500

            replacement = create_child()
            surface.setMask(mask)
            assert region_width(replacement), "Child creation did not invalidate mask"
            user32.DestroyWindow(child)
            children.remove(child)
            # Missed parent notifications must still be repaired by the guard.
            with patch.object(surface, "refresh_clip"):
                unannounced = create_child()
            assert not region_width(unannounced)
            surface.setMask(mask)
            assert not region_width(unannounced), "Duplicate unexpectedly bypassed the guard test"
            surface._retry_clip()
            assert region_width(unannounced)
            assert user32.SetWindowRgn(replacement, None, False)
            assert user32.SetWindowRgn(root, None, False)
            deadline = time.monotonic() + 2
            while not (region_width(replacement) and region_width(root)):
                assert time.monotonic() < deadline, "500ms guard did not recover renderer reset"
                app.processEvents()
                time.sleep(.01)

            with patch.object(surface, "_clip_native_video", return_value=False):
                surface.refresh_clip()
                surface.setMask(mask)
                for _ in range(300):
                    surface.setMask(mask)
                    surface._retry_clip()
                assert not surface._clip_timer.isActive(), "Duplicate masks defeat bounded retries"
                surface.setMask(mask)
                assert not surface._clip_timer.isActive()
            surface.hide()
            surface.show()
            app.processEvents()
            assert surface._clip_timer.isActive()
        print("PASS: one clip per committed resize, duplicate masks, DPI/clear/root/events, replacement, guard and bounded retries")
    finally:
        for child in children:
            user32.DestroyWindow(child)
        surface.close()


if __name__ == "__main__":
    main()
