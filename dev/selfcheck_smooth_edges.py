"""Rounded selection cutouts and native loading pills retain subpixel alpha."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.widgets import LoadingIndicator, SelectionNotchEffect

APP = QApplication.instance() or QApplication([])


def canvas(width, height, scale):
    image = QImage(round(width * scale), round(height * scale), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    return image


class SmoothEdges(unittest.TestCase):
    def test_selection_notch_is_circular_and_has_fractional_alpha_at_each_scale(self):
        card = QWidget()
        card.resize(200, 100)
        effect = SelectionNotchEffect(card)
        try:
            for scale in (1, 1.25, 1.75, 2):
                with self.subTest(scale=scale):
                    source = canvas(200, 100, scale)
                    source.fill(Qt.red)
                    output = canvas(200, 100, scale)
                    with patch.object(effect, 'sourcePixmap', return_value=QPixmap.fromImage(source)):
                        painter = QPainter(output)
                        effect.draw(painter)
                        painter.end()
                    self.assertEqual(output.pixelColor(round(188 * scale), round(50 * scale)).alpha(), 0)
                    self.assertEqual(output.pixelColor(round(167 * scale), round(50 * scale)).alpha(), 255)
                    fringe = [output.pixelColor(x, y).alpha()
                              for y in range(round(31 * scale), round(69 * scale))
                              for x in range(round(169 * scale), output.width())]
                    self.assertGreater(sum(0 < alpha < 255 for alpha in fringe), 15)
                    # Three radial samples inside the circle must all be transparent.
                    for x, y in ((188, 34), (172, 50), (188, 66)):
                        self.assertEqual(output.pixelColor(round(x * scale), round(y * scale)).alpha(), 0)
        finally:
            card.deleteLater()

    def test_loading_and_refresh_pills_have_smooth_caps_in_both_themes(self):
        try:
            for mode in ('dark', 'light'):
                theme.apply(mode)
                APP.setStyleSheet(theme.qss())
                for icon, text in ((True, 'Buffering'), (False, 'Refreshing')):
                    indicator = LoadingIndicator(text=text, icon=icon)
                    try:
                        indicator.ensurePolished()
                        indicator.adjustSize()
                        indicator.layout().activate()
                        indicator._apply_mask()
                        self.assertTrue(indicator.mask().isEmpty())
                        for scale in (1, 1.25, 1.75, 2):
                            output = canvas(indicator.width(), indicator.height(), scale)
                            painter = QPainter(output)
                            indicator._render_badge(painter)
                            painter.end()
                            self.assertEqual(output.pixelColor(0, 0).alpha(), 0)
                            fringe = [output.pixelColor(x, y).alpha()
                                      for y in range(round(5 * scale))
                                      for x in range(round(indicator.height() / 2 * scale))]
                            self.assertTrue(any(0 < alpha < 205 for alpha in fringe), (mode, icon, scale))
                    finally:
                        indicator.deleteLater()
        finally:
            theme.apply('dark')
            APP.setStyleSheet(theme.qss())

    def test_windows_loading_pill_uses_per_pixel_upload_and_animation_updates(self):
        if APP.platformName() != 'windows':
            self.skipTest('Windows native alpha upload')
        parent = QWidget()
        parent.setGeometry(-8000, -8000, 500, 300)
        indicator = LoadingIndicator(parent)
        parent.show()
        try:
            indicator.start()
            QTest.qWait(120)
            indicator.grab()  # Native off-screen windows do not receive expose paints.
            self.assertTrue(indicator._alpha_uploaded)
            self.assertTrue(indicator.mask().isEmpty())
            self.assertTrue(indicator._movie.isValid())
            self.assertGreater(indicator._movie.currentFrameNumber(), 0)
            indicator.stop()
            self.assertTrue(indicator.isHidden())
        finally:
            parent.close()


if __name__ == '__main__':
    unittest.main()
