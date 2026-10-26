"""Corner selection markers and native loading pills render correctly."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.widgets import LoadingIndicator, NavSelectionCheck, StreamBadge, WallPaneBorder
from ddm.video_surface import VideoCorner

APP = QApplication.instance() or QApplication([])


def canvas(width, height, scale):
    image = QImage(round(width * scale), round(height * scale), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    return image


class SmoothEdges(unittest.TestCase):
    def test_native_upload_is_deferred_and_reentrant_paints_are_coalesced(self):
        if APP.platformName() != 'windows':
            self.skipTest('Windows native alpha upload')
        theme.apply('light')
        try:
            for factory in (StreamBadge, VideoCorner, LoadingIndicator,
                            lambda owner: WallPaneBorder(owner, None)):
                with self.subTest(factory=factory):
                    owner = QWidget()
                    owner.move(-8000, -8000)
                    widget = factory(owner)
                    widget.setAttribute(Qt.WA_NativeWindow)
                    try:
                        with patch.object(widget, '_paint_layered') as upload:
                            owner.show()
                            widget.show()
                            QTest.qWait(30)
                            upload.reset_mock()
                            for _ in range(5):
                                widget.grab()
                            upload.assert_not_called()
                            # An upload may synchronously trigger another paint.
                            upload.side_effect = lambda: widget.grab()
                            APP.processEvents()
                            self.assertEqual(upload.call_count, 1)
                            APP.processEvents()
                            self.assertEqual(upload.call_count, 1)
                            upload.reset_mock()
                            widget.grab()
                            widget.hide()
                            APP.processEvents()
                            upload.assert_not_called()
                    finally:
                        owner.close()
        finally:
            theme.apply('dark')

    def test_static_native_corner_reuses_upload_until_theme_or_size_changes(self):
        if APP.platformName() != 'windows':
            self.skipTest('Windows native alpha upload')
        owner = QWidget()
        owner.move(-8000, -8000)
        corner = VideoCorner(owner)
        owner.show()
        corner.show()
        APP.processEvents()
        try:
            corner.grab()
            APP.processEvents()
            self.assertTrue(corner._alpha_uploaded)
            with patch.object(corner, '_render_badge', wraps=corner._render_badge) as render:
                for _ in range(20):
                    corner.grab()
                    APP.processEvents()
                render.assert_not_called()
                corner.setFixedSize(14, 14)
                corner.grab()
                APP.processEvents()
                self.assertEqual(render.call_count, 1)
                theme.apply('light')
                corner.grab()
                APP.processEvents()
                self.assertEqual(render.call_count, 2)
        finally:
            owner.close()
            theme.apply('dark')

    def test_corner_marker_has_an_empty_ring_and_fills_when_selected(self):
        marker = NavSelectionCheck()
        marker.resize(28, 28)
        try:
            for mode in ('dark', 'light'):
                theme.apply(mode)
                marker.setChecked(False)
                empty = marker.grab().toImage()
                marker.setChecked(True)
                selected = marker.grab().toImage()
                scale = selected.devicePixelRatio()
                accent = theme.qcolor(theme.ACCENT)
                self.assertNotEqual(empty.pixelColor(round(14 * scale), round(14 * scale)), accent)
                rim = empty.pixelColor(round(14 * scale), round(4 * scale))
                self.assertGreater(rim.red(), 200)
                for x, y in ((14, 14), (14, 9), (14, 18), (9, 14), (18, 14)):
                    self.assertEqual(selected.pixelColor(round(x * scale), round(y * scale)), accent)
                for x, y in ((2, 2), (0, 0), (27, 27)):
                    self.assertEqual(selected.pixelColor(round(x * scale), round(y * scale)),
                                     empty.pixelColor(round(x * scale), round(y * scale)))
        finally:
            marker.deleteLater()
            theme.apply('dark')

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
            APP.processEvents()
            self.assertTrue(indicator._alpha_uploaded)
            self.assertTrue(indicator.mask().isEmpty())
            self.assertTrue(indicator._movie.isValid())
            self.assertGreater(indicator._movie.currentFrameNumber(), 0)
            import ctypes
            with patch.object(ctypes.windll.user32, 'SetWindowLongW',
                              wraps=ctypes.windll.user32.SetWindowLongW) as set_style:
                for _ in range(3):
                    indicator.grab()
                    APP.processEvents()
                set_style.assert_not_called()
            indicator.stop()
            self.assertTrue(indicator.isHidden())
        finally:
            parent.close()


if __name__ == '__main__':
    unittest.main()
