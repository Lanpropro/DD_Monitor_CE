"""On-demand real playback evidence, with bounded asynchronous mpv observation."""
import math
import os
import threading
import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer


class PlaybackCapture(QObject):
    PROPERTIES = ('time-pos', 'audio-pts', 'paused-for-cache', 'demuxer-cache-duration',
                  'cache-speed', 'video-bitrate', 'frame-drop-count',
                  'decoder-frame-drop-count', 'eof-reached')

    def __init__(self, window, emit, done):
        super().__init__(window)
        self.window, self.emit, self.done = window, emit, done
        self.closed = False
        self.players = {}
        self.lock = threading.Lock()
        self.started = self.previous = time.monotonic()
        self.samples = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.sample)

    def start(self):
        self.emit('playback-start', limit_seconds=60, limit_players=4,
                  properties=list(self.PROPERTIES), mpv_queries_on_gui_thread=False)
        self.timer.start()
        self.sample()

    @staticmethod
    def proxy_kind():
        value = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY') or os.environ.get('http_proxy') or ''
        if not value:
            return 'environment-unset'
        try:
            return 'loopback-proxy' if urlsplit(value).hostname in ('localhost', '127.0.0.1', '::1') else 'other-proxy'
        except ValueError:
            return 'other-proxy'

    def _watch(self, slot, player):
        started = time.perf_counter()
        core = getattr(player, 'player', None)
        session = getattr(player, 'play_session', None)
        old = self.players.get(slot)
        if old is not None and old['core'] is core and old['session'] == session and old['player'] is player:
            return old
        if old is not None:
            self._unwatch(old)
        entry = dict(player=player, core=core, session=session, values={}, observers=[], failed=0,
                     relay=getattr(player, '_hls_proxy', None), network={}, network_callback=None)
        self.players[slot] = entry
        relay = entry['relay']
        if relay is not None and getattr(relay, 'playback_diagnostic', None) is None:
            def network(event, **values):
                with self.lock:
                    if self.closed or self.players.get(slot) is not entry:
                        return
                    stats = entry['network']
                    counter = {'request': 'requests', 'response': 'responses',
                               'request-error': 'errors', 'read-error': 'errors'}.get(event)
                    if counter:
                        stats[counter] = stats.get(counter, 0) + 1
                    if event == 'chunk':
                        stats['bytes'] = stats.get('bytes', 0) + values.get('bytes', 0)
                    if 'status' in values:
                        stats['last_status'] = values['status']
                    for key, target in (('elapsed_ms', 'headers_max_ms'), ('read_ms', 'read_max_ms'),
                                        ('write_ms', 'write_max_ms')):
                        if key in values:
                            stats[target] = round(max(stats.get(target, 0), values[key]), 3)
            entry['network_callback'] = network
            relay.playback_diagnostic = network
        if core is None:
            return entry
        def changed(name, value):
            # The callback runs on mpv's event thread. Never write logs or query
            # properties there; keep only the latest finite numeric value.
            if name not in self.PROPERTIES or not isinstance(value, (int, float, bool, type(None))):
                return
            if isinstance(value, (int, float)) and not math.isfinite(value):
                return
            with self.lock:
                if not self.closed and self.players.get(slot) is entry:
                    entry['values'][name] = value
        for name in self.PROPERTIES:
            try:
                core.observe_property(name, changed)
                entry['observers'].append((name, changed))
            except (RuntimeError, ValueError):
                entry['failed'] += 1
        self.emit('playback-observers', slot=slot, replaced=old is not None,
                  unavailable=entry['failed'], setup_ms=round((time.perf_counter() - started) * 1000, 3))
        return entry

    @staticmethod
    def _unwatch(entry):
        relay = entry['relay']
        if relay is not None and relay.playback_diagnostic is entry['network_callback']:
            relay.playback_diagnostic = None
        for name, callback in entry['observers']:
            try:
                entry['core'].unobserve_property(name, callback)
            except (RuntimeError, ValueError):
                pass
        entry['observers'].clear()

    def sample(self):
        if self.closed:
            return
        now = time.monotonic()
        live = [(tile, player) for tile, player in self.window.players.items()
                if not getattr(player, '_released', False) and not getattr(player, 'silent', False)][:4]
        seen, rows = set(), []
        tiles = list(self.window.wall.tiles)
        for tile, player in live:
            slot = tiles.index(tile) if tile in tiles else len(tiles) + len(rows)
            seen.add(slot)
            entry = self._watch(slot, player)
            with self.lock:
                values = dict(entry['values'])
                network = dict(entry['network'])
            failure = getattr(player, 'source_failure', '')
            if failure.startswith('HTTP_') and failure[5:].isdigit():
                failure = failure[:8]
            elif failure not in ('', 'LIVE_EOF', 'STALL', 'TIMEOUT'):
                failure = 'source-error'
            row = dict(slot=slot, state=getattr(player, 'state', 'unknown'),
                       paused=bool(getattr(player, 'paused', False)), failure=failure,
                       stall_ticks=getattr(player, '_stall_ticks', 0),
                       frozen_ticks=getattr(player, '_frozen_ticks', 0), properties=values,
                       stream_profile=getattr(player, 'stream_profile', 'unknown'), relay_requests=network)
            relay = getattr(player, '_hls_proxy', None)
            if relay is not None:
                speed, samples = relay.network_speed()
                row['relay_bps'], row['relay_samples'] = speed, samples
            rows.append(row)
        for slot in set(self.players) - seen:
            self._unwatch(self.players.pop(slot))
        self.emit('playback-sample', elapsed_ms=round((now - self.started) * 1000),
                  tick_gap_ms=round((now - self.previous) * 1000),
                  proxy_environment=self.proxy_kind(), players=rows,
                  resolving_slots=[tiles.index(tile) for tile in getattr(self.window, '_resolvers', {}) if tile in tiles][:16],
                  omitted_players=max(0, len(self.window.players) - len(rows)))
        self.previous = now
        self.samples += 1
        if now - self.started >= 60 or self.samples >= 61:
            self.finish('limit')

    def finish(self, reason):
        self.stop()
        self.done(reason)

    def stop(self):
        if self.closed:
            return
        with self.lock:
            self.closed = True
        self.timer.stop()
        for entry in self.players.values():
            self._unwatch(entry)
        self.players.clear()
        self.deleteLater()
