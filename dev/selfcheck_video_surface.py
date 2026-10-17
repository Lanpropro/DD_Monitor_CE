"""Windows VLC 原生画面圆角、DPI 边界、重建与各平台全屏闲置回归。"""
import argparse
import ctypes
from ctypes import wintypes
from functools import partial
from contextlib import ExitStack
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, window_fullscreen
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from dev.selfcheck_tile_fullscreen import SilentPoller


def wait(app, predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.02)
    assert predicate(), 'Timed out'


def check_regions(tile):
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)
    user32.GetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE)
    user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.MapWindowPoints.argtypes = (wintypes.HWND, wintypes.HWND,
                                      ctypes.POINTER(wintypes.POINT), wintypes.UINT)
    gdi32.CreateRectRgn.restype = wintypes.HANDLE
    gdi32.PtInRegion.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    root = int(tile.video.winId())
    children, errors = [], []
    def inspect(hwnd, _unused):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, len(name))
        if hwnd != root and not name.value.startswith('VLC video'):
            return True
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        try:
            if not user32.GetWindowRgn(hwnd, region):
                errors.append(name.value + ': missing native clip')
            else:
                origin = wintypes.POINT()
                user32.MapWindowPoints(root, hwnd, ctypes.byref(origin), 1)
                if bool(gdi32.PtInRegion(region, origin.x, origin.y)) != bool(tile.property('fullscreen')):
                    errors.append(name.value + ': video corner does not match fullscreen state')
                bounds = wintypes.RECT()
                user32.GetClientRect(root, ctypes.byref(bounds))
                if gdi32.PtInRegion(region, origin.x + bounds.right, origin.y + bounds.bottom):
                    errors.append(name.value + ': video leaks past parent')
            if hwnd != root:
                children.append(name.value)
        finally:
            gdi32.DeleteObject(region)
        return True
    inspect(root, 0)
    user32.EnumChildWindows(root, callback_type(inspect), 0)
    check_regions.last = (children, errors)
    return len(children) >= 2 and not errors


def check_controls(tile):
    user32 = ctypes.windll.user32
    user32.ChildWindowFromPointEx.argtypes = (wintypes.HWND, wintypes.POINT, wintypes.UINT)
    user32.ChildWindowFromPointEx.restype = wintypes.HWND
    user32.IsChild.argtypes = (wintypes.HWND, wintypes.HWND)
    controls = int(tile.controls.winId())
    for button in (tile.quality_button, tile.reload_button, tile.close_button):
        point = button.mapTo(tile, button.rect().center())
        scale = tile.devicePixelRatioF()
        point = wintypes.POINT(round(point.x() * scale), round(point.y() * scale))
        hwnd = int(tile.winId())
        for _ in range(15):
            child = user32.ChildWindowFromPointEx(hwnd, point, 3)
            if not child or child == hwnd:
                break
            user32.MapWindowPoints(hwnd, child, ctypes.byref(point), 1)
            hwnd = child
        assert hwnd == controls or user32.IsChild(controls, hwnd), 'Video blocks overlay controls'


def reset_output_regions(tile):
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
    reset = []
    def clear(hwnd, _unused):
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, len(name))
        if name.value.startswith('VLC video'):
            assert user32.SetWindowRgn(hwnd, None, False)
            reset.append(hwnd)
        return True
    user32.EnumChildWindows(int(tile.video.winId()), callback_type(clear), 0)
    assert reset, 'Test must reset real VLC output windows'


def check_danmaku_region(tile):
    overlay = tile.video_danmaku
    assert overlay.isVisible() and overlay.geometry() == tile.video.geometry()
    assert not overlay.mask().isEmpty(), 'Danmaku native window has no rounded mask'
    assert overlay.mask() == tile.video.mask(), 'Danmaku and video boundaries differ'
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    region = gdi32.CreateRectRgn(0, 0, 0, 0)
    video_region = gdi32.CreateRectRgn(0, 0, 0, 0)
    gdi32.EqualRgn.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    try:
        assert user32.GetWindowRgn(int(overlay.winId()), region), 'Missing native danmaku clip'
        assert user32.GetWindowRgn(int(tile.video.winId()), video_region), 'Missing native video clip'
        assert gdi32.EqualRgn(region, video_region), 'Native video and danmaku contours differ'
        assert bool(gdi32.PtInRegion(region, 0, 0)) == bool(
            tile.property('fullscreen')), 'Danmaku corner does not match fullscreen state'
        scale = overlay.devicePixelRatioF()
        assert gdi32.PtInRegion(region, round(overlay.width() * scale / 2),
                              round(overlay.height() * scale / 2))
    finally:
        gdi32.DeleteObject(region)
        gdi32.DeleteObject(video_region)


