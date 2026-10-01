"""Windows regression: control masks must follow monitor DPI changes."""
import ctypes
import os
import sys
import time

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ddm import theme
from ddm.widgets import Tile


def settle(app):
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    screens = sorted(app.screens(), key=lambda screen: screen.devicePixelRatio())
    if os.name != "nt" or len({s.devicePixelRatio() for s in screens}) < 2:
        print("Skipped: requires Windows monitors with different DPI scales")
        return
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    gdi32.CreateRectRgn.restype = ctypes.c_void_p
    user32.GetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.PtInRegion.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    region = gdi32.CreateRectRgn(0, 0, 0, 0)
    tile = Tile({"room_id": "1", "quality": 10000})
    tile.set_uname_title("测试主播", "跨屏后保留完整标题文字")
    tile.set_live(True)
    tile.set_watched("12345")
    try:
        for screen in (screens[0], screens[-1], screens[0], screens[-1]):
            tile.move(screen.geometry().topLeft() + QPoint(30, 100))
            tile.resize(320, 500) if screen.geometry().height() > screen.geometry().width() \
                else tile.resize(600, 300)
            tile.show()
            tile.set_controls_visible(True)
            settle(app)
            scale = tile.controls.devicePixelRatioF()
            assert abs(scale - screen.devicePixelRatio()) < 0.01
            assert user32.GetWindowRgn(int(tile.controls.winId()), region) > 0
            for button in (tile.quality_button, tile.reload_button, tile.close_button):
                for x in (button.width() // 2, button.width() - 3):
                    point = button.pos() + QPoint(x, button.height() // 2)
                    assert gdi32.PtInRegion(region, round(point.x() * scale),
                                           round(point.y() * scale)), \
                        f"DPI {scale}: native mask clips {button.text() or 'refresh'}"
            for badge in (tile.stream_badge, tile.title_badge):
                # Keep the same text and logical size between monitors; this is
                # the case that previously left a stale Windows window region.
                assert user32.GetWindowRgn(int(badge.winId()), region) > 0
                assert gdi32.PtInRegion(region, round((badge.width() - 5) * scale),
                                       round(badge.height() / 2 * scale)), \
                    f"DPI {scale}: native mask clips badge text"
            print(f"Native control mask correct at {scale * 100:g}%")
    finally:
        gdi32.DeleteObject(region)
        tile.close()


if __name__ == "__main__":
    main()
