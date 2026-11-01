"""Offline static move preview and normal Qt DPI transitions; --screens uses attached monitors."""
import argparse
import ctypes
from ctypes import wintypes
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QPixmap, QScreen
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.plugins import PluginManager
from ddm.window_move import WindowMove
from dev.selfcheck_mpv import ready
from dev.selfcheck_window_resize import Work, latest_geometry, settle, wait_orientation


def make_window(count, layout, *, sidebar_count=None):
    rooms = [dict(room_id=str(9000+i), uname='synthetic', live=True, muted=True)
             for i in range(sidebar_count or count)]
    window = MainWindow(rooms, [dict(r) for r in rooms[:count]], layout_id=layout,
        state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit',
            'auto_update': False, 'preview_on_hover': False, 'recording_enabled': False,
            'sidebar_auto_compact': False,
            'recording_replay_enabled': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setGeometry(-9000, 40, 1420, 860)
    window.show()
    settle(250)
    return window


def dpi_event(window):
    QCoreApplication.sendEvent(window, QEvent(QEvent.Type.DevicePixelRatioChange))


def assert_settled(window):
    assert not window._resize_dirty
    assert window.updatesEnabled()
    assert window._root_layout.isEnabled()
    assert not window.wall._interactive_resize
    assert not window._resize_idle_timer.isActive()
    assert not window.wall._resize_timer.isActive()
    area = window.centralWidget().contentsRect()
    content = window._content.geometry()
    assert content.bottomRight() == area.bottomRight(), (content, area)
    if window.orientation == 'portrait':
        assert content.top() == window.sidebar.geometry().bottom()+1
    else:
        assert content.left() == window.sidebar.geometry().right()+1
    # Fractional Windows DPI can round a minimum size by one logical pixel.
    assert window.wall.pos() == window._content.contentsRect().topLeft()
    assert abs(window.wall.width()-window._content.width()) <= 1
    assert abs(window.wall.height()-window._content.height()) <= 1
    for tile in window.wall.visible_tiles():
        assert tile.video.devicePixelRatioF() == window.devicePixelRatioF()
        assert tile.controls.devicePixelRatioF() == window.devicePixelRatioF()
    latest_geometry(window)


def assert_native_geometry(window):
    user32 = ctypes.windll.user32
    user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    for widget in window.findChildren(QWidget):
        if not widget.isVisible() or widget.isWindow() or not widget.testAttribute(Qt.WA_NativeWindow):
            continue
        parent = widget.nativeParentWidget()
        origin, actual = wintypes.POINT(), wintypes.POINT()
        assert user32.ClientToScreen(int(parent.winId()), ctypes.byref(origin))
        assert user32.ClientToScreen(int(widget.winId()), ctypes.byref(actual))
        position = widget.mapTo(parent, QPoint())
        scale = widget.devicePixelRatioF()
        expected = origin.x+round(position.x()*scale), origin.y+round(position.y()*scale)
        assert abs(actual.x-expected[0]) <= 2 and abs(actual.y-expected[1]) <= 2, (
            widget.metaObject().className(), (actual.x, actual.y), expected)
        bounds = wintypes.RECT()
        assert user32.GetClientRect(int(widget.winId()), ctypes.byref(bounds))
        assert abs(bounds.right-round(widget.width()*scale)) <= 1, widget.metaObject().className()
        assert abs(bounds.bottom-round(widget.height()*scale)) <= 1, widget.metaObject().className()


def check_lifecycle():
    window = make_window(6, 'corner')
    area = QApplication.primaryScreen().availableGeometry()
    window.setGeometry(area.x()+30, area.y()+60, 1200, 750)
    settle(250)
    controller = window._window_move = WindowMove(window, int(window.winId()))
    assert isinstance(controller, WindowMove)
    try:
        window._begin_interactive_resize()
        for height in (950, 1200, 1550):
            dpi_event(window)
            window.resize(1100, height)
            QApplication.processEvents()
            assert window._root_layout.isEnabled() and window.updatesEnabled()
        window._finish_interactive_resize()
        wait_orientation(window, 'portrait')
        assert_settled(window)
        window.resize(1200, 750)
        wait_orientation(window, 'landscape')
        original = window.geometry()
        for _ in range(3):
            preview = controller.begin()
            assert preview is not None and not preview.frame.isNull()
            assert not window.isVisible() and preview.isVisible()
            assert controller.begin() is None, 'Only one move preview may exist'
            preview.move(preview.pos()+QPoint(10, 10))
            controller.finish(cancelled=True)
            assert window.isVisible() and window.geometry() == original
            assert controller.preview is None and not controller.timer.isActive()
        with patch.object(QScreen, 'grabWindow', return_value=QPixmap()):
            assert controller.begin() is None
            assert window.isVisible() and controller.preview is None
        with patch.object(controller, 'begin', return_value=None), patch.object(controller, 'user32') as api:
            controller.run_move()
            api.SendMessageW.assert_called_once_with(int(window.winId()), 0x0112, 0xF012, 0)
        # Exercise the native caption handler without entering an interactive move loop.
        msg = wintypes.MSG()
        msg.message, msg.wParam = 0x00A1, 2
        assert controller.native_message(msg) and controller.press is not None
        msg.message = 0x0202
        assert controller.native_message(msg) and controller.press is None
        assert controller.user32.GetCapture() != int(window.winId())
        msg.message = 0x00A3
        assert not controller.native_message(msg), 'Native double-click must remain unhandled'
        # Native double-click message checks routing, not physical mouse generation.
        for expected in (True, False):
            controller.user32.SendMessageW(int(window.winId()), 0x00A3, 2, 0)
            settle(350)
            assert window.isMaximized() == expected
        wait_orientation(window, 'landscape')
        assert_settled(window)
        controller.begin()
        controller.finish()
        with patch.object(window, '_finish_interactive_resize', side_effect=RuntimeError('test')):
            try:
                controller._complete()
                raise AssertionError('Expected injected settle failure')
            except RuntimeError:
                pass
        assert controller.preview is None and window.isVisible()
        assert not controller.timer.isActive()
        controller.begin().close()
        assert controller.preview is None and not window.isVisible()
        assert not controller.timer.isActive()
    finally:
        window.close()
        QApplication.processEvents()


def check_native_drag(window, target, return_to=None):
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)

    def size(handle):
        rect = wintypes.RECT()
        assert user32.GetWindowRect(handle, ctypes.byref(rect))
        return rect.right-rect.left, rect.bottom-rect.top

    controller = window._window_move
    if controller is None:
        controller = window._window_move = WindowMove(window, int(window.winId()))
    before = size(int(window.winId()))
    geometry = window.geometry()
    dpr = window.devicePixelRatioF()
    videos = {int(t.video.winId()): size(int(t.video.winId())) for t in window.wall.visible_tiles()}
    players = [(p, p._prop('time-pos'), p._prop('audio-pts'), p.player, p.play_session)
               for p in window.players.values()]
    # A screen capture requires an unobscured fixture. Foreground activation
    # alone can be refused by Windows when a separately launched check starts.
    assert user32.SetWindowPos(int(window.winId()), -1, 0, 0, 0, 0, 0x0013)
    window.raise_()
    window.activateWindow()
    settle(300)
    started = time.perf_counter()
    preview = controller.begin()
    capture_ms = (time.perf_counter()-started)*1000
    assert preview is not None
    # The local FFmpeg clip is blue: inspect captured native video pixels, not Qt grab().
    frame = preview.frame.toImage()
    scale = preview.frame.devicePixelRatioF()
    checked_pixels = 0
    for tile in window.wall.tiles[:len(players)]:
        point = tile.video.mapTo(window, tile.video.rect().center())
        # Oversized landscape windows extend beyond the portrait desktop. Only
        # pixels actually present on this screen can appear in a screen capture.
        if not window.screen().geometry().contains(tile.video.mapToGlobal(tile.video.rect().center())):
            continue
        pixel = frame.pixelColor(round(point.x()*scale), round(point.y()*scale))
        if not (pixel.blue() > 150 and pixel.red() < 80):
            preview.frame.save(str(ROOT / 'work/move-preview-failed.png'))
            raise AssertionError(('Missing native video in preview', pixel.name(),
                                  frame.size(), scale, point))
        checked_pixels += 1
    assert not players or checked_pixels, 'No visible native video pixel was checked'
    try:
        for screen in (target,) if return_to is None else (target, return_to):
            area = screen.availableGeometry()
            for offset in (60, 70, 80):
                assert user32.SetWindowPos(int(preview.winId()), None,
                    area.x()+round(offset*screen.devicePixelRatio()),
                    area.y()+round(offset*screen.devicePixelRatio()), 0, 0, 0x0015)
                settle(70)
                assert size(int(preview.winId())) == preview.physical_size, 'Preview scaled while held'
                assert not window.isVisible() and window.geometry() == geometry
                assert size(int(window.winId())) == before and window.devicePixelRatioF() == dpr
                assert all(size(handle) == previous for handle, previous in videos.items())
        for player, position, audio_position, core, session in players:
            assert player._prop('time-pos') > position and not player._prop('pause')
            assert audio_position is not None and player._prop('audio-pts') > audio_position
            assert player.player is core and player.play_session == session
        controller.finish()
        deadline = time.monotonic()+3
        while controller.preview is not None and time.monotonic() < deadline:
            settle(25)
        assert controller.preview is None and not controller.timer.isActive()
    finally:
        controller.cancel()
    wait_orientation(window, 'landscape')
    assert window.size() == geometry.size(), ('Normal size changed after moving', geometry, window.geometry())
    assert window.devicePixelRatioF() == (return_to or target).devicePixelRatio()
    assert_settled(window)
    assert_native_geometry(window)
    return round(capture_ms, 2)


