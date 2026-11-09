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
