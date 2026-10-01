"""Check that native control masks preserve the stylesheet's antialiased edges."""
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ddm import theme
from ddm.widgets import Tile


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    tile = Tile({"room_id": "1", "uname": "test", "quality": 10000})
    tile.resize(420, 260)
    tile._layout_controls()
    for button in (tile.quality_button, tile.reload_button):
        assert not tile.controls.mask().contains(
            button.pos() + QPoint(button.width() + 2, button.height() // 2)
        ), "Mask fills the gap between controls"
    for button in (tile.quality_button, tile.reload_button, tile.close_button):
        button.setProperty("hovered", True)
        button.style().unpolish(button)
        button.style().polish(button)
        pixmap = button.grab()
        scale = pixmap.devicePixelRatioF()
        image = QImage(pixmap.size(), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        button.render(painter, QPoint(), QRegion(), QWidget.DrawChildren)
        painter.end()
        clipped = []
        cyan_pixels = 0
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                # Cyan background and its partially covered edge pixels.
                if (color.alpha() > 20 and color.green() > 50
                        and color.blue() > 70 and color.red() < 70):
                    cyan_pixels += 1
                    point = button.pos()
                    point.setX(point.x() + int(x / scale))
                    point.setY(point.y() + int(y / scale))
                    if not tile.controls.mask().contains(point):
                        clipped.append((x, y))
        assert cyan_pixels > 100, "Hover background was not rendered"
        assert not clipped, f"{button.text() or 'refresh'}: clipped hover pixels {clipped[:12]}"
    print("Control hover edges preserved")
    tile.close()


if __name__ == "__main__":
    main()
