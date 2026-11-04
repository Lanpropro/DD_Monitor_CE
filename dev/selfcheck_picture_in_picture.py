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

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import config, plugins, theme
from ddm.app import MainWindow
from ddm.picture_in_picture import PictureInPictureDialog, PictureInPictureWindow, pane_rectangles


def pointer(surface, kind, local, global_pos, button, buttons):
    event = QMouseEvent(kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(surface, event)


def check_floating_style(pip, wall, tiles, layer):
    floating = pip.floating
    assert floating.windowFlags() & Qt.FramelessWindowHint
    assert floating.box.contentsMargins().isNull() and floating.box.spacing() == 0
    assert wall.geometry() == floating.rect(), 'Video wall must fill the floating window'
    assert not floating.mask().contains(QPoint(0, 0))
    assert floating.mask().contains(floating.rect().center())
    for tile in tiles[:2]:
        assert tile.video.geometry() == tile.rect(), 'PiP video must have no border inset'
        tile.set_controls_visible(True)
        assert not any(widget.isVisible() for widget in
                       (tile.controls, tile.stream_badge, tile.title_badge, tile.time_badge))
        assert tile.video.square_corners and not any(corner.isVisible() for corner in tile.video_corners)
        assert tile.video.hasMouseTracking()
        if tile.cover.isVisible():
            assert tile.cover.pixmap().toImage().pixelColor(0, 0).alpha() == 255, 'Covers must join without rounded inner corners'
    with patch('ddm.picture_in_picture.QApplication.widgetAt', return_value=tiles[0].video):
        floating._poll_tools()
    assert floating.tools.isVisible()
    assert floating.tools.pos() == floating.mapToGlobal(QPoint(floating.width() - 88, 8))
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
            assert user32.GetWindowRgn(hwnd, region)
            assert not gdi32.PtInRegion(region, 0, 0)
            assert gdi32.PtInRegion(region, client.right // 2, client.bottom // 2)
        finally:
            gdi32.DeleteObject(region)
    assert all(button.text() == '' and button.toolTip() and button.accessibleName()
               for button in (floating.tools.manage, floating.pin, floating.tools.back))
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
    with patch('ddm.picture_in_picture.QApplication.widgetAt', return_value=None), \
            patch('ddm.picture_in_picture.QApplication.focusWidget', return_value=None):
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
            assert floating.size() == bounds.size() + QSize(61, 37)
        else:
            assert floating.size() == floating.minimumSize()
            assert floating.geometry().bottomRight() == bounds.bottomRight()
    floating.setGeometry(bounds)
    QTest.qWait(50)


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
        media = Path(directory) / 'local.mp4'
        subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '30',
            '-c:v', 'libx264', '-preset', 'ultrafast', str(media)], check=True, timeout=30)
        for tile in tiles[:2]:
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
    assert wall.window() is pip.floating and wall.visible_tiles() == tiles[:2]
    assert not any(tile.bottom.isVisible() for tile in tiles[:2])
    assert wall.layout_id == original_layout
    check_floating_style(pip, wall, tiles, layer)
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
        assert not pip.floating.mask().contains(QPoint(0, 0))
    for size in ((360, 240), (440, 540), (800, 320)):
        pip.floating.resize(*size)
        QTest.qWait(50)
        assert wall.rect().contains(tiles[0].geometry()) and wall.rect().contains(tiles[1].geometry())
        assert not tiles[0].geometry().intersects(tiles[1].geometry())
    pip.floating.pin.click()
    QTest.qWait(50)
    assert not (pip.floating.windowFlags() & Qt.WindowStaysOnTopHint)
    pip.floating.pin.click()
    QTest.qWait(50)
    with patch.object(window._tray, 'available', return_value=True), patch.object(window._tray, 'icon', Mock()):
        window._tray.hide()
    QTest.qWait(50)
    assert not window._tray.playback_suspended
    assert pip.floating.isVisible() and all(tile.isVisible() for tile in tiles[:2])
    window.show()
    pip.manage()
    for index, check in pip.dialog.checks.items():
        check.setChecked(index in (1, 3))
    pip.dialog.start.click()
    QTest.qWait(80)
    assert wall.visible_tiles() == [tiles[1], tiles[3]]
    state = window.current_state()
    assert state['ui']['picture_in_picture']['selection'] == [1, 3]
    assert [row['room_id'] for row in state['wall']] == [tile.room['room_id'] for tile in tiles]
    pip.restore()
    QTest.qWait(100)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not pip.active and wall.parentWidget() is window._content
    assert wall.visible_tiles() == tiles and all(tile.bottom.isVisible() for tile in tiles)
    assert wall.layout_id == original_layout and (wall.corner_ratios(), wall.layout_ratios()) == original_ratios
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


def main():
    app = QApplication([])
    native = '--native' in sys.argv or app.platformName() == 'windows'
    if native:
        os.environ['DDM_QTQUICK_DANMAKU'] = '1'
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    if native:
        assert app.platformName() == 'windows'
    for count in range(1, 17):
        for columns in (0, 1, 2, 3, 16):
            area = QRect(0, 0, 280, 160)
            rectangles = pane_rectangles(count, area, columns)
            assert len(rectangles) == count and all(area.contains(rect) and not rect.isEmpty() for rect in rectangles)
            assert not any(first.intersects(second) for index, first in enumerate(rectangles) for second in rectangles[index + 1:])
    with tempfile.TemporaryDirectory(prefix='ddm-pip-') as directory, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'REPO', directory))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(directory) / 'config.json')))
        stack.enter_context(patch.object(plugins, 'DEFAULT_PLUGINS_DIR', str(Path(directory) / 'plugins')))
        stack.enter_context(patch.object(plugins.PluginManager, 'load'))
        for name in ('start_all', 'start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
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
        stack.enter_context(patch.object(SystemTray, 'restore'))
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
    print('PASS: PiP selection, shared playback, resizing, pinning, independent visibility, restore and shutdown')


if __name__ == '__main__':
    main()
