"""Offline regression for fullscreen tile borders in both themes."""
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionFrame

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme
from ddm.widgets import WallGrid


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


def main():
    app = QApplication(sys.argv)
    for mode in ("dark", "light"):
        theme.apply(mode)
        wall = WallGrid([{}, {}], "main2")
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
