"""Isolated multi-pane PiP regression; --native uses local MP4s and real HWNDs."""
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'dev')]
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFocusEvent, QMouseEvent, QPixmap, QRegion, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from ddm import config, plugins, theme
from ddm.app import MainWindow
from ddm.picture_in_picture import (PictureInPictureDialog, PictureInPictureWindow,
    FOCUS_LAYOUT, composition_aspect, composition_ratio, composition_rows, pane_rectangles, video_aspect)


def pointer(surface, kind, local, global_pos, button, buttons):
    event = QMouseEvent(kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(surface, event)


def wheel(widget, delta, modifiers=Qt.NoModifier, *, direct=False):
    local = widget.rect().center()
    event = QWheelEvent(QPointF(local), QPointF(widget.mapToGlobal(local)), QPoint(), QPoint(0, delta),
                        Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
    if direct:
        widget.wheelEvent(event)  # The monitor's controls are hidden while PiP is open.
    else:
        QApplication.sendEvent(widget, event)


class VisibilityEvents(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Hide, QEvent.Show, QEvent.WinIdChange):
            self.events.append((watched, event.type()))
        return False


def check_floating_style(pip, wall, tiles, layer):
    floating = pip.floating
    assert floating.windowFlags() & Qt.FramelessWindowHint
    assert floating.box.contentsMargins().isNull() and floating.box.spacing() == 0
    assert wall.geometry() == floating.rect(), 'Video wall must fill the floating window'
    clip = floating.property('presentationMask')
    assert not clip.contains(QPoint(0, 0))
    assert clip.contains(floating.rect().center())
    assert abs(floating.height() - floating.width() / floating.aspect) <= 1
    for tile in tiles[:2]:
        assert tile.video.geometry() == tile.rect(), 'PiP video must have no border inset'
        tile.set_controls_visible(True)
        assert not any(widget.isVisible() for widget in
                       (tile.controls, tile.stream_badge, tile.title_badge, tile.time_badge))
        assert tile.video.square_corners and not any(corner.isVisible() for corner in tile.video_corners)
        assert tile.video.hasMouseTracking()
        if tile.cover.isVisible():
            assert tile.cover.pixmap().toImage().pixelColor(0, 0).alpha() == 255, 'Covers must join without rounded inner corners'
    with patch.object(floating, '_pointer_over', return_value=True):
        floating._poll_tools()
    assert floating.tools.isVisible()
    assert floating.tools.pos() == floating.mapToGlobal(QPoint(floating.width() - floating.tools.width() - 8, 8))
    assert floating.tools.windowHandle().transientParent() is floating.windowHandle()
    if QApplication.platformName() == 'windows':
        import ctypes
        from ctypes import wintypes
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetClientRect.argtypes = user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        hwnd = int(floating.winId())
        client, frame = wintypes.RECT(), wintypes.RECT()
        assert user32.GetClientRect(hwnd, ctypes.byref(client))
        assert user32.GetWindowRect(hwnd, ctypes.byref(frame))
        assert (frame.right - frame.left, frame.bottom - frame.top) == (client.right, client.bottom), 'No native title or resize frame may consume video space'
        assert not user32.GetWindowLongW(hwnd, -16) & 0x00C00000  # WS_CAPTION
        assert user32.GetWindowLongW(int(floating.tools.winId()), -20) & 0x00080000  # WS_EX_LAYERED
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HRGN
        gdi32.PtInRegion.argtypes = (wintypes.HRGN, ctypes.c_int, ctypes.c_int)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN)
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            if floating._native_rounding:
                from ddm.window_fullscreen import _dwm_get
                assert _dwm_get(hwnd, 33) == 2
                assert floating.mask().isEmpty()
                assert not user32.GetWindowRgn(hwnd, region), 'Hard regions disable smooth compositor corners'
            else:
                assert user32.GetWindowRgn(hwnd, region)
                assert not gdi32.PtInRegion(region, 0, 0)
                assert gdi32.PtInRegion(region, client.right // 2, client.bottom // 2)
        finally:
            gdi32.DeleteObject(region)
    assert all(button.text() == '' and button.toolTip() and button.accessibleName()
               for button in (floating.tools.manage, floating.tools.reorder, floating.pin, floating.tools.back, floating.tools.close_only))
    image = floating.tools.grab().toImage()
    assert image.pixelColor(0, 0).alpha() == 0, 'No rectangular backing behind the icons'
    assert image.pixelColor(12, 20).alpha() > 0
    if layer is not None:
        layer._update_occlusion()
        assert not layer.window.mask().contains(QPoint(0, 0)), 'Comments must respect the outer corners'
        assert not layer.window.mask().contains(floating.tools.pos() - floating.pos() + QPoint(12, 12))
    floating.tools.manage.click()
    assert pip.dialog is not None
    floating._poll_tools()
    assert not floating.tools.isVisible(), 'The picker must remain above the tools'
    pip.dialog.reject()
    with patch.object(floating, '_pointer_over', return_value=False):
        floating._poll_tools()
    assert not floating.tools.isVisible()

    # Deliver local input without moving the real desktop pointer or opening a QDrag.
    surface = tiles[0].video
    local = surface.rect().center()
    start = surface.mapToGlobal(local)
    bounds = floating.geometry()
    pointer(surface, QEvent.MouseButtonPress, local, start, Qt.LeftButton, Qt.LeftButton)
    pointer(surface, QEvent.MouseMove, local + QPoint(23, 17), start + QPoint(23, 17), Qt.NoButton, Qt.LeftButton)
    pointer(surface, QEvent.MouseButtonRelease, local, start + QPoint(23, 17), Qt.LeftButton, Qt.NoButton)
    assert floating.geometry() == bounds.translated(23, 17), 'Dragging video must move the entire window'
    # Bottom-right resize and top-left minimum-size clamp, including opposite-edge anchoring.
    for local, delta in ((floating.rect().bottomRight() - QPoint(2, 2), QPoint(61, 37)),
                         (QPoint(2, 2), QPoint(5000, 5000))):
        bounds = floating.geometry()
        start = floating.mapToGlobal(local)
        pointer(floating, QEvent.MouseButtonPress, local, start, Qt.LeftButton, Qt.LeftButton)
        pointer(floating, QEvent.MouseMove, local + delta, start + delta, Qt.NoButton, Qt.LeftButton)
        pointer(floating, QEvent.MouseButtonRelease, local, start + delta, Qt.LeftButton, Qt.NoButton)
        if delta.x() == 61:
            assert floating.width() > bounds.width() and floating.height() > bounds.height()
            assert abs(floating.height() - floating.width() / floating.aspect) <= 1
        else:
            assert floating.size() == floating.minimumSize()
            assert floating.geometry().bottomRight() == bounds.bottomRight()
    floating.setGeometry(bounds)
    QTest.qWait(50)


def check_audio_controls(pip):
    floating, wall = pip.floating, pip.host.wall
    tiles = list(wall.picture_in_picture_tiles)
    original = [(tile.volume, tile.muted) for tile in tiles]
    other = next(tile for tile in wall.tiles if tile not in tiles)
    other_audio = other.volume, other.muted
    panel = floating.audio_panel
    try:
        with patch.object(floating, '_pointer_over', return_value=True):
            floating._poll_tools()
        assert floating.audio_tools.isVisible()
        floating.audio_button.click()
        assert panel.isVisible() and panel.scroll.isVisible()
        assert not any('鼠标指向画面' in label.text() for label in panel.findChildren(QLabel))
        assert set(panel.rows) == set(tiles)
        assert [(tile.volume, tile.muted) for tile in tiles] == original
        from ddm.ui import VolumeButton
        assert all(row.slider.value() == tile.volume and row.mute.muted == tile.muted
                   and isinstance(row.mute, VolumeButton) and row.mute.text() == ''
                   and row.mute.audio_channel == tile.audio_channel
                   for tile, row in panel.rows.items())
        row = panel.rows[tiles[0]]
        assert row.avatar.toolTip() == str(tiles[0].room['uname'])
        assert max(widget.geometry().center().y() for widget in (row.avatar, row.mute, row.slider, row.value)) - min(
            widget.geometry().center().y() for widget in (row.avatar, row.mute, row.slider, row.value)) <= 1
        assert row.height() <= 32, 'An avatar and all audio controls must share one compact row'
        item = next(item for item in pip.host.sidebar._items if item.room['room_id'] == tiles[0].room['room_id'])
        face = QPixmap(32, 32)
        face.fill(QColor('#24a7b4'))
        item.thumb.set_face(face)
        panel.refresh()
        assert row.avatar.pixmap() is not None and not row.avatar.pixmap().isNull()
        previous_face = row.avatar.pixmap().cacheKey()
        face.fill(QColor('#d9a244'))
        item.thumb.set_face(face)
        panel.refresh()
        assert row.avatar.pixmap().cacheKey() != previous_face, 'Newly loaded avatars must update without reopening'
        assert floating.screen().availableGeometry().contains(panel.geometry())
        # Capture actual alpha: transparent corners and a translucent body,
        # including the scroll viewport rather than an opaque inner rectangle.
        for mode in ('light', 'dark'):
            pip.host.set_appearance(mode)
            QTest.qWait(30)
            panel.refresh()
            image = panel.grab().toImage()
            scale = panel.devicePixelRatioF()
            assert image.pixelColor(0, 0).alpha() == 0
            for point in (QPoint(6, 40), panel.rows[tiles[0]].mapTo(panel, QPoint(100, 3))):
                alpha = image.pixelColor(round(point.x() * scale), round(point.y() * scale)).alpha()
                assert 100 < alpha < 245, (mode, point, alpha)
            assert panel.property('appearanceLight') == (mode == 'light')
            if '--audio-preview' in sys.argv:
                output = ROOT / 'work/pip-previews'
                output.mkdir(parents=True, exist_ok=True)
                panel.grab().save(str(output / f'audio-{mode}.png'))
        if '--audio-preview' in sys.argv:
            output = ROOT / 'work/pip-previews'
            output.mkdir(parents=True, exist_ok=True)
            panel.grab().save(str(output / 'audio-expanded.png'))
            floating.tools.grab().save(str(output / 'audio-toolbar.png'))
        row = panel.rows[tiles[0]]
        row.slider.setValue(65)
        assert tiles[0].volume == 65 and not tiles[0].muted
        row.mute.click()
        assert tiles[0].muted
        tiles[0].set_volume(40)
        panel.refresh()
        assert row.slider.value() == 40 and not row.mute.muted
        # Compare the real controls, including Qt's accumulated wheel deltas
        # and modifier behavior; the speaker's own wheel remains its 5-step.
        for delta, modifiers in ((120, Qt.NoModifier), (-120, Qt.NoModifier),
                                 (240, Qt.NoModifier), (120, Qt.ControlModifier)):
            for pip_control, monitor_control in ((row.slider, tiles[0].volume_slider),
                                                  (row.mute, tiles[0].volume_button)):
                tiles[0].set_volume(40)
                panel.refresh()
                wheel(monitor_control, delta, modifiers, direct=True)
                expected = tiles[0].volume
                tiles[0].set_volume(40)
                panel.refresh()
                wheel(pip_control, delta, modifiers)
                assert tiles[0].volume == expected, (type(pip_control), delta, modifiers, expected, tiles[0].volume)
        assert (other.volume, other.muted) == other_audio
        bounds, order = floating.geometry(), list(pip.selection)
        floating.tools.reorder.setChecked(True)
        QTest.mouseClick(row.slider, Qt.LeftButton, pos=row.slider.rect().center())
        assert floating.geometry() == bounds and pip.selection == order
        floating.tools.reorder.setChecked(False)
        QTest.keyClick(row.slider, Qt.Key_Escape)
        assert pip.active and not panel.isVisible(), 'Esc must close the panel before returning'
        # Deliver shortcuts to a PiP video without moving the desktop pointer.
        with patch.object(floating, '_tile_at', return_value=tiles[0]), patch.object(floating, '_pointer_over', return_value=True):
            before = tiles[0].volume
            QTest.keyClick(tiles[0].video, Qt.Key_Up)
            assert tiles[0].volume == min(100, before + 5)
            from PySide6.QtGui import QKeySequence
            QTest.keySequence(tiles[0].video, QKeySequence(pip.host.shortcuts['solo']))
            assert not tiles[0].muted and tiles[1].muted
        assert (other.volume, other.muted) == other_audio, 'Solo must leave unselected rooms alone'
    finally:
        panel.hide()
        floating.audio_feedback.hide()
        for tile, (volume, muted) in zip(tiles, original):
            tile.set_volume(volume)
            tile.set_muted(muted)


def check_move_burst(pip):
    floating = pip.floating
    surface = pip.host.wall.visible_tiles()[0].video
    bounds = floating.geometry()
    start = surface.mapToGlobal(surface.rect().center())
    with patch.object(floating, '_pointer_over', return_value=True):
        floating._poll_tools()
        assert floating.tools.isVisible() and floating.audio_tools.isVisible()
        pointer(surface, QEvent.MouseButtonPress, surface.mapFromGlobal(start), start, Qt.LeftButton, Qt.LeftButton)
        assert not floating.tools.isVisible() and not floating.audio_tools.isVisible()
        with patch.object(floating.tools, 'move', wraps=floating.tools.move) as tools_move, \
                patch.object(floating.audio_tools, 'move', wraps=floating.audio_tools.move) as audio_move:
            source_geometry = None
            for delta in (QPoint(13, 7), QPoint(-55, 29), QPoint(86, -14), QPoint(21, 18)):
                target = start + delta
                pointer(surface, QEvent.MouseMove, surface.mapFromGlobal(target), target, Qt.NoButton, Qt.LeftButton)
                floating._poll_tools()  # The hover timer must not reveal or move tools during a drag.
                presented = floating._live_move.preview if floating._live_move is not None else floating
                assert presented.pos() == bounds.topLeft() + delta and presented.size() == bounds.size()
                if floating._live_move is not None:
                    if source_geometry is None:
                        source_geometry = floating.geometry()
                    assert floating.geometry() == source_geometry, 'All source video windows must remain still during movement'
                assert not floating.tools.isVisible() and not floating.audio_tools.isVisible()
            tools_move.assert_not_called()
            audio_move.assert_not_called()
            target = start + QPoint(29, 24)
            pointer(surface, QEvent.MouseButtonRelease, surface.mapFromGlobal(target), target, Qt.LeftButton, Qt.NoButton)
            assert floating.pos() == bounds.topLeft() + QPoint(29, 24), 'Release must apply the final pointer position'
            QTest.qWait(120)
            assert floating.tools.isVisible() and floating.audio_tools.isVisible()
            assert tools_move.call_count == audio_move.call_count == 1
        assert floating._gesture is None and QWidget.mouseGrabber() is not floating
        assert floating._live_move is None
    floating.setGeometry(bounds)
    QTest.qWait(30)


def check_native_corners(pip):
    """Optional real compositor evidence over a controlled local backdrop."""
    floating = pip.floating
    assert floating._native_rounding
    previous = floating.geometry()
    backdrop = QWidget(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    backdrop.setAttribute(Qt.WA_ShowWithoutActivating)
    backdrop.setStyleSheet('background: #ff00ff;')
    previous_cursor = QCursor.pos()
    try:
        floating.resize_to_width(480)
        origin = floating.screen().availableGeometry().topLeft() + QPoint(36, 36)
        backdrop.setGeometry(QRect(origin, floating.size() + QSize(48, 48)))
        backdrop.show()
        floating.move(origin + QPoint(24, 24))
        floating.raise_()
        QTest.qWait(350)
        position = floating.pos()
        image = floating.screen().grabWindow(0, position.x(), position.y(), floating.width(), floating.height()).toImage()
        output = ROOT / 'work/pip-previews'
        output.mkdir(parents=True, exist_ok=True)
        image.save(str(output / ('native-rounded-' + os.environ.get('QT_SCALE_FACTOR', '1') + '.png')))
        # Local blue video against magenta: fractional red and green together
        # identify compositor blending, rather than a two-color region staircase.
        scale = floating.devicePixelRatioF()
        edge = round(12 * scale)
        for left, top in ((0, 0), (image.width() - edge, 0),
                          (0, image.height() - edge), (image.width() - edge, image.height() - edge)):
            corner = image.copy(left, top, edge, edge)
            colors = [corner.pixelColor(x, y) for y in range(corner.height()) for x in range(corner.width())]
            assert any(10 < color.red() < 230 and 10 < color.green() < 160 and color.blue() > 190 for color in colors), ('Actual desktop corners must include alpha-blended video', left, top)
        # Real HWND hit testing must survive a missing QWidget lookup (native
        # video / transparent Quick windows), including after toggling pin.
        backdrop.hide()
        with patch('ddm.picture_in_picture.QApplication.widgetAt', return_value=None):
            QCursor.setPos(floating.mapToGlobal(floating.rect().center()))
            QTest.qWait(150)
            assert floating._pointer_over() and floating.tools.isVisible()
            for pinned in (False, True):
                QCursor.setPos(floating.pin.mapToGlobal(floating.pin.rect().center()))
                floating.pin.click()
                QTest.qWait(150)
                assert pip.pinned is pinned and floating.tools.isVisible()
            QCursor.setPos(origin + QPoint(2, 2))
            QTest.qWait(150)
            assert not floating.tools.isVisible()
            QCursor.setPos(floating.mapToGlobal(floating.rect().center()))
            QTest.qWait(150)
            assert floating.tools.isVisible(), 'Re-entering native video must restore all icons'
    finally:
        QCursor.setPos(previous_cursor)
        floating.setGeometry(previous)
        backdrop.close()
        backdrop.deleteLater()
        QTest.qWait(80)


def check_resize_burst(pip, wall):
    floating = pip.floating
    bounds = floating.geometry()
    local = floating.rect().bottomRight() - QPoint(2, 2)
    start = floating.mapToGlobal(local)
    pointer(floating, QEvent.MouseButtonPress, local, start, Qt.LeftButton, Qt.LeftButton)
    with patch.object(floating, 'setGeometry', wraps=floating.setGeometry) as apply_geometry:
        for offset in range(1, 121):
            delta = QPoint(offset, round(offset / floating.aspect))
            pointer(floating, QEvent.MouseMove, local + delta, start + delta, Qt.NoButton, Qt.LeftButton)
        assert apply_geometry.call_count == 0, 'Pointer bursts must retain one latest geometry until the frame timer or release'
        assert floating._geometry_timer.isActive()
        pointer(floating, QEvent.MouseButtonRelease, local + delta, start + delta, Qt.LeftButton, Qt.NoButton)
        assert apply_geometry.call_count == 1, 'Releasing the pointer must apply the latest size exactly once'
    assert floating._pending_geometry is None and not floating._geometry_timer.isActive()
    assert wall.geometry() == floating.rect(), 'Wall geometry must be synchronized when resizing returns'
    selected = wall.picture_in_picture_tiles
    expected = pane_rectangles(len(selected), wall.rect(), pip.columns,
                               wall.picture_in_picture_aspects, wall.picture_in_picture_primary)
    assert [tile.geometry() for tile in selected] == expected
    # This checks event coalescing and geometry consistency, not live-stream FPS
    # or compositor tearing. The user's native trace is separate evidence.
    floating.setGeometry(bounds)
    QTest.qWait(50)


def check_native_system_move(pip):
    from ddm.picture_in_picture_resize import LiveMove
    floating = pip.floating
    live = LiveMove(floating)
    floating._live_move = live
    floating._gesture = (QPoint(), floating.geometry(), Qt.Edges())
    api = live.user32 = Mock()
    try:
        floating.grabMouse()
        api.GetAsyncKeyState.return_value = 0
        assert not live.run_system_move()
        assert QWidget.mouseGrabber() is floating
        destination = floating.geometry().translated(47, 21)
        def native_loop(*_args):
            assert live.system_moving and QWidget.mouseGrabber() is not floating
            floating._escape()
            assert pip.active, 'The native loop owns Esc while moving'
            live.preview.setGeometry(destination)
        api.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 1 else 0
        api.SendMessageW.side_effect = native_loop
        assert live.run_system_move() and not live.system_moving
        assert live.preview.geometry() == destination
        assert api.SendMessageW.call_args.args[1:] == (0x0112, 0xF012, 0)
        api.GetAsyncKeyState.side_effect = lambda _key: 0x8000
        assert live.run_system_move()
        assert live.preview.geometry() == floating._gesture[1], 'Esc must cancel the move rather than close PiP'
    finally:
        floating._gesture = None
        floating.releaseMouse()
        live.stop()


def check_quick_mask_batch():
    from ddm.video_danmaku_quick import _MovingDanmakuWindow
    window = _MovingDanmakuWindow()
    window.resize(240, 120)
    base = QRegion(0, 0, 240, 120)
    window.setMask(base)
    window.begin_mask_batch()
    window.begin_move(1, QRegion(10, 10, 30, 30))
    window.begin_move(2, QRegion(80, 10, 30, 30))
    assert window.mask() == base, 'A batch must preserve the current native clip until the group is ready'
    window.end_mask_batch()
    assert not window.mask().contains(QPoint(20, 20)) and not window.mask().contains(QPoint(90, 20))
    assert window.mask().contains(QPoint(200, 100)), 'The final clip must retain unaffected areas'
    window.cancel_move(1)
    window.cancel_move(2)
    assert window.mask() == base
    window.deleteLater()


def drag_pane(floating, source, target):
    start = source.mapToGlobal(source.rect().center())
    end = target.mapToGlobal(target.rect().center())
    pointer(source.video, QEvent.MouseButtonPress, source.video.rect().center(), start, Qt.LeftButton, Qt.LeftButton)
    pointer(floating, QEvent.MouseMove, floating.mapFromGlobal(end), end, Qt.NoButton, Qt.LeftButton)
    pointer(floating, QEvent.MouseButtonRelease, floating.mapFromGlobal(end), end, Qt.LeftButton, Qt.NoButton)


def check_reordering(pip, players):
    floating, wall = pip.floating, pip.host.wall
    original = list(pip.selection)
    wall_order = list(wall.tiles)
    selected = list(wall.picture_in_picture_tiles)
    primary = pip.primary
    origin = floating.pos()
    cores = [player.player for player in players]
    handles = [int(tile.video.winId()) for tile in selected]
    audio = [(tile.volume, tile.muted, tile.audio_channel) for tile in selected]
    assert not floating.tools.reorder.isChecked()
    floating.tools.reorder.click()
    assert floating.tools.reorder.isChecked()
    drag_pane(floating, selected[0], selected[1])
    assert pip.selection[:2] == original[:2][::-1]
    assert floating.pos() == origin and wall.tiles == wall_order
    assert [player.player for player in players] == cores
    assert [int(tile.video.winId()) for tile in selected] == handles
    assert [(tile.volume, tile.muted, tile.audio_channel) for tile in selected] == audio
    assert not floating._geometry_timer.isActive(), 'Reordering must not queue a window move or resize'
    assert pip.state()['selection'] == pip.selection
    check_resize_burst(pip, wall)
    assert floating.tools.reorder.isChecked(), 'Outer-edge resizing must remain available in reorder mode'
    if pip.columns == FOCUS_LAYOUT and primary in original[:2]:
        expected_primary = original[1] if primary == original[0] else original[0]
        assert pip.primary == expected_primary
    pip.manage()
    assert pip.dialog._selected() == pip.selection
    pip.dialog.start.click()
    assert pip.selection[:2] == original[:2][::-1], 'Applying the same picker must preserve the dragged order'
    source = selected[0]
    start = source.mapToGlobal(source.rect().center())
    for end in (start + QPoint(1, 1), floating.mapToGlobal(floating.rect().bottomRight() + QPoint(30, 30))):
        before = list(pip.selection)
        pointer(source.video, QEvent.MouseButtonPress, source.video.rect().center(), start, Qt.LeftButton, Qt.LeftButton)
        pointer(floating, QEvent.MouseMove, floating.mapFromGlobal(end), end, Qt.NoButton, Qt.LeftButton)
        pointer(floating, QEvent.MouseButtonRelease, floating.mapFromGlobal(end), end, Qt.LeftButton, Qt.NoButton)
        assert pip.selection == before and floating.pos() == origin
    pointer(source.video, QEvent.MouseButtonPress, source.video.rect().center(), start, Qt.LeftButton, Qt.LeftButton)
    QCoreApplication.sendEvent(floating, QEvent(QEvent.UngrabMouse))
    assert floating._reorder_drag is None, 'Lost mouse capture must cancel pending swaps'
    floating.releaseMouse()
    drag_pane(floating, selected[0], selected[1])
    assert pip.selection == original and pip.primary == primary
    floating.tools.reorder.click()
    assert not floating.tools.reorder.isChecked()
    bounds = floating.geometry()
    start = selected[0].mapToGlobal(selected[0].rect().center())
    pointer(selected[0].video, QEvent.MouseButtonPress, selected[0].video.rect().center(), start, Qt.LeftButton, Qt.LeftButton)
    pointer(floating, QEvent.MouseMove, floating.mapFromGlobal(start + QPoint(23, 17)), start + QPoint(23, 17), Qt.NoButton, Qt.LeftButton)
    pointer(floating, QEvent.MouseButtonRelease, floating.mapFromGlobal(start + QPoint(23, 17)), start + QPoint(23, 17), Qt.LeftButton, Qt.NoButton)
    assert floating.geometry() == bounds.translated(23, 17) and pip.selection == original
    floating.setGeometry(bounds)


def check_buffer_scale(pip):
    floating = pip.floating
    previous = floating.geometry()
    for width in (400, floating.minimumWidth()):
        floating.resize_to_width(width)
        for tile in pip.host.wall.visible_tiles():
            tile.set_buffering(True)
            indicator = tile.spinner
            assert 0 < indicator._presentation_scale <= .75
            assert indicator.width() <= max(1, tile.width() - 12) + 1
            assert indicator.height() <= max(1, tile.height() - 12) + 1
            assert abs(indicator.width() - indicator.natural_size().width() * indicator._presentation_scale) <= 1
            assert abs(indicator.height() - indicator.natural_size().height() * indicator._presentation_scale) <= 1
            assert tile.pause_overlay._presentation_scale == 1, 'Pause presentation was not requested to change'
            tile.set_buffering(False)
    floating.setGeometry(previous)


def check_live_resize(pip, players, layer):
    """Native regression of live composition; this is not a performance benchmark."""
    from ddm.picture_in_picture_resize import LiveResize
    from shiboken6 import isValid
    floating = pip.floating
    previous = floating.geometry()
    if '--live-resize' in sys.argv:
        floating.move(floating.screen().availableGeometry().topLeft() + QPoint(40, 40))
    bounds = floating.geometry()
    local = floating.rect().bottomRight() - QPoint(2, 2)
    start = floating.mapToGlobal(local)
    cores = [player.player for player in players]
    tiles = pip.host.wall.visible_tiles()
    handles = [int(tile.video.winId()) for tile in tiles]
    positions = [player._prop('time-pos') for player in players]
    sizes = [tile.video.size() for tile in tiles]
    try:
        pointer(floating, QEvent.MouseButtonPress, local, start, Qt.LeftButton, Qt.LeftButton)
        delta = QPoint(90, round(90 / floating.aspect))
        pointer(floating, QEvent.MouseMove, local + delta, start + delta, Qt.NoButton, Qt.LeftButton)
        floating._flush_geometry()
        live = floating._live_resize
        assert live is not None and live.preview.isVisible()
        assert floating.size() == bounds.size(), 'The live source must keep its playback size during dragging'
        assert floating.saveGeometry() == live.preview.saveGeometry(), 'Persist the on-screen geometry, not the parked source'
        QTest.qWait(150)
        floating._poll_tools()
        assert not floating.tools.isVisible(), 'Resize must not leave detached floating controls'
        expected_sources = {int(floating.winId()), int(layer.window.winId())}
        expected_sources.update(int(tile.video_danmaku.super_chat_overlay.winId()) for tile in tiles)
        assert expected_sources <= live.thumbnails.keys(), 'Video, Quick comments and SC must all be composed'
        image = None
        for index, width in enumerate((bounds.width() + 150, bounds.width() + 40, bounds.width() + 100)):
            live.set_geometry(QRect(bounds.topLeft(), QSize(width, round(width / floating.aspect))))
            QTest.qWait(140)
            assert floating.size() == bounds.size()
            assert [tile.video.size() for tile in tiles] == sizes
            if '--live-resize' in sys.argv:
                point = live.preview.pos()
                image = live.preview.screen().grabWindow(0, point.x(), point.y(), live.preview.width(), live.preview.height()).toImage()
                output = ROOT / 'work/pip-previews'
                output.mkdir(parents=True, exist_ok=True)
                image.save(str(output / f'live-resize-{index}.png'))
        assert all(player._prop('time-pos') > position + .2 for player, position in zip(players, positions)), 'Playback must continue during live scaling'
        if image is not None:
            QTest.qWait(250)
            next_image = live.preview.screen().grabWindow(0, point.x(), point.y(), live.preview.width(), live.preview.height()).toImage()
            area = QRect(0, image.height() * 2 // 3, image.width() // 2, image.height() // 3)
            assert image.copy(area) != next_image.copy(area), 'At a fixed output size, the video pixels must advance rather than display one frozen screenshot'
        assert [player.player for player in players] == cores
        assert [int(tile.video.winId()) for tile in tiles] == handles
        target = live.preview.geometry()
        live.finish()
        assert floating.geometry() == target
        # A second press while the final swapchains settle must remain usable.
        point = target.topLeft() + QPoint(20, 20)
        pointer(live.preview, QEvent.MouseButtonPress, QPoint(20, 20), point, Qt.LeftButton, Qt.LeftButton)
        assert floating._live_resize is None
        pointer(floating, QEvent.MouseButtonRelease, QPoint(20, 20), point, Qt.LeftButton, Qt.NoButton)
        QTest.qWait(120)
        assert not live.thumbnails and not isValid(live.preview)
        with patch.object(floating, '_pointer_over', return_value=True):
            floating._poll_tools()
        assert floating.tools.isVisible()
        # Exercise the actual release path, including a pending final pointer.
        local = floating.rect().bottomRight() - QPoint(2, 2)
        start = floating.mapToGlobal(local)
        pointer(floating, QEvent.MouseButtonPress, local, start, Qt.LeftButton, Qt.LeftButton)
        delta = QPoint(70, round(70 / floating.aspect))
        pointer(floating, QEvent.MouseMove, local + delta, start + delta, Qt.NoButton, Qt.LeftButton)
        floating._flush_geometry()
        live = floating._live_resize
        with patch.object(floating, 'setGeometry', wraps=floating.setGeometry) as apply_geometry:
            for offset in (60, 20, 80):
                delta = QPoint(offset, round(offset / floating.aspect))
                pointer(floating, QEvent.MouseMove, local + delta, start + delta, Qt.NoButton, Qt.LeftButton)
                floating._flush_geometry()
            assert apply_geometry.call_count == 0, 'Dragging must resize only the compositor destination'
            pointer(floating, QEvent.MouseButtonRelease, local + delta, start + delta, Qt.LeftButton, Qt.NoButton)
            assert apply_geometry.call_count == 1, 'Apply one final native player resize on release'
        target = live.preview.geometry()
        assert floating.geometry() == target
        QTest.qWait(140)
        assert floating._live_resize is None and not live.thumbnails
        # Failed registration keeps the original live resize path.
        failed = LiveResize(floating)
        floating._live_resize = failed
        with patch.object(failed.dwm, 'DwmRegisterThumbnail', return_value=-1):
            assert not failed.begin()
        assert floating._live_resize is None and floating.geometry() == target
    finally:
        if floating._live_resize is not None:
            floating._live_resize.finish(immediate=True)
        floating._gesture = None
        floating.releaseMouse()
        floating.setGeometry(previous)
        QTest.qWait(100)


def exercise(app, window, native, directory):
    pip, wall = window.picture_in_picture, window.wall
    tiles = list(wall.tiles)
    surface_tracking = [(widget, widget.hasMouseTracking(), widget.cursor().shape())
                        for tile in tiles for widget in (tile, tile.video)]
    for tile in tiles:
        cover = QPixmap(32, 18)
        cover.fill(QColor('#36524c'))
        tile.set_cover(cover)
    original_layout = wall.layout_id
    original_ratios = wall.corner_ratios(), wall.layout_ratios()
    audio = [(tile.volume, tile.muted, tile.audio_channel) for tile in tiles]
    players = []
    layer = None
    if native:
        from ddm.player import TilePlayer
        from selfcheck_mpv import ready, pump
        for index, tile in enumerate(tiles[:2]):
            media = Path(directory) / f'local-{index}.mp4'
            size = '320x180' if index == 0 else '180x320'
            pattern = 'color=c=0x00aaff' if '--corners' in sys.argv else 'testsrc2'
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', f'{pattern}:s={size}:r=30' if pattern.startswith('color') else f'{pattern}=s={size}:r=30', '-t', '30',
                '-c:v', 'libx264', '-preset', 'ultrafast', str(media)], check=True, timeout=30)
            player = TilePlayer(tile.video, window, silent=True)
            player.freeze_watch = False
            player.play(str(media))
            player.set_muted(True)
            tile.set_video_active(True)
            window.players[tile] = player
            players.append(player)
            ready(app, player)
        cores = [player.player for player in players]
        generations = [player.state_generation for player in players]
        positions = [player._prop('time-pos') for player in players]
        handles = [int(tile.video.winId()) for tile in tiles]
        layer = wall.ensure_quick_danmaku_layer()
        assert layer is not None
        now = int(time.time())
        for tile in tiles[:2]:
            owner = tile.video_danmaku
            owner.set_active(True)
            owner.set_enabled(True)
            assert owner.add_event({'text': 'Local PiP comment'})
            owner.set_super_chats([dict(kind='super_chat', id='local-pip', uid='1', uname='Local',
                price=30, message='Local PiP SC', start_time=now, end_time=now + 120)])
        QTest.qWait(150)
    pip.manage()
    assert len(pip.dialog.checks) == 4
    for check in pip.dialog.checks.values():
        check.setChecked(False)
    assert not pip.dialog.start.isEnabled()
    for index, check in pip.dialog.checks.items():
        check.setChecked(index < 2)
    pip.dialog.start.click()
    QTest.qWait(150)
    assert pip.active and pip.placeholder.isVisible()
    assert window.isMinimized(), 'Opening PiP must minimize the main window after accepting the picker'
    assert pip.floating.isVisible() and not pip.floating.isMinimized()
    assert wall.window() is pip.floating and wall.visible_tiles() == tiles[:2]
    assert not any(tile.bottom.isVisible() for tile in tiles[:2])
    assert wall.layout_id == original_layout
    if native:
        assert abs(pip.aspects_for([0])[0] - 16 / 9) < .001
        assert abs(pip.aspects_for([1])[0] - 9 / 16) < .001
        if '--corners' in sys.argv:
            check_native_corners(pip)
    check_floating_style(pip, wall, tiles, layer)
    check_audio_controls(pip)
    check_move_burst(pip)
    if native:
        check_native_system_move(pip)
    check_resize_burst(pip, wall)
    check_reordering(pip, players)
    check_buffer_scale(pip)
    if native:
        for tile in wall.visible_tiles():
            tile.video_danmaku.add_event({'text': 'Local resize comment'})
        check_live_resize(pip, players, layer)
    pip.manage()
    pip.dialog.checks[3].setChecked(True)
    pip.dialog.reject()
    assert wall.visible_tiles() == tiles[:2], 'Cancel must retain the current composition'
    if layer is not None:
        assert layer.window.transientParent() is pip.floating.windowHandle()
        assert layer.items
        for tile in tiles[:2]:
            overlay = tile.video_danmaku.super_chat_overlay
            assert overlay.isVisible()
            assert overlay.windowHandle().transientParent() is pip.floating.windowHandle()
        pip.manage()
        pip.dialog.start.click()
        QTest.qWait(60)
        assert all(tile.video_danmaku.super_chat_overlay.isVisible() for tile in tiles[:2]), 'Applying an unchanged composition must retain SC'
        pip.manage()
        QTest.qWait(40)
        pip.dialog.reject()
        QTest.qWait(60)
        assert all(tile.video_danmaku.super_chat_overlay.isVisible() for tile in tiles[:2]), 'Cancel must restore SC after closing the modal picker'
    assert wall.corner_ratios() == original_ratios[0] and wall.layout_ratios() == original_ratios[1]
    for mode in ('light', 'dark'):
        window.set_appearance(mode)
        QTest.qWait(100)
        assert wall.geometry() == pip.floating.rect()
        assert all(tile.video.geometry() == tile.rect() for tile in tiles[:2])
        assert not pip.floating.property('presentationMask').contains(QPoint(0, 0))
    for size in ((360, 240), (440, 540), (800, 320)):
        pip.floating.resize(*size)
        QTest.qWait(50)
        assert wall.rect().contains(tiles[0].geometry()) and wall.rect().contains(tiles[1].geometry())
        assert not tiles[0].geometry().intersects(tiles[1].geometry())
        assert abs(pip.floating.height() - pip.floating.width() / pip.floating.aspect) <= 1
        for tile, aspect in zip(wall.visible_tiles(), wall.picture_in_picture_aspects):
            assert abs(tile.width() - tile.height() * aspect) <= 2
    visibility = VisibilityEvents()
    watched = (pip.floating, pip.floating.tools, *(tile.video for tile in tiles[:2]))
    for widget in watched:
        widget.installEventFilter(visibility)
    # Keep hover state stable so a genuine hide/show caused by pinning is visible.
    with patch.object(pip.floating, '_poll_tools'):
        for pinned in (False, True, False, True):
            visibility.events.clear()
            pip.floating.pin.click()
            QTest.qWait(25)
            assert pip.pinned is pinned and pip.floating.pin.isChecked() is pinned
            if not native:
                assert bool(pip.floating.windowHandle().flags() & Qt.WindowStaysOnTopHint) is pinned
            assert not visibility.events, 'Pinning must not hide, show or recreate the video/tool windows'
            assert ('已置顶' if pinned else '未置顶') in pip.floating.pin.toolTip()
            if native:
                import ctypes
                from ctypes import wintypes
                ctypes.windll.user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
                assert bool(ctypes.windll.user32.GetWindowLongW(int(pip.floating.winId()), -20) & 8) is pinned
    for widget in watched:
        widget.removeEventFilter(visibility)
    # An unchecked pin stays neutral even with the pointer left on it; blue
    # communicates pinned state, not hover or automatic activation.
    with patch('ddm.picture_in_picture.QCursor.pos', return_value=pip.floating.pin.mapToGlobal(QPoint(5, 12))):
        pip.floating.pin.setChecked(False)
        image = pip.floating.pin.grab().toImage()
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(5 * scale), round(12 * scale)).alpha() < 230
        pip.floating.pin.setChecked(True)
        image = pip.floating.pin.grab().toImage()
        assert image.pixelColor(round(5 * scale), round(12 * scale)) == theme.qcolor(theme.ACCENT)
    button = pip.floating.tools.reorder
    with patch('ddm.picture_in_picture.QCursor.pos', return_value=button.mapToGlobal(QPoint(5, 12))):
        assert not button.isChecked()
        image = button.grab().toImage()
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(5 * scale), round(12 * scale)) == theme.qcolor(theme.ACCENT), 'Reorder hover must match the neighboring controls'
    with patch('ddm.picture_in_picture.QCursor.pos', return_value=QPoint(-30000, -30000)):
        image = button.grab().toImage()
        assert image.pixelColor(round(5 * scale), round(12 * scale)).alpha() < 230
        button.setChecked(True)
        image = button.grab().toImage()
        assert image.pixelColor(round(5 * scale), round(12 * scale)) == theme.qcolor(theme.ACCENT), 'Enabled reorder mode must remain blue after the pointer leaves'
        button.setChecked(False)
    button = pip.floating.tools.manage
    with patch.object(button, 'underMouse', return_value=True), \
            patch.object(button, 'hasFocus', return_value=True), \
            patch('ddm.picture_in_picture.QCursor.pos', return_value=QPoint(-30000, -30000)):
        QApplication.sendEvent(button, QFocusEvent(QEvent.FocusIn, Qt.ActiveWindowFocusReason))
        image = button.grab().toImage()
        scale = image.devicePixelRatio()
        assert image.pixelColor(round(12 * scale), round(21 * scale)).alpha() < 230, 'Automatic tool-window focus must not light the composition icon'
        with patch.object(pip.floating, '_pointer_over', return_value=False):
            pip.floating._poll_tools()
            assert not pip.floating.tools.isVisible(), 'Automatic focus must not pin the hover tools open'
        QApplication.sendEvent(button, QFocusEvent(QEvent.FocusIn, Qt.TabFocusReason))
        image = button.grab().toImage()
        assert image.pixelColor(round(12 * scale), round(21 * scale)).alpha() > 230, 'Keyboard focus must remain visible'
        QApplication.sendEvent(button, QFocusEvent(QEvent.FocusOut, Qt.ActiveWindowFocusReason))
    player = window.players.get(tiles[0])
    before_aspects = list(wall.picture_in_picture_aspects)
    window.players[tiles[0]] = Mock(_prop=lambda name: {'dw': 800, 'dh': 600})
    pip._refresh_aspects()
    QTest.qWait(50)
    assert wall.picture_in_picture_aspects[0] == 4 / 3
    assert abs(tiles[0].width() - tiles[0].height() * 4 / 3) <= 2
    # Missing metadata while the same room reconnects retains its known ratio.
    window.players[tiles[0]] = Mock(_prop=lambda name: None)
    pip._refresh_aspects()
    assert wall.picture_in_picture_aspects[0] == 4 / 3
    if player is None:
        window.players.pop(tiles[0])
    else:
        window.players[tiles[0]] = player
    pip._video_aspects.pop(tiles[0])
    pip._refresh_aspects()
    assert wall.picture_in_picture_aspects == before_aspects
    with patch.object(window._tray, 'available', return_value=True), patch.object(window._tray, 'icon', Mock()):
        window._tray.hide()
    QTest.qWait(50)
    assert not window._tray.playback_suspended
    assert pip.floating.isVisible() and all(tile.isVisible() for tile in tiles[:2])
    window.showNormal()
    pip.manage()
    for index, check in pip.dialog.checks.items():
        check.setChecked(index in (1, 3))
    pip.dialog.start.click()
    QTest.qWait(80)
    assert wall.visible_tiles() == [tiles[1], tiles[3]]
    assert not window.isMinimized(), 'Editing an existing PiP must not minimize the main window again'
    state = window.current_state()
    assert state['ui']['picture_in_picture']['selection'] == [1, 3]
    assert [row['room_id'] for row in state['wall']] == [tile.room['room_id'] for tile in tiles]
    panel = pip.floating.audio_panel
    panel.toggle()
    panel.rows[tiles[1]].slider.setValue(73)
    panel.rows[tiles[1]].mute.click()
    assert window.current_state()['wall'][1]['volume'] == 73
    panel.hide()
    pip.restore()
    QTest.qWait(100)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not pip.active and wall.parentWidget() is window._content
    assert wall.visible_tiles() == tiles and all(tile.bottom.isVisible() for tile in tiles)
    assert wall.layout_id == original_layout and (wall.corner_ratios(), wall.layout_ratios()) == original_ratios
    assert tiles[1].volume == 73 and tiles[1].muted, 'Returning must retain PiP audio edits in the monitor'
    if native:
        assert window.players[tiles[1]].volume == 73
    tiles[1].set_volume(audio[1][0])
    tiles[1].set_muted(audio[1][1])
    assert all((widget.hasMouseTracking(), widget.cursor().shape()) == (tracking, cursor)
               for widget, tracking, cursor in surface_tracking)
    assert [(tile.volume, tile.muted, tile.audio_channel) for tile in tiles] == audio
    if layer is not None:
        assert layer.window.transientParent() is window.windowHandle()
    pip.start([0, 1], 1)
    QTest.qWait(80)
    assert tiles[0].y() < tiles[1].y() and tiles[0].x() == tiles[1].x()
    pip.floating.tools.back.click()
    QTest.qWait(80)
    assert not pip.active and window.isVisible()
    assert not window.isMinimized(), 'Closing PiP must restore the main window'
    # Minimized/tray-hidden lifecycle needs a native window manager.
    if native:
        pip.start([0, 1], 0)
        QTest.qWait(80)
        assert window.isMinimized()
        pip.floating.tools.close_only.click()
        QTest.qWait(80)
        assert not pip.active and window.isMinimized(), 'Close-only must keep the main window minimized'
        window.showNormal()
        pip.start([0, 1], 0)
        QTest.qWait(80)
        with patch.object(window._tray, 'available', return_value=True), patch.object(window._tray, 'icon', Mock()):
            window._tray.hide()
        assert not window.isVisible()
        pip.floating.tools.close_only.click()
        QTest.qWait(80)
        assert not pip.active and not window.isVisible(), 'Close-only must not wake a tray-hidden monitor'
        window.showNormal()
    if native:
        pump(app, .2)
        assert [player.player for player in players] == cores
        assert [player.state_generation for player in players] == generations
        assert [int(tile.video.winId()) for tile in tiles] == handles
        assert all(player._prop('vo-configured') for player in players)
        assert all(player._prop('time-pos') > before for player, before in zip(players, positions))
    window.start_tile.assert_not_called()
    pip.start([0], 0)
    window.close()
    QTest.qWait(50)
    assert not pip.active and all(player._released for player in players)


