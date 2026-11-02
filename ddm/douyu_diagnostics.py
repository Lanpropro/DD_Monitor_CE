"""Opt-in real Douyu playback sampling; no stream URLs or account data."""
import functools
import hashlib
from pathlib import Path
import re
import struct
import sys
import time
import traceback
from urllib.parse import urlsplit
import uuid

from .douyu_capture import Capture, TransportObserver


PROPERTIES = (
    'time-pos', 'playback-time', 'audio-pts', 'avsync', 'paused-for-cache',
    'video-frame-info', 'estimated-frame-number', 'vo-delayed-frame-count',
    'vo-configured', 'eof-reached', 'idle-active', 'core-idle', 'demuxer-cache-duration',
    'demuxer-cache-time', 'demuxer-cache-idle', 'cache-speed', 'hwdec-current',
    'video-format', 'estimated-vf-fps', 'decoder-frame-drop-count', 'frame-drop-count',
    'mistimed-frame-count', 'display-sync-active', 'display-fps', 'estimated-display-fps',
    'vsync-ratio', 'vsync-jitter', 'video-sync', 'video-timing-offset', 'audio-delay',
    'audio-speed-correction', 'video-speed-correction', 'speed', 'container-fps',
    'video-params', 'video-out-params', 'audio-params', 'video-bitrate', 'audio-bitrate')

EFFECTIVE_OPTIONS = ('vo', 'ao', 'gpu-api', 'gpu-context', 'd3d11-adapter', 'hwdec',
    'vd-lavc-threads', 'video-sync', 'cache-pause', 'cache-pause-wait', 'cache-secs',
    'demuxer-max-bytes', 'demuxer-readahead-secs', 'demuxer-lavf-analyzeduration',
    'demuxer-lavf-probesize', 'network-timeout')


