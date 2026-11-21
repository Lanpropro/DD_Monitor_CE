"""Run opted-in room recordings independently of the playback wall."""
from . import media_sources
from .bili_workers import StreamResolver
from .recording_session import BackgroundRecordingSource
from .streamer_defaults import room_defaults


class AutoRecording:
    def __init__(self, host):
        self.host = host
        self.settings_key = None
        self.attempted = {}
        self.failed_to_start = set()

    def configured_rooms(self):
        saved = self.host.settings.get('streamer_defaults')
        if not isinstance(saved, dict):
            return {}
        return {room_id: row for room_id, row in saved.items()
                if isinstance(room_id, str) and room_id and isinstance(row, dict)
                and row.get('auto_record') is True}

    def monitored_rooms(self):
        return self.configured_rooms() if self.host.settings.get('recording_enabled', True) else {}

    def settings_changed(self):
        host = self.host
        rooms = self.monitored_rooms()
        for source in tuple(host.recorder.sessions):
            if isinstance(source, BackgroundRecordingSource) and source.room['room_id'] not in rooms:
                host.recorder.stop(source)
        key = (frozenset(rooms), host.recorder.directory_setting)
        if self.settings_key and key[1] != self.settings_key[1]:
            for room_id in self.failed_to_start:
                self.attempted.pop(room_id, None)
            self.failed_to_start.clear()
        self.attempted = {room: started for room, started in self.attempted.items() if room in rooms}
        self.failed_to_start.intersection_update(rooms)
        if key == self.settings_key:
            return
        self.settings_key = key
        if rooms and not host._closing:
            host.refresh_status(force=True)

    def source_for(self, room_id):
        return next((source for source in self.host.recorder.sessions
                     if isinstance(source, BackgroundRecordingSource)
                     and source.room['room_id'] == room_id), None)

    def apply_status(self, status):
        host = self.host
        if host._closing:
            return
        rooms = self.monitored_rooms()
        if self.settings_key is None:
            self.settings_key = (frozenset(rooms), host.recorder.directory_setting)
        for room_id, profile in rooms.items():
            info = status.get(room_id)
            if not info or not info.get('live_known', True) or 'live' not in info:
                continue
            if not info['live']:
                self.attempted.pop(room_id, None)
                self.failed_to_start.discard(room_id)
                source = self.source_for(room_id)
                if source is not None:
                    host.recorder.stop(source, confirmed_offline=True)
                continue
            started = info.get('live_start_ts')
            started = started if type(started) is int and started > 0 else 0
            if room_id in self.attempted:
                previous = self.attempted[room_id]
                if not started or not previous or started <= previous:
                    self.attempted[room_id] = previous or started
                    continue
                self.attempted.pop(room_id)
                source = self.source_for(room_id)
                if source is not None:
                    host.recorder.stop(source, confirmed_offline=True)
            existing = tuple(host.recorder.sessions.values())
            if any(session.room_id == room_id and session.recording and session.stopping for session in existing):
                continue
            self.attempted[room_id] = started
            self.failed_to_start.discard(room_id)
            if (any(session.room_id == room_id and session.recording for session in existing)
                    or any(recording and str(tile.room.get('room_id')) == room_id
                           for tile, recording in host._pending_capture.items())):
                continue
            room = {'room_id': room_id, 'uname': info.get('uname') or profile.get('name') or room_id,
                    'title': info.get('title', ''), 'live': True}
            quality = room_defaults(host.settings, room_id).get('recording')
            if not host.recorder.start_background(BackgroundRecordingSource(room, quality)):
                self.failed_to_start.add(room_id)

    def resolve_source(self, session):
        host = self.host
        source = session.tile
        platform = host.plugins.platform_for(session.room_id)
        if host._closing or (platform is None and not session.room_id.isdigit()):
            host.recorder.source_failed(session, '对应直播平台不可用')
            return
        quality = source.quality
        exact = isinstance(quality, dict) and quality['label'] not in ('最高', '最高可用')
        request = quality['qn'] if isinstance(quality, dict) else (
            10000 if quality is not None or host.settings.get('recording_lock_quality', True) else 250)
        resolver = StreamResolver(session.room_id, request, host, platform=platform,
                                  codec=session.video_codec or host._codec_settings()['bili_codec'])
        if isinstance(quality, int):
            resolver.streamer_height = quality
            resolver.streamer_allow_lower = False
        session.resolver = resolver

        def current():
            return (not host._closing and host.recorder.sessions.get(source) is session
                    and not session.stopping and session.resolver is resolver)

        def resolved(_room_id, url, actual, _profile, options):
            if not current():
                media_sources.discard(url)
                return
            no_tier = len(options) == 1 and options[0].get('qn') == 0
            if (isinstance(quality, int) and quality > 0 and not resolver.applied_streamer_quality and not no_tier
                    or exact and actual != request):
                media_sources.discard(url)
                host.recorder.source_failed(session, '直播源未提供设置的录制画质')
                return
            if source.stream_url != url:
                media_sources.discard(source.stream_url)
                media_sources.take(url)
            source.stream_url = url
            source.stream_headers = dict(resolver.headers)
            source.stream_codec = resolver.source_codec
            host.recorder.source_resolved(session, url, source.stream_headers, source.stream_codec)

        def failed(_room_id, reason):
            if current():
                host.recorder.source_failed(session, reason)

        resolver.resolved.connect(resolved)
        resolver.failed.connect(failed)
        resolver.finished.connect(lambda: host._resolvers_running.discard(resolver))
        resolver.finished.connect(resolver.deleteLater)
        host._resolvers_running.add(resolver)
        resolver.start()