def check_focus_geometry():
    profiles = ([16 / 9] * 6, [9 / 16] * 6,
                [16 / 9, 9 / 16, 4 / 3, 1, 9 / 16, 32 / 9])
    for aspects in profiles:
        for primary in range(6):
            ratio = composition_ratio(aspects, FOCUS_LAYOUT, primary)
            for width in (320, 641, 1280):
                area = QRect(7, 11, width, round(width / ratio))
                rectangles = pane_rectangles(6, area, FOCUS_LAYOUT, aspects, primary)
                assert all(area.contains(rect) and not rect.isEmpty() for rect in rectangles)
                assert not any(a.intersects(b) for index, a in enumerate(rectangles) for b in rectangles[index + 1:])
                assert sum(rect.width() * rect.height() for rect in rectangles) >= area.width() * area.height() - area.width() - area.height()
                assert all(min(abs(rect.width() - rect.height() * value), abs(rect.height() - rect.width() / value)) <= 2
                           for rect, value in zip(rectangles, aspects)), 'Focus layout must preserve each display aspect, including a portrait primary'
                assert rectangles[primary].topLeft() == QPoint(min(rect.left() for rect in rectangles), min(rect.top() for rect in rectangles))
    area = QRect(0, 0, 960, 540)
    for primary in range(6):
        rectangles = pane_rectangles(6, area, FOCUS_LAYOUT, primary=primary)
        assert rectangles[primary] == QRect(0, 0, 640, 360)
        assert all(rect.size() == QSize(320, 180) for index, rect in enumerate(rectangles) if index != primary)