def overlay_sizes(tile):
    result = []
    for widget in (tile.controls, tile.stream_badge, tile.title_badge, tile.time_badge,
                   tile.quality_button, tile.reload_button, tile.close_button, tile.bottom):
        native = None
        if widget.testAttribute(Qt.WA_NativeWindow):
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(int(widget.winId()), ctypes.byref(rect))
            native = (rect.right - rect.left, rect.bottom - rect.top)
        result.append((widget.size(), widget.font(), widget.devicePixelRatioF(), native))
    return result


def check_control_background(tile):
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    region = gdi32.CreateRectRgn(0, 0, 0, 0)
    try:
        assert user32.GetWindowRgn(int(tile.controls.winId()), region)
        scale = tile.controls.devicePixelRatioF()
        for button in (tile.quality_button, tile.reload_button, tile.close_button):
            rect = button.geometry()
            x, y = round(rect.x() * scale), round(rect.y() * scale)
            assert not gdi32.PtInRegion(region, x, y), 'Rectangular backing expands control background'
            assert gdi32.PtInRegion(region, round(rect.center().x() * scale),
                                  round(rect.center().y() * scale))
    finally:
        gdi32.DeleteObject(region)


def check_pixels(tile):
    point = tile.video.mapToGlobal(QPoint())
    image = tile.screen().grabWindow(0, point.x(), point.y(), tile.video.width(), tile.video.height()).toImage()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    if not (center.blue() > 180 and center.red() < 80):
        return False
    for x, y in ((0, 0), (image.width() - 1, 0), (0, image.height() - 1),
                 (image.width() - 1, image.height() - 1)):
        pixel = image.pixelColor(x, y)
        assert (pixel.blue() > 180 and pixel.red() < 80) == bool(
            tile.property('fullscreen')), 'VLC corner does not match fullscreen state'
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--background', action='store_true')
    args = parser.parse_args()
    app = QApplication([])
    if os.name != 'nt' or app.platformName() != 'windows':
        print('Skipped: Windows native renderer required')
        return
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    with tempfile.TemporaryDirectory() as directory:
        video = Path(directory) / 'surface.flv'
        subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                        '-i', 'color=c=blue:s=1280x720:r=25', '-t', '45', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(video)], check=True)
        playlist = Path(directory) / 'surface.m3u8'
        subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-i', str(video),
                        '-c', 'copy', '-hls_time', '2', '-hls_list_size', '0',
                        '-hls_playlist_type', 'vod', str(playlist)], check=True)
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/surface.flv'
        try:
            for platform in ('bilibili', 'douyu', 'huya', 'douyin', 'twitch', 'youtube'):
                room = {'room_id': '1000' if platform == 'bilibili' else platform + ':1000',
                        'platform': platform, 'uname': 'Surface test', 'live': False}
                with patch('ddm.app.QTimer.singleShot'):
                    window = MainWindow([room], [dict(room)], layout_id='1x1', state={'plugins_enabled': ['domestic_live', 'global_live'], 'settings': {'auto_update': False}})
                window._upgrade_fullscreen_quality = lambda _tile: False
                window.sync_danmaku = lambda: None
                interactions = ExitStack()
                if args.background:
                    window.setAttribute(Qt.WA_ShowWithoutActivating, True)
                    window.move(-10000, -10000)
                    position = interactions.enter_context(patch.object(QCursor, 'pos'))
                    position.return_value = QPoint(-10000, -10000)
                    interactions.enter_context(patch.object(ctypes.windll.user32, 'SetCursor'))
                    # 后台验证全屏布局和尺寸，不改变前台窗口、鼠标或系统光标。
                    def enter(widget):
                        widget.resize(1280, 720)
                        return (int(widget.winId()), 0, (0, 0, 0, 0))
                    interactions.enter_context(patch.object(window_fullscreen, 'enter', side_effect=enter))
                    interactions.enter_context(patch.object(window_fullscreen, 'exit'))
                    window._hold_fullscreen_frame = lambda: None
                    window._release_fullscreen_frame = lambda: None
                else:
                    window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
                window.isActiveWindow = lambda: True
                window.resize(800, 600)
                window.show()
                if not args.background:
                    window.activateWindow()
                tile = window.wall.tiles[0]
                player = TilePlayer(tile.video, tile)
                window.players[tile] = player
                # 国内/海外实际走 FFmpeg 中继；B 站使用原来的直接播放。
                source = url.replace('surface.flv', 'surface.m3u8') if platform in ('twitch', 'youtube') else url
                player.play(source, profile='web' if platform == 'bilibili' else platform)
                if args.background:
                    position.return_value = tile.video.mapToGlobal(tile.video.rect().center())
                cursor = window._fullscreen_cursor
                cursor.IDLE_SECONDS = .25
                try:
                    try:
                        wait(app, lambda: player.player.get_time() > 0 and check_regions(tile))
                    except AssertionError:
                        print('RENDER_STATE', platform, str(player.player.get_state()), player.player.get_time(), getattr(check_regions, 'last', None))
                        raise
                    reset_output_regions(tile)
                    wait(app, lambda: check_regions(tile))
                    tile.set_video_active(True)
                    sizes = overlay_sizes(tile)
                    for enabled in (True, False, True):
                        # Qt can reapply its rectangular paint mask when a
                        # layered sibling is created; native contours must recover.
                        mask = tile.controls.mask()
                        tile.controls.clearMask()
                        tile.controls.setMask(mask)
                        tile.danmaku_button.setChecked(enabled)
                        if enabled:
                            assert tile.video_danmaku.add_event({'text': 'Rounded overlay regression'})
                            tile.video_danmaku.comments[-1].x = 0
                        app.processEvents()
                        check_control_background(tile)
                        assert overlay_sizes(tile) == sizes, (platform, enabled, sizes, overlay_sizes(tile))
                        if enabled:
                            check_danmaku_region(tile)
                        else:
                            assert not tile.video_danmaku.isVisible()
                    tile.set_controls_visible(False)
                    if not args.background:
                        wait(app, lambda: check_pixels(tile))
                    window._on_fullscreen(tile)
                    window._clear_fullscreen_cover()
                    if not args.background:
                        window.activateWindow()
                    wait(app, lambda: check_regions(tile))
                    check_danmaku_region(tile)
                    check_control_background(tile)
                    geometry = tile.video.geometry()
                    point = tile.video.mapToGlobal(tile.video.rect().center())
                    if args.background:
                        position.return_value = point
                    else:
                        QCursor.setPos(point)
                    try:
                        wait(app, lambda: cursor.hidden)
                    except AssertionError:
                        u = ctypes.windll.user32
                        u.GetForegroundWindow.restype = wintypes.HWND
                        print('IDLE_STATE', platform, 'qt_active', window.isActiveWindow(),
                              'native_active', u.GetForegroundWindow() == int(window.winId()),
                              'timer', cursor.timer.isActive(), 'pos', QCursor.pos(),
                              'video', tile.video.geometry(),
                              'inside', tile.video.rect().contains(tile.video.mapFromGlobal(QCursor.pos())),
                              'popup', bool(QApplication.activePopupWidget()),
                              'modal', bool(QApplication.activeModalWidget()), 'buttons', QApplication.mouseButtons())
                        raise
                    assert not tile.bottom.isVisible() and not tile.controls.isVisible()
                    assert tile.video.geometry() == geometry, platform + ': idle changed video size'
                    if not args.background:
                        wait(app, lambda: check_pixels(tile))
                    if args.background:
                        position.return_value = point + QPoint(15, 0)
                    else:
                        QCursor.setPos(QCursor.pos() + QPoint(15, 0))
                    wait(app, lambda: not cursor.hidden)
                    assert tile.bottom.isVisible() and tile.video.geometry() == geometry
                    tile.set_controls_visible(True)
                    app.processEvents()
                    check_controls(tile)
                    window._exit_fullscreen()
                    window._clear_fullscreen_cover()
                    player.play(source, profile='web' if platform == 'bilibili' else platform)
                    wait(app, lambda: player.player.get_time() > 0 and check_regions(tile))
                    check_danmaku_region(tile)
                    tile.set_controls_visible(False)
                    if not args.background:
                        wait(app, lambda: check_pixels(tile))
                    print('PASS:', platform, 'background' if args.background else 'visible',
                          'danmaku rounded mask/on/off; stable control size/background; native reset; fullscreen/idle/rebuild')
                finally:
                    window.close()
                    app.processEvents()
                    interactions.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    main()
