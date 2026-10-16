"""Native VLC playback survives appearance changes, with alpha badges above it."""
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
platform._wmi_query = lambda *args: (_ for _ in ()).throw(OSError('Isolated test'))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from ddm import app as app_module, theme
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from dev.selfcheck_tile_fullscreen import SilentPoller


def main():
    app = QApplication([])
    assert app.platformName() == 'windows'
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    rooms = [dict(room_id=str(990000+i), uname='Playback test '+str(i), live=False) for i in range(2)]
    with patch('PySide6.QtCore.QTimer.singleShot'):
        window = app_module.MainWindow(rooms, [dict(r) for r in rooms], layout_id='1x2',
            state={'plugins_enabled': [], 'settings': {'auto_update': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    visible = '--visible' in sys.argv
    if visible:
        window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        window.move(50, 100)
    else:
        window.move(-10000, -10000)
    window.resize(1280, 720)
    window.show()
    app.processEvents()
    with tempfile.TemporaryDirectory() as directory:
        video = Path(directory) / 'appearance.mp4'
        surface = window.wall.tiles[0].video
        width, height = max(2, surface.width()//2*2), max(2, surface.height()//2*2)
        subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
            '-i', f'color=c=blue:s={width}x{height}:r=25', '-t', '20', '-c:v', 'libx264',
            '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(video)], check=True)
        try:
            for tile in window.wall.tiles:
                player = TilePlayer(tile.video, window, silent=True)
                window.players[tile] = player
                player.play(str(video))
                tile.set_video_active(True)
                tile.set_controls_visible(True)
            deadline = time.monotonic()+10
            while time.monotonic() < deadline and not all(p.player.get_time() > 0 for p in window.players.values()):
                QTest.qWait(30)
            assert all(p.player.get_time() > 0 for p in window.players.values()), 'VLC did not start'
            if visible:
                from dev.selfcheck_video_surface import check_pixels, wait
                wait(app, lambda: all(check_pixels(tile) for tile in window.wall.tiles))
            players = dict(window.players)
            handles = [int(t.video.winId()) for t in window.wall.tiles]
            before = [p.player.get_time() for p in players.values()]
            recorder = window.recorder
            with patch.object(recorder, 'stop') as stop, patch.object(window, 'start_tile') as start:
                for mode in ('light', 'dark', 'light', 'dark'):
                    window.set_appearance(mode)
                    QTest.qWait(200)
                    assert window.players == players and window.recorder is recorder
                    assert handles == [int(t.video.winId()) for t in window.wall.tiles]
                    if theme.is_light():
                        for tile in window.wall.tiles:
                            tile.stream_badge.grab()
                            assert tile.stream_badge._alpha_uploaded
                            if visible:
                                badge = tile.stream_badge
                                point = badge.mapToGlobal(QPoint())
                                pixels = badge.screen().grabWindow(0, point.x(), point.y(),
                                    badge.width(), badge.height()).toImage()
                                corner = pixels.pixelColor(0, 0)
                                pixels.save(str(ROOT / 'work/appearance-badge-native.png'))
                                if corner.blue() <= 180:
                                    print('CORNER', corner.name(), corner.alpha(), 'DPR', pixels.devicePixelRatio())
                                    badge.screen().grabWindow(0, point.x()-12, point.y()-12,
                                        badge.width()+24, badge.height()+24).save(str(ROOT / 'work/appearance-badge-surround.png'))
                                assert corner.blue() > 180 and corner.red() < 80, ('Opaque badge corner', corner.name())
                                body = pixels.pixelColor(pixels.width()//2, round(3*pixels.devicePixelRatio()))
                                assert body.red() > 220 and body.green() > 220, ('Light body missing', body.name())
                                from dev.selfcheck_video_surface import check_controls
                                check_controls(tile)
                        output = ROOT / 'work/appearance-delivery'
                        output.mkdir(parents=True, exist_ok=True)
                        point = window.mapToGlobal(QPoint())
                        assert window.screen().grabWindow(0, point.x(), point.y(), window.width(), window.height()).save(str(output / 'native-light.png'))
                    else:
                        assert all(not getattr(t.stream_badge, '_layered_hwnd', None) for t in window.wall.tiles)
                start.assert_not_called()
                stop.assert_not_called()
            assert all(p.player.get_time() > earlier for p, earlier in zip(players.values(), before)), 'Playback clock reset or stopped'
            print('PASS: two native VLC outputs continue; stable players/HWNDs; no resolver restart/recording stop; alpha uploads and dark restoration')
        finally:
            window.close()
            app.processEvents()


if __name__ == '__main__':
    main()
