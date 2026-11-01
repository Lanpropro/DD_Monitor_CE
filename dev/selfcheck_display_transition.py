"""Offline DPI/maximize layout batching; --screens exercises attached monitors."""
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
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from ddm import theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.plugins import PluginManager
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
    assert not window._display_transition and not window._resize_dirty
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
    try:
        window._begin_interactive_resize()
        guard = window._dpi_drag
        before = window.wall.geometry()
        for height in (950, 1200, 1550):
            dpi_event(window)
            window.resize(1100, height)
            QApplication.processEvents()
            assert window._display_transition and not window._root_layout.isEnabled()
            assert not window.updatesEnabled(), 'Do not paint mixed DPI child geometry'
            assert window.wall.geometry() == before, 'Intermediate screen geometry was committed'
        window._finish_interactive_resize()
        assert window._dpi_drag is None and not guard.active
        assert window.updatesEnabled(), 'Final layout must restore painting'
        wait_orientation(window, 'portrait')
        assert_settled(window)

        dpi_event(window)
        window._end_display_transition()  # Layout resumes before the final paint commit.
        dpi_event(window)
        window._finish_interactive_resize()
        assert window.updatesEnabled(), 'A repeated DPI event must retain the original paint state'

        window._begin_interactive_resize()
        guard = window._dpi_drag
        dpi_event(window)
        window.hide()
        assert window._dpi_drag is None and not guard.active
        assert not window._display_transition and window._root_layout.isEnabled()
        assert window.updatesEnabled()
        assert not window._resize_idle_timer.isActive()
        window.show()
        wait_orientation(window, 'portrait')
        assert_settled(window)

        window._begin_interactive_resize()
        guard = window._dpi_drag
        rect = wintypes.RECT()
        user32 = ctypes.windll.user32
        assert user32.GetWindowRect(int(window.winId()), ctypes.byref(rect))
        user32.SendMessageW(int(window.winId()), 0x0214, 1, ctypes.addressof(rect))
        assert not guard.active, 'Native resizing must use immediate DPI handling'
        window._finish_interactive_resize()
        assert window._dpi_drag is None

        window._root_layout.setEnabled(False)
        dpi_event(window)
        window._cancel_interactive_resize()
        assert not window._root_layout.isEnabled(), 'Preserve caller-disabled layout state'
        window._root_layout.setEnabled(True)
        window._root_layout.invalidate()
        window._root_layout.activate()

        window.setUpdatesEnabled(False)
        dpi_event(window)
        window._cancel_interactive_resize()
        assert not window.updatesEnabled(), 'Preserve caller-disabled painting'
        window.setUpdatesEnabled(True)
        assert window.wall.updatesEnabled()

        dpi_event(window)
        window.resize(1420, 860)
        with patch.object(window, '_apply_orientation', side_effect=RuntimeError('test')):
            try:
                window._finish_interactive_resize()
                raise AssertionError('Expected injected orientation failure')
            except RuntimeError:
                pass
        assert not window._display_transition and window._root_layout.isEnabled()
        assert not window.wall._interactive_resize and not window._resize_idle_timer.isActive()
        assert window.updatesEnabled(), 'Failed layout must release the repaint hold'

        dpi_event(window)
        window.close()
        assert not window._display_transition and window._root_layout.isEnabled()
        assert not window._resize_idle_timer.isActive()
    finally:
        window.close()
        QApplication.processEvents()


def check_native_drag(window, target, return_to=None):
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.SendMessageW.restype = ctypes.c_ssize_t
    hwnd = int(window.winId())

    def size(handle):
        rect = wintypes.RECT()
        assert user32.GetWindowRect(handle, ctypes.byref(rect))
        return rect.right-rect.left, rect.bottom-rect.top

    before = size(hwnd)
    dpr = window.devicePixelRatioF()
    videos = {int(t.video.winId()): size(int(t.video.winId())) for t in window.wall.visible_tiles()}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)

    @callback_type
    def collect(handle, _unused):
        videos[int(handle)] = size(handle)
        return True

    for handle in tuple(videos):
        user32.EnumChildWindows(handle, collect, 0)  # Include libmpv's own rendering children.
    user32.SendMessageW(hwnd, 0x0231, 0, 0)  # Native move loop starts before the DPI crossing.
    try:
        for screen in (target,) if return_to is None else (target, return_to):
            area = screen.availableGeometry()
            for offset in (60, 70, 80):
                assert user32.SetWindowPos(hwnd, None, area.x()+offset, area.y()+offset,
                                           0, 0, 0x0015)  # NOSIZE | NOZORDER | NOACTIVATE
                settle(70)
                assert size(hwnd) == before, ('Window scaled before release', before, size(hwnd))
                assert window.devicePixelRatioF() == dpr, 'DPI switched while the title bar was held'
                assert all(size(handle) == previous for handle, previous in videos.items())
    finally:
        user32.SendMessageW(hwnd, 0x0232, 0, 0)
    wait_orientation(window, 'landscape')
    assert window.devicePixelRatioF() == (return_to or target).devicePixelRatio()
    assert_settled(window)
    assert_native_geometry(window)


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
            check_native_drag(window, portrait)
            check_native_drag(window, landscape)
            check_native_drag(window, portrait, return_to=landscape)
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
                        assert work.calls['_relayout_corner'] == 0, 'Old landscape layout ran during maximize'
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
                '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30', '-t', '30',
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
