"""Offline fullscreen bar animation, interruption, settings and corner alpha."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from ddm import app as app_module, theme
from ddm.dialogs import GeneralSettingsPage
from ddm.widgets import TimeBadge
from dev.selfcheck_tile_fullscreen import SilentPoller


class PaintProbeEdit(QLineEdit):
    paints = 0

    def paintEvent(self, event):
        self.paints += 1
        super().paintEvent(event)


def check_reveal_start(tile, wake):
    values = []
    animation = tile._bar_animation
    animation.valueChanged.connect(values.append)
    layout = tile._layout_areas

    def prepare_layout():
        assert animation.state() == QAbstractAnimation.Stopped, 'Reveal clock started before layout finished'
        return layout()

    try:
        with patch.object(tile, '_layout_areas', side_effect=prepare_layout):
            wake()
        assert all(float(value) >= .999 for value in values), 'Reveal flashed a visible frame while configuring its range'
        assert animation.state() == QAbstractAnimation.Running and animation.currentTime() == 0
    finally:
        animation.valueChanged.disconnect(values.append)


def native_bar_image(widget):
    from ddm.badge_surface import BitmapInfo
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    if '--desktop' in sys.argv:
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
        for target in (widget.parentWidget().window(), widget):
            user32.SetWindowPos(int(target.winId()), wintypes.HWND(-1), 0, 0, 0, 0, 0x13)
        QTest.qWait(20)
        point = widget.mapToGlobal(QPoint())
        return widget.screen().grabWindow(0, point.x(), point.y(), widget.width(), widget.height()).toImage()
    user32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.POINTER(BitmapInfo),
        wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
    gdi32.CreateDIBSection.restype = wintypes.HANDLE
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    scale = widget.devicePixelRatioF()
    width, height = round(widget.width()*scale), round(widget.height()*scale)
    memory = gdi32.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    info = BitmapInfo(40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    assert memory and bitmap, 'Native capture allocation failed'
    previous = gdi32.SelectObject(memory, bitmap)
    try:
        assert user32.PrintWindow(int(widget.winId()), memory, 2), 'Native capture failed'
        image = QImage(ctypes.string_at(bits, width*height*4), width, height,
                       width*4, QImage.Format_RGB32).copy()
        image.setDevicePixelRatio(scale)
        return image
    finally:
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)


def check_transparent_bar(app, tile):
    from ddm.widgets import _icon_color
    from ddm import fullscreen_bar
    secret = 'private-danmaku-fixture'
    key = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, secret)
    with patch.dict(os.environ, DDM_FULLSCREEN_INPUT_CAPTURE='1'), \
            patch.object(fullscreen_bar.logging.getLogger(fullscreen_bar.__name__), 'info') as log:
        for _ in range(310):
            tile.bottom._trace_input('child-event', tile.bottom, key)
        assert log.call_count == 300, 'Input diagnostics must remain bounded'
        assert secret not in str(log.call_args_list), 'Input diagnostics must not record typed text'
        with patch.object(fullscreen_bar.time, 'monotonic', return_value=tile.bottom._input_trace_until + 1):
            tile.bottom._trace_input('expired', tile.bottom, key)
            assert log.call_count == 300
    tile.bottom._input_trace_until = tile.bottom._input_trace_count = 0
    editor = PaintProbeEdit(tile.bottom)
    editor.setGeometry(tile.bottom.width() // 2 - 90, 4, 180, 24)
    editor.setStyleSheet("QLineEdit {background: #236343; color: white; border: none;}")
    editor.show()
    try:
        for mode in ('dark', 'light'):
            theme.apply(mode)
            app.processEvents()
            QTest.qWait(30)
            image = QImage(tile.bottom.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            editor.paints = 0
            painter = QPainter(image)
            tile.bottom.render(painter, QPoint(), QRegion(), QWidget.DrawChildren)
            painter.end()
            assert editor.paints > 0, 'Transparent composition must include the live editor'
            sample_x = tile.bottom.width() // 2 + 120
            assert image.pixelColor(sample_x, 0).alpha() < 10, 'Fullscreen bar top must reveal video'
            assert 100 < image.pixelColor(sample_x, image.height() - 1).alpha() < 200, 'Bottom gradient must remain translucent'
            assert _icon_color(tile.pause_button).name() == '#ffffff', 'Icons must stay white in both themes'
            clicked = []
            tile.pause_button.clicked.connect(lambda: clicked.append(True))
            QTest.mouseClick(tile.pause_button, Qt.LeftButton)
            assert clicked, 'Transparent bar controls must remain interactive'
            editor.setFocus()
            QTest.keyClicks(editor, 'local-only')
            assert editor.text().endswith('local-only'), 'Embedded editors must retain keyboard input'
            QTest.qWait(30)
            assert editor.paints > 0, 'Typing still needs the ordinary live editor paint path'
            centre = editor.mapTo(tile.bottom, QPoint(editor.width()//2, 2))
            assert image.pixelColor(centre).name() == '#236343', 'Composited frame lost the input control'
            origin = tile.pause_button.mapTo(tile.bottom, QPoint())
            pixels = [image.pixelColor(origin.x()+x, origin.y()+y)
                      for y in range(tile.pause_button.height()) for x in range(tile.pause_button.width())]
            assert sum(c.red()>220 and c.green()>220 and c.blue()>220 for c in pixels) > 4, 'Composited frame lost the pause icon'
            if app.platformName() == 'windows':
                assert tile.bottom.qt_composited and tile.bottom.isWindow()
                assert tile.bottom.testAttribute(Qt.WA_TranslucentBackground)
                assert tile.bottom.windowHandle().format().alphaBufferSize() > 0, 'Qt must own an alpha backing store'
                assert not getattr(tile.bottom, '_layered_hwnd', None), 'Do not mix manual and Qt alpha uploads'
                for _ in range(3):
                    QTest.keyClicks(editor, 'a')
                    QTest.qWait(20)
                    native = native_bar_image(tile.bottom)
                    scale = native.devicePixelRatioF()
                    point = editor.mapTo(tile.bottom, QPoint(editor.width()//2, 2))
                    assert native.pixelColor(round(point.x()*scale), round(point.y()*scale)).name() == '#236343', 'Native window lost the editor during typing'
                    colours = [native.pixelColor(round((origin.x()+x)*scale), round((origin.y()+y)*scale))
                               for y in range(tile.pause_button.height()) for x in range(tile.pause_button.width())]
                    assert sum(c.red()>220 and c.green()>220 and c.blue()>220 for c in colours) > 4, 'Native window lost the pause icon'
                label_origin = tile.volume_label.mapTo(tile.bottom, QPoint())
                area = tile.volume_label.rect().translated(label_origin)
                before = native_bar_image(tile.bottom)
                tile.volume_label.setText('77' if mode == 'dark' else '42')
                QTest.qWait(30)
                after = native_bar_image(tile.bottom)
                x, y = round(area.x()*scale), round(area.y()*scale)
                width, height = round(area.width()*scale), round(area.height()*scale)
                assert before.copy(x, y, width, height) != after.copy(x, y, width, height), 'Native volume text must refresh under its mask'

        editor.hide()
    finally:
        editor.deleteLater()


def main():
    app = QApplication([])
    badge = TimeBadge()
    refreshed = []
    badge.refresh_theme = lambda: refreshed.append(True)
    badge.event(QEvent(QEvent.Type.Show))
    badge.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not refreshed, 'Destroyed badges must cancel queued theme refreshes'
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    room = {'room_id': '1000', 'uname': 'Fixture', 'live': False}
    with patch('ddm.app.QTimer.singleShot'):
        window = app_module.MainWindow([room], [dict(room)], layout_id='1x1',
            state={'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
    window._startup_update_timer.stop()
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(40, 40) if '--desktop' in sys.argv else window.move(-10000, -10000)
    window.resize(900, 650)
    window.show()
    window.isActiveWindow = lambda: True
    tile = window.wall.tiles[0]
    cursor = window._fullscreen_cursor
    try:
        for mode in ('dark', 'light'):
            theme.apply(mode)
            app.processEvents()
            for corner in tile.video_corners:
                image = QImage(24, 24, QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(2)
                image.fill(Qt.transparent)
                painter = QPainter(image)
                corner._render_badge(painter)
                painter.end()
                assert any(0 < image.pixelColor(x, y).alpha() < 255
                           for y in range(24) for x in range(24)), 'Missing antialiased pixels'
                outside_x = 23 if corner.right else 0
                assert image.pixelColor(outside_x, 0).alpha() == 0, 'Corner backing covers skin background'
                assert image.pixelColor(12, 12).alpha() == 0, 'Corner backing covers video interior'
                if app.platformName() == 'windows':
                    QTest.qWait(30)
                    assert corner._alpha_uploaded, 'Corner must use per-pixel alpha in both themes'
            assert all(corner.isVisible() for corner in tile.video_corners)
        if app.platformName() == 'windows':
            enter = window._fullscreen_presentation.enter
            with patch.object(window, '_upgrade_fullscreen_quality'), \
                    patch.object(window._fullscreen_presentation, 'enter',
                                 side_effect=lambda target: enter(target, None if '--desktop' in sys.argv else QRect(-20000, -20000, 1100, 800))):
                window._on_fullscreen(tile)
        else:
            # Motion/layout checks use a child tile. Native promotion and its
            # lifecycle are covered by the Windows fullscreen/Quick checks.
            window._fullscreen_tile = tile
            window.wall.set_fullscreen_tile(tile)
        cursor.stop()
        assert tile.bottom.updatesEnabled(), 'Real fullscreen entry must restore bottom-bar painting'
        app.processEvents()
        assert all(not corner.isVisible() for corner in tile.video_corners)
        geometry = tile.video.geometry()
        assert geometry.height() == tile.height(), 'Fullscreen video must fill the bottom too'
        check_transparent_bar(app, tile)
        if '--desktop' in sys.argv:
            with patch('ddm.motion.enabled', return_value=True):
                tile.set_fullscreen_controls_hidden(True)
                for _ in range(50):
                    if tile._bar_animation.state() == QAbstractAnimation.Stopped:
                        break
                    QTest.qWait(20)
                assert not tile.bottom.isVisible()
                check_reveal_start(tile, lambda: tile.set_fullscreen_controls_hidden(False))
                anchor = tile.bottom.geometry()
                middle = []
                for _ in range(6):
                    QTest.qWait(20)
                    middle.append(tile.bottom.windowOpacity())
                    assert tile.bottom.geometry() == anchor, f'Reveal changed geometry: anchor={anchor}, actual={tile.bottom.geometry()}, expected={tile.bottom._tile_rect}, dpr={tile.bottom.devicePixelRatioF()}'
                    assert tile.bottom.devicePixelRatioF() == tile.devicePixelRatioF(), 'Reveal changed the native bar DPI'
                    native_bar_image(tile.bottom)
                assert any(0 < opacity < 1 for opacity in middle), 'Reveal must retain its fade animation'
                assert tile.bottom.windowOpacity() == 1.0
            print('PASS: real fullscreen desktop pixels retain input and controls during typing')
            return
        if app.platformName() == 'windows':
            before = tile.bottom.mapToGlobal(QPoint())
            old = window.pos()
            window.move(old + QPoint(70, 40))
            app.processEvents()
            assert tile.bottom.mapToGlobal(QPoint()) == before + QPoint(70, 40), 'Native bar must follow its owner'
            layer = tile.video_danmaku
            with patch.object(layer, '_quick_layer', Mock()), patch.object(layer, '_quick_group', 1):
                layer._quick_mask_signature = None
                layer.update_quick_mask([tile.bottom])
                holes = layer._quick_mask_signature[-2]
                centre = layer.mapFromGlobal(tile.bottom.mapToGlobal(tile.bottom.rect().center()))
                assert holes.contains(centre), 'Comments must leave room for the bar on offset monitors'
            window.hide()
            app.processEvents()
            assert not tile.bottom.isVisible(), 'Hidden owner must not leave a floating bar'
            window.show()
            app.processEvents()
            assert tile.bottom.isVisible(), 'Restoring the owner must restore its bar'
        tile.time_badge.set_text('12:34:56')
        tile._layout_areas()
        assert tile.time_badge.geometry().bottom() < tile.bottom.tile_y() - 8, 'Time overlaps fullscreen bar'
        for progress in (0.25, 0.5, 0.75, 1.0, 0.5, 0.0):
            tile._slide_fullscreen_bar(progress)
            assert tile.time_badge.geometry().bottom() < tile.bottom.tile_y() - 8, 'Time overlaps sliding bar'
        tile._layout_areas()
        normal_y = tile.bottom.tile_y()
        point = tile.video.mapToGlobal(tile.video.rect().center())
        with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=point), \
                patch('ddm.motion.enabled', return_value=True):
            cursor.start()
            cursor._last_move = 0
            cursor.update_cursor()
            assert cursor.hidden
            QTest.qWait(60)
            if tile.bottom.qt_composited:
                assert tile.bottom.tile_y() == normal_y and 0 < tile.bottom.windowOpacity() < 1, 'Native bar must fade at a fixed position'
            else:
                assert normal_y < tile.bottom.tile_y() < tile.height(), 'Bar must slide down'
            halfway = tile.bottom.tile_y()
            opacity = tile.bottom.windowOpacity()
            cursor._position = point - QPoint(1, 0)
            cursor.update_cursor()
            assert not cursor.hidden and abs(tile.bottom.tile_y() - halfway) <= 1, 'Reversal jumped'
            if tile.bottom.qt_composited:
                assert abs(tile.bottom.windowOpacity() - opacity) < .01, 'Opacity reversal jumped'
            QTest.qWait(220)
            assert tile.bottom.tile_y() == normal_y and tile.bottom.isVisible()
            assert tile.video.geometry() == geometry, 'Animation resized native video'
            cursor._last_move = 0
            cursor.update_cursor()
            QTest.qWait(220)
            assert cursor.hidden and not tile.bottom.isVisible()
            cursor._position = point - QPoint(1, 0)
            check_reveal_start(tile, cursor.update_cursor)
            window.settings['fullscreen_auto_hide_controls'] = False
            cursor.update_cursor()
            QTest.qWait(220)
            assert tile.bottom.isVisible() and tile.bottom.tile_y() == normal_y, 'Switch-off must restore bar'
            assert tile.video.geometry() == geometry
            with patch.object(QApplication, 'activePopupWidget', return_value=object()):
                cursor.update_cursor()
                assert not cursor.hidden, 'Menu must restore controls and cursor'
            window.settings['fullscreen_auto_hide_controls'] = True
            with patch('ddm.motion.enabled', return_value=False):
                cursor._last_move = 0
                cursor.update_cursor()
                assert not tile.bottom.isVisible(), 'Reduced motion must hide immediately'
                cursor.stop()
                assert tile.bottom.isVisible(), 'Reduced motion must restore immediately'
            outside = tile.mapToGlobal(QPoint(tile.width() + 100, tile.height() // 2))
            with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=outside):
                cursor.update_cursor()
                QTest.qWait(220)
                assert not tile.bottom.isVisible() and not tile.controls.isVisible(), 'Leaving the screen must hide both bars'
                assert not cursor.hidden and QApplication.overrideCursor() is None, 'Other monitor cursor must stay visible'
                cursor.update_cursor()
                assert tile._bar_animation.state() == QAbstractAnimation.Stopped, 'Outside polling must not restart the slide'
                window.settings['fullscreen_auto_hide_controls'] = False
                cursor.update_cursor()
                QTest.qWait(220)
                assert tile.bottom.isVisible(), 'Leaving must respect the auto-hide switch'
                window.settings['fullscreen_auto_hide_controls'] = True
                cursor.update_cursor()
                QTest.qWait(220)
            cursor.update_cursor()
            QTest.qWait(220)
            assert tile.bottom.isVisible() and tile.controls.isVisible(), 'Returning must restore both bars'
            cursor._last_move = 0
            cursor.update_cursor()
            QTest.qWait(220)
            assert cursor.hidden
            with patch('ddm.fullscreen_cursor.QCursor.pos', return_value=outside):
                cursor.update_cursor()
                assert not cursor.hidden and QApplication.overrideCursor() is None, 'Leaving from idle must release the cursor'
            cursor.stop()
        if window._fullscreen_presentation.tile is not None:
            window._exit_fullscreen()
        else:
            window._fullscreen_tile = None
            window.wall.set_fullscreen_tile(None)
        assert not tile.bottom.property('fullscreen')
        assert not getattr(tile.bottom, '_layered_hwnd', None), 'Leaving fullscreen must restore ordinary bar painting'
        assert not tile.bottom.isWindow(), 'Leaving fullscreen must restore the ordinary child bar'
        assert not tile.bottom._masked_labels, 'Leaving fullscreen must restore native label regions'
        assert not tile.pause_button.property('fullscreen')
        assert tile._bar_progress == 0 and tile.bottom.isVisible()
        assert tile.time_badge.geometry().bottom() < tile.bottom.tile_y() - 8, 'Time overlaps normal bar'
        assert all(corner.isVisible() for corner in tile.video_corners)
        page = GeneralSettingsPage({'fullscreen_auto_hide_controls': False})
        assert not page.values()['fullscreen_auto_hide_controls']
        page.reset()
        assert page.values()['fullscreen_auto_hide_controls']
        assert window.current_state()['settings']['fullscreen_auto_hide_controls']
        page.close()
    finally:
        cursor.stop()
        window.close()
        app.processEvents()
    print('PASS: corner alpha, fullscreen animation, reversal, screen exit/return, cursor visibility, switch and cleanup')


if __name__ == '__main__':
    main()
