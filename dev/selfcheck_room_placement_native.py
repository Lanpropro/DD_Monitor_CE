"""Local libmpv swap regression: preserve cores, video HWNDs, progress and position audio."""
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.plugins import PluginManager
from dev.checks.bootstrap import require_local_network
from selfcheck_mpv import mta_lifetime, pump, ready


def main():
    denied = []
    sys.addaudithook(lambda event, args: require_local_network(event, args, denied))
    with mta_lifetime(), tempfile.TemporaryDirectory(prefix='ddm-placement-') as directory:
        media = Path(directory)/'fixture.mp4'
        subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '15',
            '-c:v', 'libx264', '-preset', 'ultrafast', str(media)], check=True, timeout=30)
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        with ExitStack() as stack:
            for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                           'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                           'load_cached_covers', 'load_cached_avatars', '_check_startup_update'):
                stack.enter_context(patch.object(MainWindow, method))
            stack.enter_context(patch.object(PluginManager, 'load'))
            rooms = [dict(room_id=str(1001+i), uname=f'Local {i}', live=True,
                          muted=True, volume=20+i*50) for i in range(2)]
            window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='2x2',
                state={'plugins_enabled': [], 'settings': {'auto_quality': False,
                    'close_behavior': 'exit', 'auto_update': False, 'preview_on_hover': False,
                    'recording_enabled': False, 'recording_replay_enabled': False}})
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.setGeometry(-15000, 0, 1000, 700)
            window.show()
            players = []
            try:
                first, second, empty = window.wall.tiles[:3]
                for tile in (first, second):
                    player = TilePlayer(tile.video, window, silent=True)
                    player.freeze_watch = False
                    player.set_muted(True)
                    player.play(str(media))
                    tile.set_video_active(True)
                    window.players[tile] = player
                    players.append(player)
                    ready(app, player)
                pump(app, .05)
                window.start_tile.reset_mock()
                cores = [player.player for player in players]
                generations = [player.state_generation for player in players]
                handles = {tile: int(tile.video.winId()) for tile in window.wall.tiles}
                audio = [(tile.volume, tile.muted, tile.audio_channel) for tile in window.wall.tiles]
                positions = [player._prop('time-pos') for player in players]
                owners = dict(window.players)
                assert first.room.get('room_id') == '1001'
                with patch.object(window.recorder, 'stop', wraps=window.recorder.stop) as stop_recording:
                    window._on_tile_swapped('1001', second)
                    assert window.wall.tiles[0] is second and window.wall.tiles[1] is first
                    window._on_room_dropped(empty, '1001')
                    assert window.wall.tiles[2] is first and window.wall.tiles[1] is empty
                    stop_recording.assert_not_called()
                pump(app, .25)
                assert window.players == owners
                assert [player.player for player in players] == cores
                assert [player.state_generation for player in players] == generations
                assert all(not player._released and player._prop('vo-configured') for player in players)
                assert all(player._prop('time-pos') > before for player, before in zip(players, positions))
                assert {tile: int(tile.video.winId()) for tile in window.wall.tiles} == handles
                assert [(tile.volume, tile.muted, tile.audio_channel) for tile in window.wall.tiles] == audio
                window.start_tile.assert_not_called()
                assert not denied
            finally:
                window.close()
                app.processEvents()
                assert all(player._released for player in players)
        app.shutdown()
    print('PASS: native room placement keeps two libmpv cores/HWNDs, continuous progress, position audio and clean shutdown')


if __name__ == '__main__':
    main()
