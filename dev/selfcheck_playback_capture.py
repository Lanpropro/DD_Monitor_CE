"""Playback capture lifecycle regressions; fixtures are not live evidence."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QWidget
from ddm.playback_capture import PlaybackCapture


class Core:
    def __init__(self):
        self.callbacks = {}

    def observe_property(self, name, callback):
        self.callbacks[name] = callback

    def unobserve_property(self, name, callback):
        assert self.callbacks.pop(name) is callback

    def __getattr__(self, name):
        raise AssertionError('No synchronous property reads: ' + name)


class CaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QWidget()
        self.addCleanup(self.window.deleteLater)
        self.tiles = [QWidget(self.window) for _ in range(6)]
        self.window.wall = SimpleNamespace(tiles=self.tiles)
        self.window._resolvers = {self.tiles[5]: object()}
        self.window.players = {tile: SimpleNamespace(player=Core(), play_session='PRIVATE_SESSION',
            state='buffering', paused=False, _stall_ticks=3, _frozen_ticks=1, silent=False,
            source_failure='https://PRIVATE_HOST/token=PRIVATE_SECRET', _hls_proxy=None) for tile in self.tiles}
        self.records = []
        self.done = Mock()
        self.capture = PlaybackCapture(self.window, lambda stage, **values: self.records.append(dict(stage=stage, **values)), self.done)
        self.addCleanup(self.capture.stop)

    def test_async_samples_are_bounded_and_never_include_private_fields(self):
        self.capture.start()
        self.assertEqual(len(self.capture.players), 4)
        player = self.window.players[self.tiles[0]]
        callback = player.player.callbacks['paused-for-cache']
        callback('paused-for-cache', True)
        callback('cache-speed', 1024)
        callback('time-pos', float('nan'))
        callback('not-a-property', 'PRIVATE_SECRET')
        self.capture.sample()
        sample = self.records[-1]
        self.assertEqual(sample['players'][0]['properties']['cache-speed'], 1024)
        self.assertTrue(sample['players'][0]['properties']['paused-for-cache'])
        self.assertEqual(sample['resolving_slots'], [5])
        self.assertEqual(sample['omitted_players'], 2)
        self.assertNotIn('PRIVATE_', json.dumps(self.records))
        self.capture.stop()
        callback('cache-speed', 2048)
        self.assertFalse(player.player.callbacks)
        self.assertFalse(self.capture.timer.isActive())

    def test_new_session_detaches_old_observers_and_ignores_late_callbacks(self):
        self.capture.start()
        player = self.window.players[self.tiles[0]]
        old = player.player
        late = old.callbacks['time-pos']
        player.player = Core()
        player.play_session = 'NEW_PRIVATE_SESSION'
        self.capture.sample()
        self.assertFalse(old.callbacks)
        late('time-pos', 999)
        self.assertNotIn('time-pos', self.capture.players[0]['values'])
        self.window.players.clear()
        self.capture.sample()
        self.assertFalse(player.player.callbacks)
        self.assertFalse(self.capture.players)

    def test_douyin_source_and_format_are_observed_without_retaining_signed_url(self):
        player = self.window.players[self.tiles[0]]
        player.stream_profile = 'douyin'
        player.url = 'https://pull-flv-l13.douyincdn.com/PRIVATE_ROOM.flv?sign=PRIVATE_SECRET#PRIVATE_FRAGMENT'
        player.actual_quality = 10000
        self.tiles[0].quality = 10000
        self.capture.start()
        callback = player.player.callbacks['width']
        callback('width', 1920)
        callback('height', 1080)
        callback('container-fps', 60.0)
        callback('demuxer-cache-state', {'fw-bytes': 1024, 'private': 'PRIVATE_SECRET'})
        callback('height', float('inf'))
        self.capture.sample()
        row = self.records[-1]['players'][0]
        self.assertEqual(row['source'], dict(host='pull-flv-l13.douyincdn.com', scheme='https',
                                            transport='flv', route='direct-mpv', actual_quality=10000))
        self.assertEqual(row['requested_quality'], 10000)
        self.assertEqual({key: row['properties'][key] for key in
                          ('width', 'height', 'container-fps', 'cache-forward-bytes')},
                         dict(width=1920, height=1080, **{'container-fps': 60.0, 'cache-forward-bytes': 1024}))
        self.assertNotIn('PRIVATE_', json.dumps(self.records))
        self.assertEqual(set(self.window.players[self.tiles[1]].player.callbacks), set(self.capture.PROPERTIES))

    def test_douyin_reconnect_replaces_source_and_rejects_old_format_callbacks(self):
        player = self.window.players[self.tiles[0]]
        player.stream_profile = 'douyin'
        player.url = 'https://pull-flv-l13.douyincdn.com/PRIVATE.flv'
        self.capture.start()
        late = player.player.callbacks['width']
        player.play_session = 'replacement'
        player.url = 'https://pull-hls-l13.douyincdn.com/PRIVATE.m3u8?PRIVATE_SECRET'
        self.capture.sample()
        late('width', 999)
        self.capture.sample()
        row = self.records[-1]['players'][0]
        self.assertEqual(row['source']['transport'], 'hls')
        self.assertEqual(row['source']['host'], 'pull-hls-l13.douyincdn.com')
        self.assertNotIn('width', row['properties'])
        self.capture.stop()
        self.assertFalse(player.player.callbacks)

    def test_douyin_invalid_source_does_not_break_capture_or_expose_input(self):
        player = self.window.players[self.tiles[0]]
        player.stream_profile = 'douyin'
        player.url = 'https://[PRIVATE_SECRET'
        self.capture.start()
        self.assertEqual(self.records[-1]['players'][0]['source']['host'], 'unknown')
        self.assertNotIn('PRIVATE_', json.dumps(self.records))

    def test_bundled_mpv_supplies_forward_cache_bytes_to_capture(self):
        from ddm.player import mpv
        import tempfile
        import threading
        import wave
        player = self.window.players[self.tiles[0]]
        player.stream_profile = 'douyin'
        self.capture.start()
        changed = player.player.callbacks['demuxer-cache-state']
        ready = threading.Event()
        def received(name, value):
            changed(name, value)
            if isinstance(value, dict) and type(value.get('fw-bytes')) is int:
                ready.set()
        core = mpv.MPV(config=False, load_scripts=False, vo='null', ao='null',
                       idle=True, terminal=False, pause=True, cache='yes')
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'cache.wav'
                with wave.open(str(path), 'wb') as audio:
                    audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                    audio.writeframes(b'\0\0' * 48000)
                core.observe_property('demuxer-cache-state', received)
                core.play(str(path))
                self.assertTrue(ready.wait(5), 'Bundled mpv must expose the observed cache byte field')
                self.capture.sample()
                self.assertGreaterEqual(self.records[-1]['players'][0]['properties']['cache-forward-bytes'], 0)
        finally:
            core.terminate()

    def test_relay_metrics_are_numeric_aggregates_and_detach_after_capture(self):
        player = self.window.players[self.tiles[0]]
        relay = player._hls_proxy = SimpleNamespace(playback_diagnostic=None, network_speed=lambda: (1000, 2))
        self.capture.start()
        callback = relay.playback_diagnostic
        callback('request')
        callback('response', status=200, elapsed_ms=42)
        callback('chunk', bytes=65536, read_ms=10)
        callback('delivered', bytes=65536, write_ms=7)
        callback('request-error', status=503, elapsed_ms=50)
        self.capture.sample()
        stats = self.records[-1]['players'][0]['relay_requests']
        self.assertEqual(stats, dict(requests=1, responses=1, last_status=503, headers_max_ms=50,
                                    bytes=65536, read_max_ms=10, write_max_ms=7, errors=1))
        self.capture.stop()
        self.assertIsNone(relay.playback_diagnostic)
        callback('chunk', bytes=99)
        self.assertFalse(self.capture.players)

    def test_time_and_count_limits_close_observers_and_finish_once(self):
        self.capture.start()
        with patch('ddm.playback_capture.time.monotonic', return_value=self.capture.started + 60):
            self.capture.sample()
        self.done.assert_called_once_with('limit')
        count = len(self.records)
        self.capture.sample()
        self.assertEqual(len(self.records), count)
        self.assertTrue(self.capture.closed)

    def test_proxy_classification_never_returns_endpoint_or_credentials(self):
        for value, expected in (('http://u:PRIVATE_SECRET@127.0.0.1:7890', 'loopback-proxy'),
                                ('http://u:PRIVATE_SECRET@private.invalid:12', 'other-proxy')):
            with patch.dict(os.environ, {'https_proxy': value}):
                self.assertEqual(self.capture.proxy_kind(), expected)


if __name__ == '__main__':
    unittest.main()
