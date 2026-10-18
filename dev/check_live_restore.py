"""Public live stream: maximize/restore the 1+5 wall and inspect native composition."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ['DDM_QTQUICK_DANMAKU'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication
from ddm import bili, theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from selfcheck_danmaku_render_thread import MotionProbe


def settle(app, seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(.01)


def main():
    assert not bili.SESSION_DATA
    room_id = sys.argv[1] if len(sys.argv) > 1 else '1883358196'
    url, quality, profile, headers = bili.play_url(room_id, 80)
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    room = dict(room_id=room_id, uname='Public live restore check', live=True)
    with patch.object(MainWindow, 'start_tile'), patch.object(MainWindow, 'refresh_status'), \
            patch.object(MainWindow, 'refresh_stats'):
        window = MainWindow([room], [dict(room)], layout_id='corner',
                            state={'plugins_enabled': []})
        window.setGeometry(80, 80, 1200, 800)
        window.setWindowFlag(Qt.WindowStaysOnTopHint)
        window.show()
        tile = window.wall.tiles[0]
        player = TilePlayer(tile.video, tile, silent=True)
        window.players[tile] = player
        try:
            player.play(url, profile, headers, options=('audio=no',))
            tile.set_video_active(True)
            tile.danmaku_button.setChecked(True)
            window.sync_danmaku()
            deadline = time.perf_counter() + 40
            while time.perf_counter() < deadline:
                settle(app, .1)
                if window.wall._quick_danmaku_layer and float(player._prop('time-pos', 0) or 0) > 0:
                    break
            layer = window.wall._quick_danmaku_layer
            assert layer and layer.items, 'Real live danmaku required'
            results = []
            pixel_checks = 0
            for cycle in range(3):
                window.showMaximized()
                settle(app, .5)
                window.showNormal()
                window.setGeometry(80, 80, 1200 - cycle * 60, 800 - cycle * 40)
                window.raise_()
                window.activateWindow()
                settle(app, .6)
                assert not window.isMaximized()
                assert layer.window.isVisible()
                assert layer.window.color().alpha() == 0
                assert all(record['item'].property('imageLoaded') for record in layer.items.values())
                # Retained QML objects must create new scene nodes and continue
                # moving after their native surface is replaced.
                if layer.items:
                    record = next(iter(layer.items.values()))
                    probe = MotionProbe(record['item'])
                    positions = []
                    def sample():
                        x = probe.scene_x()
                        if x is not None:
                            positions.append(x)
                    layer.window.afterRendering.connect(sample, Qt.DirectConnection)
                    try:
                        settle(app, .2)
                        assert len({round(x, 1) for x in positions}) > 2, 'Live danmaku must keep moving after restore'
                    finally:
                        layer.window.afterRendering.disconnect(sample)
                        probe.deleteLater()
                point = tile.video.mapToGlobal(QPoint())
                scale = tile.screen().devicePixelRatio()
                exposed = True
                for rx, ry in ((.1, .1), (.9, .1), (.1, .9), (.9, .9), (.5, .5)):
                    hit = user32.WindowFromPoint(wintypes.POINT(
                        round((point.x() + tile.video.width() * rx) * scale),
                        round((point.y() + tile.video.height() * ry) * scale)))
                    exposed &= int(user32.GetAncestor(hit, 2) or 0) == int(window.winId())
                if not exposed:
                    print(json.dumps(dict(cycle=cycle, pixels='skipped: test window obscured')), flush=True)
                    continue
                image = tile.screen().grabWindow(0, point.x(), point.y(),
                                                 tile.video.width(), tile.video.height()).toImage()
                colors = [image.pixelColor(x, y) for y in range(image.height() // 3, image.height() * 2 // 3, 8)
                          for x in range(image.width() // 3, image.width() * 2 // 3, 8)]
                nonblack = sum(max(c.red(), c.green(), c.blue()) > 24 for c in colors) / len(colors)
                results.append(dict(cycle=cycle, nonblack=round(nonblack, 3),
                                    ex_style=hex(ctypes.windll.user32.GetWindowLongW(int(layer.window.winId()), -20))))
                print(json.dumps(results[-1]), flush=True)
                pixel_checks += 1
                if nonblack < .05:
                    layer.window.hide()
                    settle(app, .2)
                    image = tile.screen().grabWindow(0, point.x(), point.y(),
                                                     tile.video.width(), tile.video.height()).toImage()
                    raise AssertionError('Video area is black after native restore')
            assert float(player._prop('time-pos', 0) or 0) > 0
            assert pixel_checks, 'No foreground pixel checks; rerun when test window can be visible'
            for indicator in (tile.spinner, tile.pause_overlay):
                indicator.start()
                tile._layout_areas()
                settle(app, .2)
                assert indicator._alpha_uploaded, 'Live-video loading overlay must upload per-pixel alpha'
                assert indicator.mask().isEmpty(), 'Loading overlays must not use a binary region mask'
                origin = indicator.mapToGlobal(QPoint())
                hit = user32.WindowFromPoint(wintypes.POINT(
                    round((origin.x() + indicator.width() / 2) * scale),
                    round((origin.y() + indicator.height() / 2) * scale)))
                if int(user32.GetAncestor(hit, 2) or 0) == int(window.winId()):
                    shot = indicator.screen().grabWindow(0, origin.x() - 4, origin.y() - 4,
                                                         indicator.width() + 8, indicator.height() + 8)
                    name = 'live-loading-smooth.png' if indicator is tile.spinner else 'live-refresh-smooth.png'
                    shot.save(str(Path(__file__).resolve().parents[1] / 'cache' / name))
                indicator.stop()
            print('PASS native loading overlays above public live video', flush=True)
            print('PASS live restore', room_id, quality, 'pixel_checks=', pixel_checks, flush=True)
        finally:
            window.close()
            app.processEvents()
            app.aboutToQuit.emit()


if __name__ == '__main__':
    main()
