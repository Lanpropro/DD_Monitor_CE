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
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, plugins, theme
from ddm.app import MainWindow
from ddm.picture_in_picture import (PictureInPictureDialog, PictureInPictureWindow,
    composition_aspect, composition_rows, pane_rectangles, video_aspect)


def pointer(surface, kind, local, global_pos, button, buttons):
    event = QMouseEvent(kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.NoModifier)
    QApplication.sendEvent(surface, event)


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
            assert floating.width() > bounds.width() and floating.height() > bounds.height()
            assert abs(floating.height() - floating.width() / floating.aspect) <= 1
        else:
            assert floating.size() == floating.minimumSize()
            assert floating.geometry().bottomRight() == bounds.bottomRight()
    floating.setGeometry(bounds)
    QTest.qWait(50)


def check_native_corners(pip):
    """Optional real compositor evidence over a controlled local backdrop."""
    floating = pip.floating
    assert floating._native_rounding
    previous = floating.geometry()
    backdrop = QWidget(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    backdrop.setAttribute(Qt.WA_ShowWithoutActivating)
    backdrop.setStyleSheet('background: #ff00ff;')
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
    finally:
        floating.setGeometry(previous)
        backdrop.close()
        backdrop.deleteLater()
        QTest.qWait(80)


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
    with patch.object(pip.floating.tools.manage, 'underMouse', return_value=True), \
            patch('ddm.picture_in_picture.QApplication.widgetAt', return_value=pip.floating.pin):
        image = pip.floating.tools.manage.grab().toImage()
        assert image.pixelColor(12, 21).alpha() < 230, 'A stale hover bit must not flash the composition icon blue'
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
    assert not window.isMinimized(), 'Closing PiP must restore the main window'
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
    print('PASS: PiP selection, shared playback, resizing, pinning, independent visibility, restore and shutdown')


if __name__ == '__main__':
    main()
