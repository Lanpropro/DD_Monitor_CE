"""Native reveal regions, bitmap paint count, DPI and software fallback."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm.theme_transition import WaveOverlay


def main():
    app = QApplication([])
    if sys.platform != 'win32' or app.platformName() != 'windows':
        print('SKIP: native Windows compositor test')
        return
    window = QWidget()
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(2560, 1440)
    window.show()
    scale = window.devicePixelRatioF()
    snapshot = QPixmap(round(window.width()*scale), round(window.height()*scale))
    snapshot.setDevicePixelRatio(scale)
    snapshot.fill(QColor('#123456'))
    overlay = WaveOverlay(window, snapshot, window.mapToGlobal(QPoint(10, 10)))
    counts = []
    original = WaveOverlay.paintEvent
    def painted(widget, event):
        counts.append(1)
        original(widget, event)
    with patch.object(WaveOverlay, 'paintEvent', painted):
        overlay.show()
        QTest.qWait(40)
        before = len(counts)
        for step in range(1, 16):
            overlay.reveal(step/20)
            app.processEvents()
        assert overlay._native_clip
        native_paints = len(counts)-before
        assert native_paints <= 2, ('Region changes must not repaint/upload each bitmap', native_paints)
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,)*4
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
        gdi32.PtInRegion.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            assert user32.GetWindowRgn(int(overlay.winId()), region)
            assert not gdi32.PtInRegion(region, round(11*scale), round(11*scale))
            assert gdi32.PtInRegion(region, round((window.width()-1)*scale), round((window.height()-1)*scale))
        finally:
            gdi32.DeleteObject(region)
        visible = overlay.grab().toImage()
        assert visible.pixelColor(round(11*scale), round(11*scale)).alpha() == 0
        assert visible.pixelColor(round((window.width()-10)*scale), round((window.height()-10)*scale)).name() == '#123456'
        with patch.object(overlay, '_clip_native', return_value=False):
            overlay.reveal(.8)
        assert not overlay._native_clip
        QTest.qWait(20)
        assert len(counts) > before+native_paints
    overlay.close()
    window.close()
    print(f'PASS: 15 native reveal steps required {native_paints} bitmap repaints; physical DPI region, interruption capture and software fallback')


if __name__ == '__main__':
    main()