def exercise_focus(app, native, directory):
    rooms = [dict(room_id=str(2200 + index), uname=f'Focus {index}', live=False, muted=True) for index in range(6)]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='3x2',
        state={'plugins_enabled': [], 'ui': {'picture_in_picture': {
            'selection': list(range(6)), 'columns': FOCUS_LAYOUT, 'primary': 4}},
            'settings': {'close_behavior': 'exit', 'auto_quality': False, 'auto_update': False,
                         'recording_enabled': False, 'recording_replay_enabled': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.setGeometry(-12000, 0, 1100, 750)
    window.show()
    pip, wall = window.picture_in_picture, window.wall
    tiles = list(wall.tiles)
    players = []
    try:
        if native:
            from ddm.player import TilePlayer
            from selfcheck_mpv import ready
            for index, tile in enumerate(tiles[:2]):
                player = TilePlayer(tile.video, window, silent=True)
                player.freeze_watch = False
                player.play(str(Path(directory) / f'local-{index}.mp4'))
                player.set_muted(True)
                tile.set_video_active(True)
                window.players[tile] = player
                players.append(player)
                ready(app, player)
        cores = [player.player for player in players]
        handles = [int(tile.video.winId()) for tile in tiles]
        positions = [player._prop('time-pos') for player in players]
        pip.manage()
        dialog = pip.dialog
        QTest.qWait(30)
        assert dialog.columns.currentData() == FOCUS_LAYOUT
        assert dialog.primary_row.isVisible() and dialog.primary.currentData() == 4
        assert dialog.rect().contains(dialog.start.geometry()) and dialog.start.isVisible()
        assert dialog.rect().contains(QRect(dialog.primary.mapTo(dialog, QPoint()), dialog.primary.size()))
        dialog.checks[5].setChecked(False)
        assert not dialog.start.isEnabled() and dialog.primary.count() == 5
        dialog.checks[5].setChecked(True)
        assert dialog.start.isEnabled() and dialog.primary.currentData() == 4
        dialog.primary.setCurrentIndex(dialog.primary.findData(0))
        assert dialog.preview.primary == 0 and dialog.preview.labels[0].text().startswith('主画面')
        dialog.start.click()
        QTest.qWait(100)
        assert pip.columns == FOCUS_LAYOUT and pip.primary == 0 and wall.picture_in_picture_primary == 0
        assert wall.visible_tiles() == tiles
        panel = pip.floating.audio_panel
        panel.toggle()
        QTest.qWait(30)
        assert len(panel.rows) == 6 and panel.height() < 320
        assert panel.scroll.verticalScrollBar().maximum() == 0, 'Six compact rows should fit without scrolling'
        if '--audio-preview' in sys.argv:
            for mode in ('light', 'dark'):
                window.set_appearance(mode)
                QTest.qWait(30)
                panel.grab().save(str(ROOT / 'work/pip-previews' / f'audio-six-{mode}.png'))
        panel.hide()
        before = [tile.geometry() for tile in tiles]
        pip.manage()
        pip.dialog.primary.setCurrentIndex(pip.dialog.primary.findData(1))
        pip.dialog.reject()
        assert pip.primary == 0 and [tile.geometry() for tile in tiles] == before
        pip.manage()
        pip.dialog.primary.setCurrentIndex(pip.dialog.primary.findData(1))
        pip.dialog.start.click()
        QTest.qWait(100)
        assert pip.primary == 1 and wall.picture_in_picture_primary == 1
        expected = pane_rectangles(6, wall.rect(), FOCUS_LAYOUT, pip.aspects_for(pip.selection), 1)
        assert [tile.geometry() for tile in tiles] == expected
        assert tiles[1].geometry().topLeft() == QPoint(0, 0)
        check_reordering(pip, players)
        check_buffer_scale(pip)
        check_resize_burst(pip, wall)
        assert [player.player for player in players] == cores
        assert [int(tile.video.winId()) for tile in tiles] == handles
        assert all(player._prop('time-pos') > position for player, position in zip(players, positions))
        state = window.current_state()['ui']['picture_in_picture']
        assert state['primary'] == 1 and state['columns'] == FOCUS_LAYOUT
        pip.restore()
        QTest.qWait(50)
        assert wall.tiles == tiles and wall.layout_id == '3x2'
        assert all(tile.spinner._presentation_scale == 1 for tile in tiles)
        pip.manage()
        assert pip.dialog.primary.currentData() == 1
        pip.dialog.reject()
    finally:
        window.close()
        QTest.qWait(100)
    assert not pip.active and all(player._released for player in players)


def exercise_live_room_picker(app, native, directory):
    rooms = [dict(room_id='2101', uname='Wall live', live=True),
             dict(room_id='2102', uname='Wall offline', live=False)]
    rooms += [dict(room_id=str(3100 + index), uname=f'Other {index}', live=True) for index in range(1, 6)]
    rooms += [dict(room_id='4101', uname='Offline', live=False),
              dict(room_id='4102', uname='Unknown', live=True, live_known=False)]
    window = MainWindow([dict(room) for room in rooms], [dict(room) for room in rooms[:2]], layout_id='2x2',
        state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit', 'auto_quality': False,
            'auto_update': False, 'recording_enabled': False, 'recording_replay_enabled': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.setGeometry(-12000, 0, 1100, 750)
    window.show()
    QTest.qWait(80)
    pip, wall = window.picture_in_picture, window.wall
    original_tiles = list(wall.tiles)
    original_state = window.current_state()['wall']
    original_layout = wall.layout_id, wall.layout_ratios(), wall.corner_ratios()
    try:
        pip.manage()
        dialog = pip.dialog
        assert list(dialog.checks) == [0, 1, '3101', '3102', '3103', '3104', '3105']
        assert [label.text() for label, _keys in dialog.sections] == ['已入墙', '其他已开播']
        assert dialog._selected() == [0, 1]
        assert not pip._extra_tiles and wall.tiles == original_tiles
        dialog.reject()
        assert window.current_state()['wall'] == original_state
        pip.manage()
        dialog = pip.dialog
        for rid in ('3101', '3102', '3103', '3104'):
            dialog.checks[rid].setChecked(True)
        dialog.columns.setCurrentIndex(dialog.columns.findData(FOCUS_LAYOUT))
        dialog.primary.setCurrentIndex(dialog.primary.findData('3102'))
        assert dialog.start.isEnabled() and dialog.preview.primary == 3
        dialog.search.setText('Other 2')
        assert dialog.checks[0].isHidden() and not dialog.checks['3102'].isHidden()
        assert len(dialog._selected()) == 6, 'Search must not unselect hidden rows'
        dialog.search.clear()
        dialog.start.click()
        QTest.qWait(50)
        assert pip.active and len(wall.picture_in_picture_tiles) == 6
        assert set(pip._extra_tiles) == {'3101', '3102', '3103', '3104'}
        assert wall.tiles[:len(original_tiles)] == original_tiles
        assert window.current_state()['wall'] == original_state
        assert pip.state()['selection'] == [0, 1]
        assert pip.state()['external_primary'] == '3102'
        assert pip.primary_choice() == '3102'
        window._refresh_meta()
        assert window.sidebar._wall_room_ids == {'2101', '2102'}
        removed = pip._extra_tiles['3101']
        retained = pip._extra_tiles['3102']
        retained.set_volume(73)
        retained.set_muted(False)
        old_player = None
        retained_player = None
        if native:
            from ddm.player import TilePlayer
            from selfcheck_mpv import ready
            old_player = TilePlayer(removed.video, window, silent=True)
            old_player.freeze_watch = False
            old_player.play(str(Path(directory) / 'local-0.mp4'))
            window.players[removed] = old_player
            ready(app, old_player)
            retained_player = TilePlayer(retained.video, window, silent=True)
            retained_player.freeze_watch = False
            retained_player.play(str(Path(directory) / 'local-0.mp4'))
            window.players[retained] = retained_player
            ready(app, retained_player)
            retained_core, retained_handle = retained_player.player, int(retained.video.winId())
        pip.manage()
        dialog = pip.dialog
        assert list(dialog.checks)[:2] == [0, 1]
        assert dialog.primary.currentData() == '3102'
        dialog.checks['3101'].setChecked(False)
        dialog.checks['3105'].setChecked(True)
        dialog.start.click()
        assert '3101' not in pip._extra_tiles and removed not in wall.tiles
        assert removed not in window.players
        if old_player is not None:
            assert old_player._released
        assert pip._extra_tiles['3102'] is retained and retained.volume == 73 and not retained.muted
        if retained_player is not None:
            assert window.players[retained] is retained_player and retained_player.player is retained_core
            assert int(retained.video.winId()) == retained_handle
        assert all(entry[0] not in (removed, removed.video) for entry in pip.floating._surface_state)
        assert pip.primary_choice() == '3102'
        assert len(wall.picture_in_picture_tiles) == 6
        pip.floating.audio_panel.rebuild()
        assert retained in pip.floating.audio_panel.rows
        assert pip.floating.audio_panel.rows[retained].slider.value() == 73
        pip.swap_positions(wall.picture_in_picture_tiles[0], pip._extra_tiles['3103'])
        assert pip.primary_choice() == '3102'
        choices_before_restore = pip.selected_choices()
        assert window.current_state()['wall'] == original_state
        pip.restore()
        if retained_player is not None:
            assert retained_player._released
        assert wall.tiles == original_tiles and not pip._extra_tiles
        assert (wall.layout_id, wall.layout_ratios(), wall.corner_ratios()) == original_layout
        assert window.current_state()['wall'] == original_state
        assert pip.external_primary == '3102'
        pip.manage()
        assert pip.dialog._selected() == choices_before_restore
        assert pip.dialog.primary.currentData() == '3102'
        pip.dialog.reject()
        assert not pip._extra_tiles
        # A follow can go offline while the non-modal picker is open.
        pip.manage()
        dialog = pip.dialog
        dialog.columns.setCurrentIndex(dialog.columns.findData(0))
        for check in dialog.checks.values():
            check.setChecked(False)
        dialog.checks['3101'].setChecked(True)
        room = next(room for room in window.sidebar.rooms() if room['room_id'] == '3101')
        room['live'] = False
        dialog.start.click()
        assert not pip.active and pip.dialog is dialog and not pip._extra_tiles
        dialog.reject()
        room['live'] = True
        assert pip.start(['3101'], primary='3101')
        pip.restore()
        assert not pip.selection and pip.external_rooms == ['3101']
        pip.manage()
        assert pip.dialog._selected() == ['3101'], 'An external-only composition must stay external-only'
        pip.dialog.reject()
        assert pip.start(['3101'], primary='3101')
        # Finishing capture sessions must retain their tile until the existing completion hook runs.
        temporary = pip._extra_tiles['3101']
        window.recorder.sessions[temporary] = Mock(stopping=True, recording=False)
        with patch.object(window.recorder, 'stop'):
            pip.restore()
        assert temporary in window._preset_retired_tiles and temporary not in wall.tiles
        window.recorder.sessions.pop(temporary)
        window._record_state_changed(temporary)
        assert temporary not in window._preset_retired_tiles
        assert pip.start(['3101'], primary='3101')
        window.close()
        app.processEvents()
        assert not pip.active and not pip._extra_tiles and wall.tiles == original_tiles
    finally:
        theme.signals().changed.disconnect()
        focused = app.focusWidget()
        if focused is not None:
            focused.clearFocus()
        window.close()
        QTest.qWait(100)
        app.processEvents()


def main():
    app = QApplication([])
    native = '--native' in sys.argv or app.platformName() == 'windows'
    if native:
        os.environ['DDM_QTQUICK_DANMAKU'] = '1'
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    check_quick_mask_batch()
    check_focus_geometry()
    if native:
        assert app.platformName() == 'windows'
    for count in range(1, 17):
        for columns in (0, 1, 2, 3, 16):
            for aspects in ([16 / 9] * count, [9 / 16 if index % 2 else 4 / 3 for index in range(count)]):
                aspect = composition_aspect(composition_rows(aspects, columns))
                area = QRect(0, 0, 1280, round(1280 / aspect))
                rectangles = pane_rectangles(count, area, columns, aspects)
                assert len(rectangles) == count and all(area.contains(rect) and not rect.isEmpty() for rect in rectangles)
                assert not any(first.intersects(second) for index, first in enumerate(rectangles) for second in rectangles[index + 1:])
                assert sum(rect.width() * rect.height() for rect in rectangles) >= area.width() * area.height() - area.width() - area.height(), 'Partial final rows must fill their width, without vacant grid slots'
                assert all(abs(rect.width() - rect.height() * ratio) <= 2 for rect, ratio in zip(rectangles, aspects))
    assert video_aspect(Mock(_prop=lambda name: {'w': 1440, 'h': 1080, 'dw': 1920, 'dh': 1080})) == 16 / 9
    assert video_aspect(Mock(_prop=lambda name: {'dw': 1920, 'dh': 1080, 'rotate': 90})) == 9 / 16
    assert video_aspect(Mock(_prop=lambda name: None)) is None
    with tempfile.TemporaryDirectory(prefix='ddm-pip-') as directory, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'REPO', directory))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(directory) / 'plugins')))
        stack.enter_context(patch.object(plugins.PluginManager, 'load'))
        for name in ('start_all', '_start_startup_tiles', 'start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                     'load_cached_covers', 'load_cached_avatars', 'load_room_avatars', 'sync_danmaku',
                     '_check_startup_update', '_check_startup_plugins'):
            stack.enter_context(patch.object(MainWindow, name))
        init = PictureInPictureWindow.__init__
        def background(floating, controller):
            init(floating, controller)
            floating.setAttribute(Qt.WA_ShowWithoutActivating)
            floating.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            floating.move(-15000, 0)
        stack.enter_context(patch.object(PictureInPictureWindow, '__init__', background))
        restore_geometry = PictureInPictureWindow.restoreGeometry
        def background_restore(floating, geometry):
            restored = restore_geometry(floating, geometry)
            floating.move(-15000, 0)  # Qt normally brings a saved off-screen window onto the desktop.
            return restored
        stack.enter_context(patch.object(PictureInPictureWindow, 'restoreGeometry', background_restore))
        init_dialog = PictureInPictureDialog.__init__
        def background_dialog(dialog, controller):
            init_dialog(dialog, controller)
            dialog.setAttribute(Qt.WA_ShowWithoutActivating)
            dialog.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
            dialog.move(-14000, 0)
        stack.enter_context(patch.object(PictureInPictureDialog, '__init__', background_dialog))
        # Do not restore/activate a real foreground window during the close test.
        from ddm.system_tray import SystemTray
        def restore_without_activation(tray):
            tray.window.setWindowState(tray.window.windowState() & ~Qt.WindowMinimized)
            tray.window.show()
        stack.enter_context(patch.object(SystemTray, 'restore', autospec=True, side_effect=restore_without_activation))
        rooms = [dict(room_id=str(1100 + index), uname=f'Local {index}', live=False,
                      muted=True, volume=20 + index * 10) for index in range(4)]
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='2x2',
            state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit', 'auto_quality': False,
                'auto_update': False, 'recording_enabled': False, 'recording_replay_enabled': False}})
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        window.setGeometry(-12000, 0, 1100, 750)
        window.show()
        QTest.qWait(100)
        try:
            exercise(app, window, native, directory)
        finally:
            window.close()
            app.processEvents()
        exercise_focus(app, native, directory)
        if native:
            # This case creates and retires native video surfaces from a picker.
            # The offscreen Qt backend crashes at teardown even with the baseline implementation.
            exercise_live_room_picker(app, native, directory)
    print('PASS: PiP selection, shared playback, resizing, pinning, independent visibility, restore and shutdown')


if __name__ == '__main__':
    main()
