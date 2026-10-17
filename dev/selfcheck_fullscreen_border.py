"""Offline regression for fullscreen tile borders in both themes."""
import os
import sys
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionFrame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme
from ddm.widgets import WallGrid
from ddm import window_fullscreen


def border_width(tile):
    option = QStyleOptionFrame()
    option.initFrom(tile)
    return tile.style().pixelMetric(QStyle.PixelMetric.PM_DefaultFrameWidth, option, tile)


def check_video_mask(tile, fullscreen):
    assert tile.video.square_corners is fullscreen
    region = tile.video.mask()
    assert region.contains(QPoint(0, 0)) is fullscreen
    assert region.contains(tile.video.rect().center())
    assert tile.video_danmaku.mask() == region
    assert tile.video.x() == (0 if fullscreen else 1)
    assert tile.video.width() == tile.width() - (0 if fullscreen else 2)
    assert tile.bottom.x() == (0 if fullscreen else 1)
    assert tile.bottom.width() == tile.width() - (0 if fullscreen else 2)


def check_native_frame(app):
    if app.platformName() != 'windows':
        return
    # A hidden native window verifies monitor bounds without covering the desktop.
    from PySide6.QtWidgets import QWidget
    window = QWidget()
    window.resize(900, 600)
    hwnd = int(window.winId())
    original = (window_fullscreen._dwm_get(hwnd, 33), window_fullscreen._dwm_get(hwnd, 34))
    state = window_fullscreen.enter(window)
    try:
        if original[0] is not None:
            assert window_fullscreen._dwm_get(hwnd, 33) == 1
        if original[1] is not None:
            assert window_fullscreen._dwm_get(hwnd, 34) == 0xFFFFFFFE
        user32 = ctypes.windll.user32
        bounds = wintypes.RECT()
        user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        assert user32.GetClientRect(hwnd, ctypes.byref(bounds))
        monitor = window_fullscreen._MonitorInfo()
        monitor.cbSize = ctypes.sizeof(monitor)
        assert user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor))
        assert bounds.right == monitor.rcMonitor.right - monitor.rcMonitor.left
        assert bounds.bottom == monitor.rcMonitor.bottom - monitor.rcMonitor.top
    finally:
        window_fullscreen.exit(window, state)
    assert (window_fullscreen._dwm_get(hwnd, 33), window_fullscreen._dwm_get(hwnd, 34)) == original
    window.close()


def main():
    app = QApplication(sys.argv)
    check_native_frame(app)
    for mode in ("dark", "light"):
        theme.apply(mode)
        wall = WallGrid([{}, {}], "main2")
        wall.setAttribute(Qt.WA_ShowWithoutActivating)
        wall.move(-10000, -10000)
        wall.resize(1000, 700)
        wall.show()
        app.processEvents()
        target, other = wall.tiles[:2]
        target.set_focused(True)
        normal_width = border_width(target)
        assert normal_width > 0
        check_video_mask(target, False)
        for _ in range(3):
            wall.set_fullscreen_tile(target)
            target.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
            target.set_focused(True)
            app.processEvents()
            assert target.property("focused") is True
            assert border_width(target) == 0, mode
            check_video_mask(target, True)
            wall.set_fullscreen_tile(None)
            app.processEvents()
            assert target.property("focused") is True
            assert border_width(target) == normal_width, mode
            check_video_mask(target, False)
        wall.set_fullscreen_tile(target)
        wall.set_fullscreen_tile(other)
        assert target.property("fullscreen") is False
        assert border_width(target) == normal_width
        assert border_width(other) == 0
        check_video_mask(target, False)
        check_video_mask(other, True)
        theme.apply("light" if mode == "dark" else "dark")
        app.processEvents()
        assert border_width(other) == 0
        check_video_mask(other, True)
        wall.set_fullscreen_tile(None)
        assert border_width(other) > 0
        check_video_mask(other, False)
        wall.close()
    print("PASS: fullscreen borders, hover, focus, repeated transitions, tile and theme changes")


if __name__ == "__main__":
    main()
