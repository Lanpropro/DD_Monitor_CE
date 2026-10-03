"""Native control masks use physical pixels without rectangular backing."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ddm import theme
from ddm.widgets import Tile


def main():
    app = QApplication(sys.argv)
    if os.name != "nt" or app.platformName() != "windows":
        print("Skipped: requires Windows native window masks")
        return
    app.setStyleSheet(theme.qss())
    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
    gdi32.CreateRectRgn.restype = wintypes.HANDLE
    gdi32.CreateRoundRectRgn.argtypes = (ctypes.c_int,) * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
    gdi32.EqualRgn.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    gdi32.PtInRegion.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
    user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
    tile = Tile({"room_id": "1", "uname": "Test", "quality": 10000})
    tile.show()
    try:
        for width, label in ((800, "原画"), (320, "超清"), (600, "蓝光20M")):
            tile.resize(width, 300)
            tile.quality_button.setText(label)
            tile.set_controls_visible(True)
            app.processEvents()
            tile._refresh_overlay_masks()
            scale = tile.controls.devicePixelRatioF()
            actual = gdi32.CreateRectRgn(0, 0, 0, 0)
            expected = gdi32.CreateRectRgn(0, 0, 0, 0)
            try:
                assert user32.GetWindowRgn(int(tile.controls.winId()), actual) > 0
                for button in (tile.quality_button, tile.reload_button, tile.close_button):
                    rect = button.geometry()
                    diameter = round(rect.height() * scale)
                    part = gdi32.CreateRoundRectRgn(
                        round(rect.x() * scale), round(rect.y() * scale),
                        round((rect.x() + rect.width()) * scale),
                        round((rect.y() + rect.height()) * scale), diameter, diameter)
                    try:
                        gdi32.CombineRgn(expected, expected, part, 2)
                    finally:
                        gdi32.DeleteObject(part)
                    assert gdi32.PtInRegion(actual, round(rect.center().x() * scale),
                                           round(rect.center().y() * scale))
                    assert not gdi32.PtInRegion(actual, round((rect.x() + 1) * scale),
                                               round((rect.y() + 1) * scale))
                    gap_x = round((rect.x() + rect.width() + 2) * scale)
                    assert not gdi32.PtInRegion(actual, gap_x, diameter // 2)
                assert gdi32.EqualRgn(actual, expected), "Logical-pixel rounding still scales edge steps"
            finally:
                gdi32.DeleteObject(actual)
                gdi32.DeleteObject(expected)
            print(f"Physical control edges, corners and gaps passed at {scale * 100:g}% ({label})")
    finally:
        tile.close()


if __name__ == "__main__":
    main()
