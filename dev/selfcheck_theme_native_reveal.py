"""Native reveal regions, bitmap paint count, DPI and software fallback."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm.theme_transition import WaveOverlay


def check_render_thread(app):
    from ddm.theme_wave_quick import QuickWaveOverlay
    window = QWidget()
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setGeometry(-20000, -20000, 640, 360)
    window.show()
    QTest.qWait(20)
    snapshot = QPixmap(window.size())
    snapshot.fill(QColor('#123456'))
    painter = QPainter(snapshot)
    painter.setCompositionMode(QPainter.CompositionMode_Source)
    painter.fillRect(QRect(560, 100, 40, 40), Qt.transparent)
    painter.end()
    overlay = QuickWaveOverlay(window, snapshot, window.mapToGlobal(QPoint()))
    overlay.stage.setProperty('milliseconds', 2000)
    samples = []
    gui_thread = threading.get_ident()
    def frame():
        samples.append((time.perf_counter(), threading.get_ident()))
    try:
        overlay.show()
        time.sleep(.25)  # Delay first presentation; the animation must remain held at zero.
        QTest.qWait(80)
        assert overlay.view.isExposed()
        deadline = time.perf_counter() + 2
        while not overlay.ready_to_reveal and time.perf_counter() < deadline:
            QTest.qWait(10)
        assert overlay.ready_to_reveal, (overlay._synced, len(overlay._ready_connections))
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        assert user32.GetWindowLongW(int(overlay.view.winId()), -20) & 0x20, 'Native wave must pass input through'
        before = overlay.grab().toImage()
        scale = before.devicePixelRatio()
        assert before.pixelColor(round(20*scale), round(20*scale)).alpha() > 200, 'The first presented cover must be complete'
        assert before.pixelColor(round(400*scale), round(300*scale)).alpha() > 200
        assert before.pixelColor(round(580*scale), round(120*scale)).alpha() == 0, 'Live-video holes must remain transparent'
        overlay.start_reveal()
        QTest.qWait(80)
        samples.clear()
        overlay.view.afterRendering.connect(frame, Qt.DirectConnection)
        time.sleep(.4)  # No GUI event processing; render-thread Animator must continue.
        blocked_frames = list(samples)
        overlay.view.afterRendering.disconnect(frame)
        after = overlay.grab().toImage()
        assert after.pixelColor(round(400*scale), round(300*scale)).alpha() < 10
        assert len(blocked_frames) >= 3, len(blocked_frames)
        assert all(thread != gui_thread for _, thread in blocked_frames)
        assert window.geometry().right() < 0
        print('PASS: circular shader reveal, GUI blocked 400ms, render frames', len(blocked_frames),
              'backend', overlay.view.rendererInterface().graphicsApi().name,
              '; off-screen functionality, not live performance')
        overlay.hide()
        from ddm import motion, theme
        from ddm import window_fullscreen
        from ddm.theme_transition import ThemeTransition
        transition = ThemeTransition(window)
        window._theme_transition = transition
        window.refresh_theme = lambda: window_fullscreen.sync_titlebar(window)
        starts = []
        original_start = QuickWaveOverlay.start_reveal
        def start_after_cover(item):
            cover = item.grab().toImage()
            ratio = cover.devicePixelRatio()
            starts.append((cover.pixelColor(round(20*ratio), round(20*ratio)).alpha(),
                           item.ready_to_reveal, item.parentWidget().updatesEnabled(), item._revision,
                           window_fullscreen._dwm_get(int(window.winId()), 20), int(not theme.is_light()),
                           item.caption_height))
            original_start(item)
        with patch.object(motion, 'enabled', return_value=True), \
                patch.object(QuickWaveOverlay, 'start_reveal', start_after_cover):
            theme.apply('dark')
            transition.change('light', window.mapToGlobal(QPoint()))
            assert isinstance(transition.overlays[0], QuickWaveOverlay)
            cached = transition.overlays[0]
            assert not window.updatesEnabled() and not transition.animation.state().name == 'Running'
            QTest.qWait(50)
            transition.change('dark', window.mapToGlobal(QPoint()))
            assert isinstance(transition.overlays[0], QuickWaveOverlay)
            assert transition.overlays[0] is cached, 'The shader scene must be reused'
            QTest.qWait(600)
            assert not transition.overlays
            assert window.updatesEnabled()
            transition.change('light', window.mapToGlobal(QPoint()))
            quick_window = transition.overlays[0].view
            window.move(-19000, -19000)
            assert not transition.overlays and not quick_window.isVisible() and window.updatesEnabled()
        assert starts and all(alpha > 200 and ready and enabled and native == target and top > 0
            for alpha, ready, enabled, _, native, target, top in starts), ('A full cover must precede revealing the already updated native frame', starts)
        print('PASS: actual theme entry, reverse click snapshot, completion and move cancellation')
    finally:
        overlay.hide()
        overlay.deleteLater()
        window.close()
        app.processEvents()


def check_caption_wave(app):
    from ddm import theme, window_fullscreen
    from ddm.theme_transition import framed_snapshot
    from ddm.theme_wave_quick import QuickWaveOverlay
    from ddm.video_surface import VideoSurface
    window = QWidget()
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.setWindowTitle('Native caption wave fixture')
    window.setGeometry(-6000, -6000, 640, 360)
    surface = VideoSurface(window)
    surface.setGeometry(500, 150, 100, 80)
    window._player_active = True
    window.show()
    QTest.qWait(40)
    hwnd = int(window.winId())
    style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
    theme.apply('light')
    window_fullscreen.sync_titlebar(window)
    QTest.qWait(30)
    light = window_fullscreen.caption_snapshot(window).toImage()
    theme.apply('dark')
    window_fullscreen.sync_titlebar(window)
    QTest.qWait(30)
    dark = window_fullscreen.caption_snapshot(window).toImage()
    assert not light.isNull() and not dark.isNull()
    assert light.pixelColor(light.width()//2, light.height()//2) != dark.pixelColor(dark.width()//2, dark.height()//2), 'Capture must contain DWM colours, not the legacy WM_PRINT caption'
    snapshot = framed_snapshot(window)
    overlay = QuickWaveOverlay(window, snapshot, window.mapToGlobal(QPoint(10, 40)))
    try:
        overlay.show()
        deadline = time.perf_counter()+2
        while not overlay.ready_to_reveal and time.perf_counter() < deadline:
            QTest.qWait(10)
        assert overlay.ready_to_reveal
        top = overlay.caption_height
        assert top > 0 and overlay.origin == QPoint(10, 40+top)
        assert overlay.view.geometry().topLeft() == window.mapToGlobal(QPoint(0, -top))
        scale = snapshot.devicePixelRatio()
        before = overlay.grab().toImage()
        assert before.pixelColor(round(300*scale), round(top/2*scale)).alpha() > 200
        assert before.pixelColor(round(550*scale), round((top+190)*scale)).alpha() == 0, 'Video holes must move with the client offset'
        theme.apply('light')
        window_fullscreen.sync_titlebar(window)
        effect = next(child for child in overlay.stage.childItems() if child.property('maxRadius') is not None)
        overlay.stage.hold()
        effect.setProperty('progress', 160/overlay.stage.property('radius'))
        QTest.qWait(40)
        frame = overlay.grab().toImage()
        pixel = lambda x, y: frame.pixelColor(round(x*scale), round(y*scale))
        assert pixel(20, top/2).alpha() < 10 and pixel(600, top/2).alpha() > 200, 'The circle must reveal part of the native titlebar while retaining its far end'
        assert pixel(110, top+80).alpha() < 10 and pixel(580, top+320).alpha() > 200
        assert pixel(100, top-1).alpha() < 10 and pixel(100, top+1).alpha() < 10, 'The same circle must cross the caption/client boundary'
        assert int(window.winId()) == hwnd and ctypes.windll.user32.GetWindowLongW(hwnd, -16) == style
        output = Path(__file__).resolve().parents[1]/'work/theme-frame-wave'
        output.mkdir(parents=True, exist_ok=True)
        dark.save(str(output/'native-dark-caption.png'))
        light.save(str(output/'native-light-caption.png'))
        frame.save(str(output/'caption-and-client-circle.png'))
        composite = framed_snapshot(window)
        painter = QPainter(composite)
        painter.drawImage(0, 0, frame)
        painter.end()
        composite.save(str(output/'caption-and-client-composite.png'))
        print('PASS: real native caption capture, shared circular shader across caption/client, video holes and stable native HWND/style')
    finally:
        overlay.hide()
        overlay.deleteLater()
        window.close()
        app.processEvents()
    borderless = QWidget(None, Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
    borderless.setGeometry(-6000, -6000, 320, 200)
    borderless.setAttribute(Qt.WA_ShowWithoutActivating)
    borderless.show()
    try:
        QTest.qWait(20)
        assert window_fullscreen.caption_snapshot(borderless).isNull(), 'Borderless/fullscreen windows must not gain a fake titlebar'
    finally:
        borderless.close()


def main():
    app = QApplication([])
    if sys.platform != 'win32' or app.platformName() != 'windows':
        print('SKIP: native Windows compositor test')
        return
    if '--render-thread' in sys.argv:
        check_render_thread(app)
        check_caption_wave(app)
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
