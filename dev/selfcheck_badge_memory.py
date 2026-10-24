"""Repeated native badge/corner uploads must not retain per-redraw ctypes types."""
import gc
import os
from pathlib import Path
import sys
import tracemalloc
import unittest

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.badge_surface import BadgeSurface
from ddm.video_surface import VideoCorner

APP = QApplication.instance() or QApplication([])


class SampleBadge(BadgeSurface):
    def __init__(self, parent):
        super().__init__(parent)
        self._mask_path = QPainterPath()
        self.resize(160, 24)
        self.setAttribute(Qt.WA_NativeWindow)

    def paint_badge(self, painter):
        painter.fillRect(self.rect(), Qt.red)


@unittest.skipUnless(sys.platform == 'win32' and APP.platformName() == 'windows',
                     'Windows native alpha uploads required')
class BadgeMemoryTests(unittest.TestCase):
    def test_repeated_badge_and_corner_uploads_keep_memory_bounded(self):
        parent = QWidget()
        parent.setAttribute(Qt.WA_ShowWithoutActivating)
        parent.setGeometry(-10000, -10000, 400, 100)
        surfaces = [SampleBadge(parent), VideoCorner(parent), VideoCorner(parent, right=True)]
        for index, surface in enumerate(surfaces):
            surface.move(index * 170, 0)
        try:
            parent.show()
            APP.processEvents()
            # Warm Qt/ctypes caches before measuring the sustained redraw path.
            for mode in ('dark', 'light'):
                theme.apply(mode)
                for _ in range(10):
                    for surface in surfaces:
                        surface._paint_layered()
            gc.collect()
            tracemalloc.start()
            before = tracemalloc.get_traced_memory()[0]
            for mode in ('dark', 'light'):
                theme.apply(mode)
                for _ in range(400):
                    for surface in surfaces:
                        surface._paint_layered()
                        self.assertTrue(surface._alpha_uploaded, 'Native alpha upload failed')
            gc.collect()
            retained = tracemalloc.get_traced_memory()[0] - before
            self.assertLess(retained, 512 * 1024,
                            f'2,400 redraws retained {retained / 1024:.1f} KiB after GC')
            print(f'Native badge/corner redraws: retained {retained / 1024:.1f} KiB', flush=True)
        finally:
            tracemalloc.stop()
            parent.close()
            parent.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            theme.apply('dark')


if __name__ == '__main__':
    unittest.main()
