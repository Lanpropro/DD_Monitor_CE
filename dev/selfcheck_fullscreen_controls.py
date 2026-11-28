"""Offline fullscreen bar animation, interruption, settings and corner alpha."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPalette, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QPushButton, QWidget
from ddm import app as app_module, skin_parts, theme
from ddm.dialogs import GeneralSettingsPage
from ddm.settings_appearance import AppearanceSettingsPage
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
        assert animation.state() == QAbstractAnimation.Paused and animation.currentTime() == 0
        assert tile._bar_clock.isActive()
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
            tile.bottom.render(painter, QPoint(), QRegion(), QWidget.DrawWindowBackground | QWidget.DrawChildren)
            painter.end()
            assert editor.paints > 0, 'Transparent composition must include the live editor'
            # Sample the outer margin, clear of both editors and their backplates.
            sample_x = image.width() - 2
            check_gradient(image, sample_x)
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


def check_gradient(image, x):
    height = image.height()
    alpha = [image.pixelColor(x, y).alpha() for y in range(height)]
    assert alpha[0] < 5, 'Fullscreen bar top must reveal video'
    assert 20 < alpha[height // 2] < 50, 'Most of the bar must stay lightly shaded'
    assert 110 < alpha[-1] < 155, 'Bottom edge must darken without covering the video'
    assert alpha == sorted(alpha), 'Fullscreen bar must darken smoothly toward the bottom'


def check_skin_gradient(tile):
    bar = tile.bottom
    skin_parts.configure({}, {'controls': {'background': '#ff0033', 'radius': 8}})
    try:
        image = QImage(bar.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        bar.render(painter, QPoint(), QRegion(), QWidget.DrawWindowBackground)
        painter.end()
        check_gradient(image, image.width() // 2)
        assert image.pixelColor(image.width() // 2, image.height() - 1).red() == 0, (
            'Normal skin background must not be layered under the fullscreen gradient')
    finally:
        skin_parts.configure({}, {})


def check_control_contrast(app, tile):
    def render(widget, backdrop, flags=QWidget.DrawChildren):
        image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(backdrop))
        painter = QPainter(image)
        widget.render(painter, QPoint(), QRegion(), flags)
        painter.end()
        return image

    composer = QWidget(tile.bottom)
    composer.setObjectName('DanmakuComposer')
    composer.setAttribute(Qt.WA_StyledBackground)
    composer.setGeometry(tile.bottom.width() // 2 - 115, 4, 230, 26)
    # Match the installed composer, including the plugin's local background and button rules.
    composer.setStyleSheet('#DanmakuComposer {background: transparent; border: none;}'
                           '#DanmakuComposer QLineEdit {padding: 3px 6px;}')
    row = QHBoxLayout(composer)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    editor = QLineEdit(composer)
    editor.setPlaceholderText('Local input')
    editor.setFixedHeight(26)
    row.addWidget(editor, 1)
    emoji = QPushButton(composer, objectName='TileCtrl')
    emoji.setFixedSize(24, 24)
    emoji.setStyleSheet('QPushButton#TileCtrl {border-radius: 12px; padding: 0;}')
    row.addWidget(emoji)
    send = QPushButton('发送', composer, objectName='TileCtrl')
    send.setFixedSize(44, 26)
    send.setStyleSheet('QPushButton#TileCtrl:disabled {background: transparent; color: palette(tooltip-text);}')
    editor.textChanged.connect(lambda text: send.setEnabled(bool(text)))
    row.addWidget(send)
    composer.show()
    try:
        for mode in ('light', 'dark'):
            theme.apply(mode)
            app.processEvents()
            bar = tile.bottom
            alpha = render(bar, 'transparent', QWidget.DrawWindowBackground)
            check_gradient(alpha, bar.width() // 2)
            for button in (tile.pause_button, tile.fullscreen_button):
                button.setAttribute(Qt.WA_UnderMouse, False)
                app.sendEvent(button, QEvent(QEvent.Leave))
            white = render(bar, '#ffffff')
            dark = render(bar, '#101010')
            for widget in (tile.pause_button, tile.fullscreen_button):
                rect = widget.geometry()
                x, y = rect.left() + 2, rect.center().y()
                assert 85 < white.pixelColor(x, y).value() < 155, 'Local button group must dim bright video'
                assert dark.pixelColor(x, y).value() < 40, 'Backing must blend into dark video'
                assert any(dark.pixelColor(x, y).value() > 200 for x in range(rect.left(), rect.right())
                           for y in range(rect.top(), rect.bottom())), 'Button must keep its light foreground'
            # The pause glyph itself stays unoutlined when painted without its group.
            icon = render(tile.pause_button, '#ffffff')
            assert all(icon.pixelColor(x, y).value() > 230
                       for x in range(icon.width()) for y in range(icon.height()))
            sample = QPoint(3, tile.pause_button.height() // 2)
            hover_ink = QColor(theme.mix('#ffffff', '#e7ebf0', .15))
            for button in (tile.pause_button, tile.volume_button, tile.danmaku_button,
                           tile.danmaku_settings_button, tile.recording_button, tile.fullscreen_button):
                before = render(button, '#ffffff')
                app.sendEvent(button, QEvent(QEvent.Enter))
                hovered = render(button, '#ffffff')
                actual = hovered.pixelColor(sample)
                assert all(abs(a - b) <= 1 for a, b in zip(actual.getRgb()[:3], hover_ink.getRgb()[:3])), (
                    type(button).__name__, mode, actual.name(), hover_ink.name(),
                    button.underMouse(), button.property('hovered'))
                assert hovered.pixelColor(0, 0) == QColor('#ffffff'), 'Hover must follow the button corners'
                app.sendEvent(button, QEvent(QEvent.Leave))
                assert render(button, '#ffffff') == before, 'Leaving must restore the resting surface'
            tile.pause_button.setEnabled(False)
            app.sendEvent(tile.pause_button, QEvent(QEvent.Enter))
            assert render(tile.pause_button, '#ffffff').pixelColor(sample) == QColor('#ffffff')
            app.sendEvent(tile.pause_button, QEvent(QEvent.Leave))
            tile.pause_button.setEnabled(True)
            row.activate()
            gap = QPoint(editor.geometry().right() + 2, composer.height() // 2)
            field = QPoint(editor.geometry().right() - 16, gap.y())
            editor.clearFocus()
            for draft in ('', 'Local draft'):
                editor.setText(draft)
                send.setEnabled(bool(draft))
                for backdrop in ('#ffffff', '#101010'):
                    surface = render(bar, backdrop)
                    fill = surface.pixelColor(composer.pos() + field)
                    backing = surface.pixelColor(composer.pos() + gap)
                    assert fill == backing, (mode, backdrop, fill.name(), backing.name())
                    assert backing.lightness() <= 104, (mode, backdrop, backing.name())
                bright = render(composer, '#ffffff', QWidget.DrawWindowBackground | QWidget.DrawChildren)
                assert bright.pixelColor(0, 0) == QColor('#ffffff'), 'The backing keeps its rounded corners'
                placeholder = editor.palette().color(QPalette.PlaceholderText)
                assert placeholder.lightness() >= 220, (mode, placeholder.getRgb())
                assert editor.palette().color(QPalette.Text) == QColor('#ffffff')
                ink = send.palette().color(QPalette.ButtonText)
                assert ink.lightness() >= 200, (mode, draft, ink.getRgb())
            for button in (emoji, send):
                idle = render(button, '#2d333a')
                app.sendEvent(button, QEvent(QEvent.Enter))
                hovered = render(button, '#2d333a')
                button.setDown(True)
                pressed = render(button, '#2d333a')
                button.setDown(False)
                app.sendEvent(button, QEvent(QEvent.Leave))
                point = QPoint(5, button.height() // 2)
                colors = [image.pixelColor(point) for image in (idle, hovered, pressed)]
                assert len(set(color.name() for color in colors)) == 3, (mode, colors)
                for image in (hovered, pressed):
                    assert image.pixelColor(0, 0) == idle.pixelColor(0, 0), (mode, colors)
                    rgb = image.pixelColor(point).getRgb()[:3]
                    assert max(rgb) - min(rgb) < 24, (mode, rgb)
    finally:
        composer.hide()
        composer.deleteLater()


def check_windowed_overlay(app):
    from ddm.playback_controls import _icon_color
    from ddm.settings_autosave_apply import apply_changes
    from ddm.widget_support import TILE_BAR_HEIGHT

    key = 'windowed_transparent_controls'
    auto_hide = 'windowed_auto_hide_controls'
    rooms = [{'room_id': str(index), 'uname': f'Fixture {index}', 'live': False} for index in (1, 2)]
    with patch('ddm.app.QTimer.singleShot'):
        window = app_module.MainWindow(rooms, rooms, layout_id='2x2',
            state={'plugins_enabled': [], 'settings': {'auto_update': False, 'close_behavior': 'exit'}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.move(-10000, -10000)
    window.resize(1280, 800)
    window.show()
    page = AppearanceSettingsPage(window.settings)
    transparent_switch = page.windowed_transparent_controls
    auto_hide_switch = page.windowed_auto_hide_controls
    first, second, empty = window.wall.tiles[:3]
    original_video = QRect(first.video.geometry())
    video_handles = [tile.video.winId() for tile in (first, second)]
    editor = QLineEdit(first.bottom)
    editor.setStyleSheet('QLineEdit {background: #236343; color: white; border: none;}')
    editor.setText('draft')
    editor.show()

    def check_bar(tile):
        bar = tile.bottom
        assert bar.windowed_overlay and bar.controls_exposed()
        assert not bar.property('fullscreen') and not tile.property('fullscreen')
        assert bar.tile_y() == tile.height() - TILE_BAR_HEIGHT - 1
        assert tile.video.geometry().contains(QRect(1, bar.tile_y(), bar.width(), bar.height()))
        assert not bar.mask().contains(bar.rect().bottomLeft())
        assert not tile.video.mask().contains(tile.video.rect().bottomLeft())
        if app.platformName() == 'windows':
            assert bar.isWindow() and bar.qt_composited
            assert bar.windowHandle().format().alphaBufferSize() > 0

    try:
        assert original_video.bottom() < first.bottom.tile_y()
        assert not page.values()[key]
        assert page.sections.section('controls').isAncestorOf(transparent_switch)
        assert not page.values()[auto_hide] and not auto_hide_switch.isEnabled()
        transparent_switch.click()
        assert auto_hide_switch.isEnabled()
        with patch.object(window, '_restart_codec_tile') as restart:
            apply_changes(window, {'settings': {key: page.values()[key]}})
            app.processEvents()
            restart.assert_not_called()
        assert window.current_state()['settings'][key]
        for tile in (first, second, empty):
            check_bar(tile)
        with patch.object(window.room_placement, 'open_add_room') as add_room:
            assert empty.add_room_button.isVisible()
            assert (empty.add_room_button.geometry().center() - empty.video.rect().center()).manhattanLength() <= 2
            QTest.mouseClick(empty.add_room_button, Qt.LeftButton)
            assert add_room.call_args.kwargs['target_tile'] is empty
        empty.set_room({'room_id': '3'})
        check_bar(empty)
        assert empty.add_room_button.isHidden()
        empty.set_room(None)
        check_bar(empty)
        assert empty.add_room_button.isVisible()
        assert editor.text() == 'draft'
        editor.setGeometry(first.bottom.width() // 2 - 45, 4, 90, 24)
        QTest.keyClicks(editor, ' only')
        assert editor.text() == 'draft only'
        if app.platformName() == 'windows':
            app.processEvents()
            native = native_bar_image(first.bottom)
            scale = native.devicePixelRatioF()
            point = editor.mapTo(first.bottom, QPoint(editor.width() // 2, 2))
            assert native.pixelColor(round(point.x() * scale), round(point.y() * scale)).name() == '#236343'
        editor.hide()

        for mode in ('dark', 'light'):
            theme.apply(mode)
            app.processEvents()
            for tile in (first, empty):
                image = QImage(tile.bottom.size(), QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                with QPainter(image) as painter:
                    tile.bottom.render(painter, QPoint(), QRegion(), QWidget.DrawWindowBackground)
                check_gradient(image, image.width() // 2)
                assert _icon_color(tile.pause_button).name() == '#ffffff'
        click = Mock()
        first.pause_button.clicked.connect(click)
        QTest.mouseClick(first.pause_button, Qt.LeftButton)
        click.assert_called_once()

        window.move(window.pos() + QPoint(24, 16))
        window.resize(1160, 750)
        app.processEvents()
        for tile in (first, second):
            check_bar(tile)
        first.move(first.pos() + QPoint(4, 5))
        check_bar(first)
        first.hide()
        assert not first.bottom.isVisible() and second.bottom.isVisible()
        first.show()
        check_bar(first)
        window.hide()
        assert not first.bottom.isVisible() and not second.bottom.isVisible()
        window.show()
        app.processEvents()
        check_bar(first)
        check_bar(second)

        window.showMinimized()
        app.processEvents()
        assert not any(tile.bottom.isVisible() for tile in (first, second, empty))
        window.showNormal()
        app.processEvents()
        for tile in (first, second, empty):
            check_bar(tile)

        if app.platformName() == 'windows':
            settings = window._get_settings_process()
            settings.visible = True
            settings._set_occlusion(QRect(), force=True)
            assert first.bottom.isHidden() and second.bottom.isHidden(), 'Wait for the settings window'
            settings.window_hwnd = 1
            settings._set_occlusion(QRect(first.bottom.geometry()))
            assert first.bottom.isHidden() and second.bottom.isVisible()
            first._layout_areas()
            assert first.bottom.isHidden(), 'Layout must not remap an occluded bar'
            bar = first.bottom
            overlap = QRect(bar.geometry())
            overlap.setWidth(bar.width() // 2)
            settings._set_occlusion(overlap)
            covered = bar.mapFromGlobal(overlap.center())
            exposed = QPoint(3 * bar.width() // 4, bar.height() // 2)
            assert bar.isVisible(), 'A partial overlap must keep the exposed controls available'
            assert not bar.mask().contains(covered) and bar.mask().contains(exposed)
            user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
            user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN)
            gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
            gdi32.CreateRectRgn.restype = wintypes.HRGN
            gdi32.PtInRegion.argtypes = (wintypes.HRGN, ctypes.c_int, ctypes.c_int)
            gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
            native_region = gdi32.CreateRectRgn(0, 0, 0, 0)
            try:
                assert user32.GetWindowRgn(int(bar.winId()), native_region)
                scale = bar.devicePixelRatioF()
                assert not gdi32.PtInRegion(native_region, round(covered.x() * scale), round(covered.y() * scale))
                assert gdi32.PtInRegion(native_region, round(exposed.x() * scale), round(exposed.y() * scale))
            finally:
                gdi32.DeleteObject(native_region)
            first._layout_areas()
            assert not bar.mask().contains(covered) and bar.mask().contains(exposed)

            with patch.dict(window.settings, {auto_hide: True}):
                first.set_controls_visible(False)
                assert not bar.controls_exposed()
                first.set_controls_visible(True)
                assert bar.controls_exposed() and not bar.mask().contains(covered)

            overlap.setWidth(8)
            settings._set_occlusion(overlap)
            edge = QPoint(4, bar.height() // 2)
            assert not bar.mask().contains(edge)
            position = first.pos()
            first.move(position + QPoint(12, 0))
            assert bar.mask().contains(edge)
            first.move(position)
            assert bar.controls_exposed() and not bar.mask().contains(edge)
            settings._set_occlusion(QRect(second.bottom.geometry()))
            assert first.bottom.isVisible() and second.bottom.isHidden()
            assert bar.mask().contains(covered)
            with patch.dict(window.settings, {auto_hide: True}):
                second.set_controls_visible(False)
                settings.visible = False
                settings.window_hwnd = 0
                settings._set_occlusion(QRect())
                assert not second.bottom.controls_exposed(), 'Closing settings still respects auto-hide'
            settings._set_occlusion(QRect(), force=True)
            check_bar(first)
            check_bar(second)

            from ddm.dialogs import SettingsDialog
            dialog = SettingsDialog(window.settings, {}, window, preview=True)
            covered = QPoint(3 * bar.width() // 4, bar.height() // 2)
            exposed = QPoint(bar.width() // 4, bar.height() // 2)

            def show_local_settings():
                dialog.setAttribute(Qt.WA_ShowWithoutActivating)
                dialog.move(bar.mapToGlobal(QPoint(bar.width() // 2, -100)))
                dialog.show()
                app.processEvents()
                assert bar.controls_exposed() and not bar.mask().contains(covered), 'Local settings must clip the native bar'
                assert bar.mask().contains(exposed), 'Uncovered controls must remain available'
                first.raise_overlays()
                assert not bar.mask().contains(covered), 'Raising controls must keep settings clear'
                dialog.move(dialog.pos() + QPoint(0, -dialog.height()))
                app.processEvents()
                assert bar.mask().contains(covered), 'Moving the local dialog must expose the controls immediately'
                dialog.hide()
                return SettingsDialog.DialogCode.Rejected

            with patch.object(window, '_create_settings_dialog', return_value=dialog), \
                    patch.object(dialog, 'exec', side_effect=show_local_settings):
                assert not window.open_settings()
            check_bar(first)

            enter = window._fullscreen_presentation.enter
            with patch.object(window, '_upgrade_fullscreen_quality'), \
                    patch.object(window._fullscreen_presentation, 'enter',
                                 side_effect=lambda tile: enter(tile, QRect(-12000, -12000, 1000, 700))):
                window._on_fullscreen(first)
            assert first.bottom.property('fullscreen') and first.bottom.isVisible()
            assert not second.bottom.isVisible() and not empty.bottom.isVisible()
            window._exit_fullscreen()
            app.processEvents()
            check_bar(first)
            check_bar(second)

        geometry = QRect(first.video.geometry())
        auto_hide_switch.click()
        apply_changes(window, {'settings': {auto_hide: page.values()[auto_hide]}})
        assert window.current_state()['settings'][auto_hide]
        with patch('ddm.tile_controls.QCursor.pos') as pointer, \
                patch('ddm.tile_controls.time') as clock, \
                patch('ddm.tile_widgets.set_native_cursor'):
            clock.monotonic.return_value = 10.0

            def poll(x):
                pointer.return_value = x
                first._poll_control_hover()
                second._poll_control_hover()
                empty._poll_control_hover()

            point = first.video.mapToGlobal(first.video.rect().center())
            poll(second.video.mapToGlobal(second.video.rect().center()))
            assert second.bottom.controls_exposed() and not first.bottom.controls_exposed()
            poll(point)
            check_bar(first)
            assert not second.bottom.controls_exposed()
            clock.monotonic.return_value += first.CONTROL_IDLE_SECONDS - .1
            poll(point)
            assert first.bottom.controls_exposed()
            with patch.object(first, 'plugin_interaction_active', return_value=True):
                clock.monotonic.return_value += first.CONTROL_IDLE_SECONDS
                poll(point)
                assert first.bottom.controls_exposed()
            with patch.object(first.volume_menu, 'isVisible', return_value=True):
                clock.monotonic.return_value += first.CONTROL_IDLE_SECONDS
                poll(point)
                assert first.bottom.controls_exposed()
            clock.monotonic.return_value += first.CONTROL_IDLE_SECONDS + .1
            poll(point)
            assert not first.bottom.controls_exposed() and not second.bottom.controls_exposed()
            assert not empty.bottom.controls_exposed()
            empty_point = empty.video.mapToGlobal(empty.video.rect().center())
            poll(empty_point)
            check_bar(empty)
            assert not first.bottom.controls_exposed() and not second.bottom.controls_exposed()
            clock.monotonic.return_value += empty.CONTROL_IDLE_SECONDS + .1
            poll(empty_point)
            assert not empty.bottom.controls_exposed() and empty.add_room_button.isVisible()
            assert first.video.geometry() == geometry
            with patch.object(first._plugin_controls, 'focus_input') as focus, \
                    patch.object(first.bottom, 'activateWindow'):
                first.focus_danmaku_input()
                focus.assert_called_once()
                check_bar(first)
            first.set_controls_visible(False)
            first._control_hover_timer.stop()
            pointer.return_value = point + QPoint(5, 0)
            with patch.object(window, 'isActiveWindow', return_value=True):
                window._wall_control_hover.sync()
            check_bar(first)
            assert not second.bottom.controls_exposed()

            if app.platformName() == 'windows':
                clock.monotonic.return_value += first.CONTROL_IDLE_SECONDS + .1
                poll(point + QPoint(5, 0))
                assert not first.bottom.controls_exposed()
                with patch.object(window, '_upgrade_fullscreen_quality'), \
                        patch.object(window._fullscreen_presentation, 'enter',
                                     side_effect=lambda tile: enter(tile, QRect(-12000, -12000, 1000, 700))):
                    window._on_fullscreen(first)
                assert first.bottom.property('fullscreen') and first.bottom.isVisible()
                window._exit_fullscreen()
                assert first.bottom.windowed_overlay

        auto_hide_switch.click()
        apply_changes(window, {'settings': {auto_hide: page.values()[auto_hide]}})
        first.set_controls_visible(False)
        check_bar(first)
        check_bar(second)
        page.reset()
        apply_changes(window, {'settings': {key: page.values()[key]}})
        app.processEvents()
        assert not window.current_state()['settings'][key]
        assert first.video.geometry().bottom() < first.bottom.tile_y()
        assert not first.bottom.property('overVideo') and not first.bottom.isWindow()
        assert not second.bottom.isWindow() and not empty.bottom.isWindow()
        assert not empty.bottom.windowed_overlay and empty.add_room_button.isVisible()
        if app.platformName() == 'windows':
            assert [tile.video.winId() for tile in (first, second)] == video_handles
    finally:
        page.close()
        window.close()
        app.processEvents()
    print('PASS: windowed video overlay, settings, per-tile idle, controls, fullscreen and cleanup')


def main():
    app = QApplication([])
    if '--windowed' in sys.argv:
        app_module.StatusPoller = app_module.StatsPoller = SilentPoller
        check_windowed_overlay(app)
        return
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
        tile.window().isActiveWindow = lambda: True
        assert tile.bottom.updatesEnabled(), 'Real fullscreen entry must restore bottom-bar painting'
        app.processEvents()
        assert tile.bottom.isVisible(), 'Promoting a hidden tile must show its fullscreen bar'
        assert tile.bottom.width() == tile.width(), 'Fullscreen bar must use the promoted tile size'
        assert all(not corner.isVisible() for corner in tile.video_corners)
        geometry = tile.video.geometry()
        assert geometry.height() == tile.height(), 'Fullscreen video must fill the bottom too'
        check_transparent_bar(app, tile)
        check_skin_gradient(tile)
        check_control_contrast(app, tile)
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
                positions = []
                for _ in range(6):
                    QTest.qWait(20)
                    middle.append(tile.bottom.windowOpacity())
                    positions.append(tile.bottom.tile_y())
                    assert tile.bottom.size() == anchor.size(), 'Reveal must not resize the native bar'
                    assert tile.bottom.devicePixelRatioF() == tile.devicePixelRatioF(), 'Reveal changed the native bar DPI'
                    native_bar_image(tile.bottom)
                assert any(0 < opacity < 1 for opacity in middle), 'Reveal must retain its fade animation'
                assert positions[-1] < positions[0], 'Reveal must slide up into the video'
                assert tile.bottom.windowOpacity() == 1.0
            print('PASS: real fullscreen desktop pixels retain input and controls during typing')
            return
        if app.platformName() == 'windows':
            before = tile.bottom.mapToGlobal(QPoint())
            owner = tile.window()
            old = owner.pos()
            owner.move(old + QPoint(70, 40))
            app.processEvents()
            assert tile.bottom.mapToGlobal(QPoint()) == before + QPoint(70, 40), 'Native bar must follow its owner'
            layer = tile.video_danmaku
            with patch.object(layer, '_quick_layer', Mock()), patch.object(layer, '_quick_group', 1):
                layer._quick_mask_signature = None
                layer.update_quick_mask([tile.bottom])
                holes = layer._quick_mask_signature[-2]
                centre = layer.mapFromGlobal(tile.bottom.mapToGlobal(tile.bottom.rect().center()))
                assert holes.contains(centre), 'Comments must leave room for the bar on offset monitors'
            owner.hide()
            app.processEvents()
            assert not tile.bottom.isVisible(), 'Hidden owner must not leave a floating bar'
            owner.show()
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
            assert normal_y < tile.bottom.tile_y() < tile.height(), 'Bar must slide down'
            if tile.bottom.qt_composited:
                assert 0 < tile.bottom.windowOpacity() < 1, 'Native bar must fade while sliding'
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
            # Clicking a native bottom-bar button can activate the Tool window.
            # Once the pointer returns to the video, idle hiding must still work.
            with patch.object(tile.window(), 'isActiveWindow', return_value=False), \
                    patch.object(tile.bottom, 'isActiveWindow', return_value=True):
                cursor._last_move = 0
                cursor.update_cursor()
                assert cursor.hidden, 'Active native bottom bar must count as the fullscreen player'
                cursor.stop()
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
        assert tile.bottom.testAttribute(Qt.WA_StyledBackground)
        assert not tile.bottom.property('customControlSurface')
        assert not getattr(tile.bottom, '_layered_hwnd', None), 'Leaving fullscreen must restore ordinary bar painting'
        assert not tile.bottom.isWindow(), 'Leaving fullscreen must restore the ordinary child bar'
        assert not tile.bottom._masked_labels, 'Leaving fullscreen must restore native label regions'
        assert not tile.pause_button.property('fullscreen')
        assert tile._bar_progress == 0 and tile.bottom.isVisible()
        assert tile.time_badge.geometry().bottom() < tile.bottom.tile_y() - 8, 'Time overlaps normal bar'
        assert all(corner.isVisible() for corner in tile.video_corners)
        if app.platformName() == 'windows':
            assert not ctypes.windll.user32.GetWindowLongW(int(tile.bottom.winId()), -20) & 0x80000, 'Normal bar retained the fullscreen layered backing store'
            get_owner = ctypes.windll.user32.GetWindow
            get_owner.argtypes = (wintypes.HWND, wintypes.UINT)
            get_owner.restype = wintypes.HWND
            popup = QWidget(tile.bottom, Qt.Tool | Qt.FramelessWindowHint)
            popup.setAttribute(Qt.WA_ShowWithoutActivating)
            popup.move(-20000, -20000)
            nested_popup = QWidget(popup, Qt.Tool | Qt.FramelessWindowHint)
            nested_popup.setAttribute(Qt.WA_ShowWithoutActivating)
            nested_popup.move(-20000, -20000)
            wall_windows = set(QApplication.topLevelWidgets())
            enter = window._fullscreen_presentation.enter
            sync_danmaku_controls = window.wall._sync_danmaku_controls

            def sync_danmaku_before_video_hides():
                if window.wall.fullscreen_tile is tile:
                    assert tile.video.isVisible(), 'Docked controls must detach while the old video is visible'
                sync_danmaku_controls()

            with patch.object(window, '_upgrade_fullscreen_quality'), \
                    patch.object(window._fullscreen_presentation, 'enter',
                                 side_effect=lambda target: enter(target, QRect(-20000, -20000, 1100, 800))), \
                    patch.object(window.wall, '_sync_danmaku_controls', side_effect=sync_danmaku_before_video_hides), \
                    patch('ddm.motion.enabled', return_value=False):
                for _ in range(3):
                    window._on_fullscreen(tile)
                    cursor.stop()
                    app.processEvents()
                    assert tile.bottom.isVisible() and tile.bottom.windowOpacity() == 1.0
                    assert tile.bottom.width() == tile.width()
                    for current, owner in ((popup, tile.bottom), (nested_popup, popup)):
                        current.show()
                        assert get_owner(int(current.winId()), 4) == int(owner.winId()), (
                            'A reused popup must belong to the current native owner')
                    tile.set_fullscreen_controls_hidden(True)
                    assert not tile.bottom.isVisible()
                    tile.set_fullscreen_controls_hidden(False)
                    assert tile.bottom.isVisible() and tile.bottom.windowOpacity() == 1.0
                    native_bar_image(tile.bottom)
                    nested_popup.hide()
                    popup.hide()
                    window._exit_fullscreen()
                    assert not [widget for widget in set(QApplication.topLevelWidgets()) - wall_windows
                                if widget.parentWidget() is window and widget.isVisible()], (
                        'A temporary presentation window is still covering the restored wall')
                    app.processEvents()
                    assert tile.bottom.isVisible() and not tile.bottom.isWindow()
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