def source_id(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def snapshot(player):
    cache = player._prop('demuxer-cache-state', {}) or {}
    return {
        'room': player.diagnostic_room, 'session': player.play_session,
        'state': player.state, 'paused': player.paused,
        'actual_quality': player.actual_quality, 'decode_mode': player.decode_mode,
        'freeze_watch': player.freeze_watch, 'silent': player.silent,
        'muted': player.muted, 'volume': player.volume,
        'stall_ticks': player._stall_ticks, 'frozen_ticks': player._frozen_ticks,
        'decoder_stall_ticks': player._decode_stall_ticks,
        'visible': player.video_widget.isVisible(),
        'video_size': [player.video_widget.width(), player.video_widget.height()],
        'tracks': [{key: track.get(key) for key in ('id', 'type', 'codec', 'selected',
                    'demux-w', 'demux-h', 'demux-fps', 'demux-samplerate', 'demux-channel-count')}
                   for track in (player._prop('track-list', []) or [])[:16]],
        'cache': {key: cache.get(key) for key in
                  ('cache-end', 'reader-pts', 'fw-bytes', 'eof', 'underrun',
                   'ts-per-stream', 'raw-input-rate', 'cache-duration', 'seekable-ranges')},
        'properties': {name: player._prop(name) for name in PROPERTIES},
        'render_passes': {kind: [{key: row.get(key) for key in ('last', 'avg', 'peak', 'count')}
                               for row in passes[:32]]
                          for kind, passes in (player._prop('vo-passes', {}) or {}).items()
                          if isinstance(passes, list)},
    }


def install(path, *, deep=False):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from .player import TilePlayer
    from .app import MainWindow
    from .bili import StreamResolver
    from .diagnostics import sanitize
    from .responsiveness import Probe

    path = Path(path)
    capture = Capture(path)
    write = capture.emit

    def clean(text):
        return re.sub(r'(?:https?|rtmps?)://[^\s\"\'<>]+', '[URL]', sanitize(text))[:2048]

    def active(player):
        return (player.diagnostic_room.startswith('douyu:')
                and not player._released and player._media is not None)

    original_bind = TilePlayer.bind

    @functools.wraps(original_bind)
    def bind(player):
        result = original_bind(player)
        if player.player is not None and not player._released:
            player.player.set_loglevel('warn' if player.diagnostic_room.startswith('douyu:') else 'error')
            if player.diagnostic_room.startswith('douyu:') and getattr(player, '_capture_core', None) is not player.player:
                player._capture_core = player.player
                player._capture_core_id = uuid.uuid4().hex[:8]
                available = player._prop('property-list', []) or []
                write('mpv.capabilities', room=player.diagnostic_room, core=player._capture_core_id,
                      mpv_version=player._prop('mpv-version'), ffmpeg_version=player._prop('ffmpeg-version'),
                      effective_options={key: player._prop('options/' + key) for key in EFFECTIVE_OPTIONS},
                      unavailable_properties=[name for name in PROPERTIES if name not in available])
                for name in ('start-file', 'file-loaded', 'video-reconfig', 'audio-reconfig',
                             'playback-restart', 'seek', 'end-file'):
                    def event_received(event, name=name):
                        if player.diagnostic_room.startswith('douyu:'):
                            details = event.as_dict(decoder=lambda value: value.decode('utf-8', errors='replace'))
                            write('mpv.event', room=player.diagnostic_room, session=player.play_session,
                                  core=player._capture_core_id, event=name, error=int(event.error),
                                  details={key: details.get(key) for key in
                                           ('playlist_entry_id', 'reason', 'error', 'playlist_insert_id')})
                    player.player.event_callback(name)(event_received)
        return result

    original_log = TilePlayer._log

    @functools.wraps(original_log)
    def media_log(player, level, prefix, message):
        original_log(player, level, prefix, message)
        if active(player) and level in ('warn', 'error', 'fatal'):
            # Warnings can contain complete signed paths as well as query credentials.
            write('mpv.log', room=player.diagnostic_room, session=player.play_session,
                  level=level, prefix=prefix, message=clean(message))

    original_resolve = StreamResolver._platform_play_url

    @functools.wraps(original_resolve)
    def resolve(resolver):
        if not resolver.room_id.startswith('douyu:'):
            return original_resolve(resolver)
        request = uuid.uuid4().hex[:8]
        started = time.monotonic()
        write('source.request', request=request, room=resolver.room_id, quality=resolver.quality,
              codec=resolver.codec, preview=resolver.preview, source_offset=resolver.source_offset)
        try:
            result = original_resolve(resolver)
        except Exception as error:
            chain = []
            cause = error
            while cause is not None and len(chain) < 8:
                chain.append(dict(error=type(cause).__name__, message=clean(str(cause)),
                    frames=[dict(file=Path(frame.f_code.co_filename).name,
                                 function=frame.f_code.co_name, line=line)
                            for frame, line in list(traceback.walk_tb(cause.__traceback__))[-16:]]))
                cause = cause.__cause__ or cause.__context__
            write('source.error', request=request, room=resolver.room_id,
                  elapsed_ms=(time.monotonic() - started) * 1000,
                  error=type(error).__name__, message=clean(str(error)), chain=chain,
                  cancelled=resolver.is_cancelled())
            raise
        write('source.result', request=request, room=resolver.room_id,
              elapsed_ms=(time.monotonic() - started) * 1000, source_id=source_id(result[0]),
              host=urlsplit(result[0]).hostname, actual_quality=result[1], profile=result[2],
              cancelled=resolver.is_cancelled())
        return result

    original_play = TilePlayer._play_media
    original_stop = TilePlayer._stop_media

    @functools.wraps(original_stop)
    def stop_media(player):
        original_stop(player)
        relay = getattr(player, '_douyu_capture_relay', None)
        if relay is not None:
            relay.stop()
            player._douyu_capture_relay = None

    @functools.wraps(original_play)
    def play_media(player, url, profile, headers, options):
        if profile != 'douyu':
            return original_play(player, url, profile, headers, options)
        attempt = uuid.uuid4().hex[:8]
        context = dict(room=player.diagnostic_room, playback_attempt=attempt, source_id=source_id(url))
        write('playback.request', **context, quality=player.actual_quality,
              decode_mode=player.decode_mode, host=urlsplit(url).hostname,
              mode='relay-flv' if deep else 'direct')
        relay = None
        if deep:
            from .hls_proxy import HlsProxy
            from .global_danmaku import request_proxy
            from .bili import UA
            from .douyu_transport import EdgeTLSAdapter, session_for
            request_headers = dict(headers or player.PROFILE_HEADERS['web'])
            if not any(key.lower() == 'user-agent' for key in request_headers):
                request_headers['User-Agent'] = UA
            def create_session():
                session = session_for(url)
                adapter = session.get_adapter(url)
                context_tls = adapter.poolmanager.connection_pool_kw.get('ssl_context')
                write('network.tls-policy', **context,
                      cipher_compatibility=isinstance(adapter, EdgeTLSAdapter),
                      certificate_verification=session.verify,
                      hostname_check=context_tls.check_hostname if context_tls is not None else None,
                      security_level=context_tls.security_level if context_tls is not None else None)
                return session
            relay = HlsProxy(url, request_headers, request_proxy(url),
                session_factory=create_session,
                stream_observer=lambda source: TransportObserver(
                    lambda stage, **values: write(stage, **context, **values), source),
                diagnostic=lambda **values: write('network.relay', **context, **values))
        try:
            result = original_play(player, relay.url if relay else url, profile, headers, options)
        except BaseException:
            if relay is not None:
                relay.stop()
            raise
        player._douyu_capture_relay = relay
        if relay is not None:
            player.url = url  # Keep source metadata; mpv itself reads the local relay URL.
        write('playback.started', **context, session=player.play_session)
        return result

    original_check = TilePlayer._check

    @functools.wraps(original_check)
    def check(player):
        if not active(player):
            return original_check(player)
        started = time.perf_counter()
        before = player.state
        try:
            return original_check(player)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            write('TilePlayer._check', before=before, elapsed_ms=round(elapsed, 3),
                  **snapshot(player))

    original_state = MainWindow._on_player_state

    @functools.wraps(original_state)
    def state_changed(window, tile, state):
        player = window.players.get(tile)
        if player is None or not active(player):
            return original_state(window, tile, state)
        started = time.perf_counter()
        try:
            return original_state(window, tile, state)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            write('MainWindow._on_player_state', requested_state=state,
                  elapsed_ms=round(elapsed, 3),
                  buffering=tile._buffering, **snapshot(player))

    original_initialize = MainWindow.__init__

    for method_name in ('start_tile', '_schedule_retry', '_on_picture_frozen', '_on_resolve_failed'):
        original = getattr(MainWindow, method_name)
        def timed_transition(method, label):
            @functools.wraps(method)
            def transition(window, tile, *args, **kwargs):
                room = str((tile.room if tile is not None else {}).get('room_id') or '')
                if not room.startswith('douyu:'):
                    return method(window, tile, *args, **kwargs)
                started = time.perf_counter()
                player = window.players.get(tile)
                write('recovery.begin', function=label, room=room,
                      session=player.play_session if player is not None else None,
                      reason=clean(str(args[0])) if label == '_on_resolve_failed' and args else None)
                try:
                    return method(window, tile, *args, **kwargs)
                finally:
                    write('recovery.end', function=label, room=room,
                          elapsed_ms=(time.perf_counter() - started) * 1000)
            return transition
        setattr(MainWindow, method_name, timed_transition(original, method_name))

    @functools.wraps(original_initialize)
    def initialize(window, *args, **kwargs):
        original_initialize(window, *args, **kwargs)
        platform = window.plugins.platforms.get('douyu')
        if platform is not None:
            from .douyu_cdn_control import install as install_cdn_control
            install_cdn_control(platform, path.with_name('douyu-control.json'), write)
        probe = Probe(path.with_name('douyu-responsiveness.jsonl'))
        capture.probes.append(probe)
        window._douyu_capture = capture
        probe.start()
        QApplication.instance().aboutToQuit.connect(capture.close)
        window.destroyed.connect(probe.stop)
        heartbeat = QTimer(window)
        heartbeat.setInterval(100)
        heartbeat.timeout.connect(lambda: probe.pulse(window))
        probe.pulse(window)
        heartbeat.start()
        write('window.ready', responsiveness_session=probe.session,
              screens=[dict(width=screen.geometry().width(), height=screen.geometry().height(),
                            dpr=screen.devicePixelRatio(), refresh_hz=screen.refreshRate())
                       for screen in QGuiApplication.screens()])

        def sample():
            if window._closing:
                return
            for tile, player in list(window.players.items()):
                if active(player):
                    started = time.perf_counter()
                    info = snapshot(player)
                    write('playback.sample', **info, buffering=tile._buffering,
                          requested_quality=tile.quality, layout=window.layout_id,
                          minimized=window.isMinimized(), fullscreen=window._fullscreen_tile is tile,
                          sample_ms=(time.perf_counter() - started) * 1000,
                          queued_records=capture.queue.qsize(),
                          dropped_records=capture.dropped)
        timer = QTimer(window)
        timer.setInterval(500)
        timer.timeout.connect(sample)
        timer.start()

    TilePlayer._check = check
    TilePlayer.bind = bind
    TilePlayer._log = media_log
    TilePlayer._play_media = play_media
    TilePlayer._stop_media = stop_media
    StreamResolver._platform_play_url = resolve
    MainWindow._on_player_state = state_changed
    MainWindow.__init__ = initialize
    write('capture-start', schema=2, sample_interval_ms=500, deep=deep,
          python=sys.version.split()[0], architecture_bits=struct.calcsize('P') * 8,
          queue_limit=20000, log_bytes=20 * 1024 * 1024, log_backups=5,
          limitations=['no physical display presentation timestamps or GPU utilization',
                       'FLV inspection does not decode reference-picture dependencies',
                       'network chunk timing is application read timing, not TCP packet timing',
                       'deep mode changes the transport stack to the local relay'])
    return capture
