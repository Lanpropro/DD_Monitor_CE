"""采集器功能回归；合成状态不作为真实斗鱼故障或改善证据。"""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch
from types import SimpleNamespace

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.bili import StreamResolver
from ddm.plugins import Platform
from ddm.douyu_diagnostics import install


def main():
    launcher = (Path(__file__).resolve().parents[1] / 'run.cmd').read_text(encoding='utf-8')
    normal_entry = launcher.split('rem TEMP BUG-001:', 1)[1].split('exit /b 0', 1)[0]
    capture_entry = launcher.split(':douyu\n', 1)[1].split('exit /b 0', 1)[0]
    assert '"%PROJ%dev\\diagnose_drag_windows.py"' in normal_entry
    assert '"%PROJ%dev\\diagnose_drag_windows.py" --diagnose-douyu' in capture_entry
    app = QApplication.instance() or QApplication([])
    state = {'plugins_enabled': [], 'settings': {'auto_quality': False,
             'recording_enabled': False, 'recording_replay_enabled': False,
             'danmaku_enabled': False, 'preview_on_hover': False}}
    with tempfile.TemporaryDirectory() as root, \
            patch.object(MainWindow, '__init__', MainWindow.__init__), \
            patch.object(MainWindow, '_schedule_retry', MainWindow._schedule_retry), \
            patch.object(MainWindow, '_on_picture_frozen', MainWindow._on_picture_frozen), \
            patch.object(MainWindow, '_on_resolve_failed', MainWindow._on_resolve_failed), \
            patch.object(StreamResolver, '_platform_play_url', StreamResolver._platform_play_url), \
            patch.object(TilePlayer, '_play_media', TilePlayer._play_media), \
            patch.object(TilePlayer, '_stop_media', TilePlayer._stop_media), \
            patch.object(TilePlayer, '_check', TilePlayer._check), \
            patch.object(TilePlayer, 'bind', lambda player: None), \
            patch.object(TilePlayer, '_log', TilePlayer._log), \
            patch.object(MainWindow, '_on_player_state', MainWindow._on_player_state), \
            patch('ddm.app.QTimer.singleShot'), patch.object(MainWindow, 'sync_danmaku'), \
            patch.object(MainWindow, 'refresh_status'), patch.object(MainWindow, 'refresh_stats'), \
            patch.object(MainWindow, 'start_tile'):
        path = Path(root) / 'capture.jsonl'
        logger = install(path)
        window = MainWindow([], [], layout_id='1x1', state=state)
        player = TilePlayer(window.wall.tiles[0].video)
        tile = window.wall.tiles[0]
        tile.set_room({'room_id': 'douyu:fixture', 'live': True})
        window.players[tile] = player
        player.diagnostic_room = 'douyu:fixture'
        player.play_session = 'fixture-session'
        player._media = 'https://fixture.invalid/?token=must-not-log'
        props = {'time-pos': 1., 'vo-configured': True, 'audio-pts': 1.,
                 'video-frame-info': {'picture-type': 'P'}, 'estimated-frame-number': 60,
                 'demuxer-cache-state': {'ts-per-stream': [
                     {'type': 'video', 'cache-duration': .1}, {'type': 'audio', 'cache-duration': 3.}]},
                 'vo-passes': {'fresh': [{'last': 1000, 'avg': 2000, 'count': 3, 'samples': [1, 2]}]}}
        player.stateChanged.connect(lambda state: window._on_player_state(tile, state))
        try:
            with patch.object(player, '_prop', side_effect=lambda key, default=None: props.get(key, default)):
                player.player = Mock()
                events = {}
                player.player.event_callback.side_effect = lambda name: lambda callback: events.setdefault(name, callback)
                player.bind()
                player.player.set_loglevel.assert_called_once_with('warn')
                events['end-file'](SimpleNamespace(error=0,
                    as_dict=lambda *, decoder: {'reason': decoder(b'error')}))
                player.player = None
                player._check()
                assert player.state == 'playing' and not tile._buffering
                player._check()
                player._check()
                assert player.state == 'buffering' and tile._buffering
                props['time-pos'] = 2.
                player._check()
                assert player.state == 'playing' and not tile._buffering
                logger.flush()
                count = len(path.read_text(encoding='utf-8').splitlines())
                player._log('warn', 'ffmpeg/demuxer',
                            'Timestamp discontinuity https://cdn.invalid/private.flv?sign=hidden Cookie: secret')
                logger.flush()
                assert len(path.read_text(encoding='utf-8').splitlines()) == count + 1
                player.diagnostic_room = 'huya:fixture'
                player._log('warn', 'ffmpeg/demuxer', 'must-not-log')
                player._check()
                logger.flush()
                assert len(path.read_text(encoding='utf-8').splitlines()) == count + 1
                platform = Platform()
                platform.play_url = lambda *_: ('https://cdn.invalid/source.flv?token=secret', 10000, 'douyu', {})
                resolver = StreamResolver('douyu:fixture', 10000, platform=platform)
                resolver._platform_play_url()
                def fail_source(*_):
                    raise RuntimeError('fixture https://cdn.invalid/?token=secret')
                platform.play_url = fail_source
                try:
                    resolver._platform_play_url()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('Source failure was swallowed by diagnostics')
                logger.flush()
            records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            checks = [row for row in records if row['stage'] == 'TilePlayer._check']
            changes = [row for row in records if row['stage'] == 'MainWindow._on_player_state']
            assert len(checks) == 4 and all(row['elapsed_ms'] >= 0 for row in checks)
            assert checks[0]['properties']['audio-pts'] == 1.
            assert checks[0]['properties']['video-frame-info'] == {'picture-type': 'P'}
            assert checks[0]['properties']['avsync'] is None
            assert checks[0]['cache']['ts-per-stream'][1]['cache-duration'] == 3.
            assert checks[0]['render_passes']['fresh'][0]['last'] == 1000
            assert 'samples' not in checks[0]['render_passes']['fresh'][0]
            source = next(row for row in records if row['stage'] == 'source.result')
            assert source['host'] == 'cdn.invalid' and source['actual_quality'] == 10000
            failure = next(row for row in records if row['stage'] == 'source.error')
            assert failure['chain'][0]['frames'][-1]['function'] == 'fail_source'
            assert 'token=secret' not in str(failure)
            assert [row['buffering'] for row in changes] == [False, True, False]
            warning = next(row for row in records if row['stage'] == 'mpv.log')
            event = next(row for row in records if row['stage'] == 'mpv.event')
            assert event['event'] == 'end-file' and event['details']['reason'] == 'error'
            assert 'Timestamp discontinuity' in warning['message']
            assert all(secret not in warning['message'] for secret in ('private.flv', 'hidden', 'secret'))
            assert 'must-not-log' not in path.read_text(encoding='utf-8')
        finally:
            window.close()
            app.processEvents()
            logger.close()
    print('PASS: opt-in Douyu sampling, state/UI correlation, unavailable properties, timing, no stream URL')


if __name__ == '__main__':
    main()