def check_screens(app, player_count, source):
    screens = app.screens()
    if len(screens) < 2:
        raise RuntimeError('--screens requires two attached monitors')
    landscape = max(screens, key=lambda s: s.availableGeometry().width()/s.availableGeometry().height())
    portrait = min(screens, key=lambda s: s.availableGeometry().width()/s.availableGeometry().height())
    assert portrait.availableGeometry().height() > portrait.availableGeometry().width()
    results = []
    for count, layout in ((3, 'dm_main3'), (6, 'corner'), (16, '4x4')):
        window = make_window(count, layout, sidebar_count=123)
        cover = QPixmap(400, 225)
        cover.fill(Qt.darkCyan)
        for item in window.sidebar.items():
            item.thumb.set_cover(cover)
        for i in range(20):
            window.wall.danmaku.add_message(f'Test {i}', 'DPI geometry sample')
        identities = {tile: int(tile.video.winId()) for tile in window.wall.tiles}
        cores = []
        try:
            area = landscape.availableGeometry()
            window.setGeometry(area.x()+40, area.y()+40, 1200, 750)
            settle(300)
            for tile in window.wall.tiles[:player_count]:
                player = TilePlayer(tile.video, window)
                window.players[tile] = player
                player.set_muted(True)
                player.bind()
                player.player.loop_file = 'inf'
                player.play(str(source))
                ready(app, player)
                cores.append((player, player.player, player.play_session, player._prop('time-pos')))
            captures = []
            for _ in range(3):
                captures.extend((check_native_drag(window, portrait), check_native_drag(window, landscape)))
            captures.append(check_native_drag(window, portrait, return_to=landscape))
            results.append(dict(panes=count, capture_and_begin_ms=captures))
            with ExitStack() as measured:
                work = Work(window, measured)
                for target, maximize in ((portrait, False), (portrait, True),
                                          (portrait, False), (landscape, False)):
                    work.reset()
                    started = time.perf_counter()
                    restoring = not maximize and window.isMaximized()
                    if maximize:
                        normal_layout = window.wall.layout_id
                        window.showMaximized()
                    elif restoring:
                        window.showNormal()
                    else:
                        window.showNormal()
                        area = target.availableGeometry()
                        window.setGeometry(area.x()+10, area.y()+60, 1100, 700)
                    settle(500)
                    expected = 'portrait' if maximize else 'landscape'
                    wait_orientation(window, expected)
                    assert_settled(window)
                    assert_native_geometry(window)
                    if restoring:
                        assert not window.isMaximized()
                        assert window.wall.layout_id == normal_layout
                    assert window.screen() is target
                    assert window.devicePixelRatioF() == target.devicePixelRatio()
                    assert all(int(tile.video.winId()) == hwnd for tile, hwnd in identities.items())
                    if maximize:
                        # Qt processes geometry normally; one old layout may precede the final orientation.
                        assert work.calls['_relayout_corner'] <= 1, 'Repeated old layout during maximize'
                        assert work.calls['_relayout_preset'] <= 3, 'Repeated final orientation layout'
                    results.append(dict(panes=count, maximize=maximize,
                        screen=target.name(), dpr=window.devicePixelRatioF(), orientation=window.orientation,
                        elapsed_ms=round((time.perf_counter()-started)*1000, 2), **work.snapshot()))
            for player, core, session, position in cores:
                assert player.player is core and player.play_session == session
                assert player._prop('time-pos') > position and player.state == 'playing'
        finally:
            window.close()
            QApplication.processEvents()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screens', action='store_true')
    parser.add_argument('--players', type=int, choices=range(0, 7), default=0)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.players and not args.screens:
        parser.error('--players requires --screens')
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='ddm-screen-') as temporary:
        stack.enter_context(patch.object(PluginManager, 'load'))
        for name in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                     'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                     'load_cached_covers', 'load_cached_avatars', '_check_startup_update'):
            stack.enter_context(patch.object(MainWindow, name))
        source = Path(temporary) / 'synthetic.mp4'
        if args.players:
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '30',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(source)],
                check=True, timeout=30)
        check_lifecycle()
        report = {'passed': True, 'players': args.players,
                  'scope': 'Qt layout work and native identity; not DWM or decoder FPS',
                  'screens': check_screens(app, args.players, source) if args.screens else []}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
