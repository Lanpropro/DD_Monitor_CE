"""Run opted-in room recordings independently of the playback wall."""
import sys
from datetime import datetime

from . import media_sources
from .bili_workers import RecordingStreamResolver
from .recording_schedule import ALL_WEEK, has_open_start, matches_recording_title, plan_window
from .recording_session import BackgroundRecordingSource
from .streamer_defaults import monitored_streamers, recording_policy, room_defaults


class AutoRecording:
    def __init__(self, host):
        self.host = host
        self.settings_key = None
        self.attempted = {}
        self.failed_to_start = set()
        self.room_details = {}
        self._watched_ids = set()
        self.planned_rooms = {}
        self.active_windows = {}
        self.started_open_windows = {}
        self._last_minute = None

    def _read_planned_rooms(self):
        settings = self.host.settings
        result = {}
        for room_id, row in monitored_streamers(settings).items():
            if recording_policy(row) == 'schedule':
                profile = room_defaults(settings, room_id)
                if profile.get('recording_schedule') or profile.get('recording_title_keywords'):
                    result[room_id] = {**profile, 'name': row.get('name')}
        self.planned_rooms = result

    def tick(self, *, now=None, refresh=True, config_changed=False):
        host = self.host
        if host._closing:
            return
        now = now or datetime.now()
        minute = now.replace(second=0, microsecond=0)
        previous_plans = self.planned_rooms
        if config_changed:
            self._read_planned_rooms()
        elif minute == self._last_minute:
            return
        self._last_minute = minute
        self.started_open_windows = {room: opening for room, opening in self.started_open_windows.items()
                                     if opening.date() >= now.date()}
        enabled = host.settings.get('recording_enabled', True)
        active = {}
        if enabled:
            for room_id, profile in self.planned_rooms.items():
                schedule = profile.get('recording_schedule')
                window = (plan_window(schedule, now, consumed_start=self.started_open_windows.get(room_id))
                          if schedule else (*ALL_WEEK, False))
                if window is not None and window[0] <= now:
                    active[room_id] = window
        changed = (active.keys() != self.active_windows.keys()
                   or any(previous_plans.get(room_id) != self.planned_rooms[room_id] for room_id in active))
        for room_id in active.keys() - self.active_windows.keys():
            self.attempted.pop(room_id, None)
            self.failed_to_start.discard(room_id)
        for room_id, window in self.active_windows.items():
            if room_id not in active or now >= window[1] or now < window[0]:
                self.attempted.pop(room_id, None)
                self.failed_to_start.discard(room_id)
                changed = True
        self.active_windows = active
        for source, session in tuple(host.recorder.sessions.items()):
            if not isinstance(source, BackgroundRecordingSource) or source.scheduled_end is None or session.stopping:
                continue
            window = active.get(session.room_id)
            profile = self.planned_rooms.get(session.room_id, {})
            monitoring = room_defaults(host.settings, session.room_id).get('monitor_live') is not False
            if source.scheduled_start is not None:
                if not enabled or (monitoring and not has_open_start(
                        profile.get('recording_schedule', ()), source.scheduled_start)):
                    host.recorder.stop(source)
                continue
            if enabled and now < source.scheduled_end and window and not window[2]:
                source.scheduled_end = window[1]
            elif not enabled or now >= source.scheduled_end or (
                    not window and monitoring):
                source.schedule_completed = enabled
                host.recorder.stop(source)
        if refresh and changed:
            host.refresh_status(force=True)
        return changed

    def configured_rooms(self):
        return {room_id: {'name': row.get('name'), **room_defaults(self.host.settings, room_id)}
                for room_id, row in monitored_streamers(self.host.settings).items()
                if recording_policy(row) == 'live'}

    def monitored_rooms(self):
        return self.configured_rooms() if self.host.settings.get('recording_enabled', True) else {}

    def controls_room(self, room_id):
        profile = room_defaults(self.host.settings, room_id)
        return ((profile.get('monitor_live') is True and recording_policy(profile) == 'live')
                or self.source_for(str(room_id)) is not None)

    def watched_rooms(self):
        # A capture already on disk still needs a confirmed offline status after monitoring is paused.
        return dict.fromkeys((*monitored_streamers(self.host.settings),
                              *self.planned_rooms,
                              *(session.room_id for source, session in self.host.recorder.sessions.items()
                                if isinstance(source, BackgroundRecordingSource))))

    def _finishing_paused_capture(self, session):
        profile = room_defaults(self.host.settings, session.room_id)
        return (self.host.settings.get('recording_enabled', True) and session.recording_started_at
                and profile.get('monitor_live') is False and recording_policy(profile) == 'live')

    def _settings_key(self, rooms):
        recorder = self.host.recorder
        modes = {profile.get('auto_record_mode') for profile in rooms.values()}
        return (frozenset((room_id, profile.get('auto_record_mode')) for room_id, profile in rooms.items()),
                frozenset((mode, recorder.background_directory(mode)) for mode in modes),
                'clip' in modes and recorder.background_clip_factory is not None)

    def _sync_settings_key(self, rooms):
        key = self._settings_key(rooms)
        if key == self.settings_key:
            return False
        self.settings_key = key
        for room_id in self.failed_to_start:
            self.attempted.pop(room_id, None)
        self.failed_to_start.clear()
        return True

    def settings_changed(self):
        host = self.host
        schedule_changed = self.tick(config_changed=True, refresh=False)
        rooms = self.monitored_rooms()
        for tile, recording in tuple(host._pending_capture.items()):
            if recording and str(tile.room.get('room_id')) in rooms:
                host._pending_capture.pop(tile, None)
                host._restore_capture_quality(tile)
        for source, session in tuple(host.recorder.sessions.items()):
            background = isinstance(source, BackgroundRecordingSource)
            if (background and source.scheduled_end is None and session.room_id not in rooms
                    and not self._finishing_paused_capture(session)
                    or not background and session.recording and session.room_id in rooms):
                host.recorder.stop(source)
        self.attempted = {room: started for room, started in self.attempted.items()
                          if room in rooms or room in self.active_windows}
        watched = set(self.watched_rooms())
        self.room_details = {room: details for room, details in self.room_details.items() if room in watched}
        changed = self._sync_settings_key(rooms) or watched != self._watched_ids or schedule_changed
        self._watched_ids = watched
        if changed and watched and not host._closing:
            host.refresh_status(force=True)

    def source_for(self, room_id):
        return next((source for source in self.host.recorder.sessions
                     if isinstance(source, BackgroundRecordingSource)
                     and source.room['room_id'] == room_id), None)

    def apply_status(self, status, *, now=None):
        host = self.host
        if host._closing:
            return {}
        self.tick(now=now, refresh=False, config_changed=True)
        rooms = {**self.monitored_rooms(),
                 **{room_id: self.planned_rooms[room_id] for room_id in self.active_windows}}
        self._sync_settings_key(rooms)
        faces = {}
        watched = self.watched_rooms()
        self.room_details = {room: details for room, details in self.room_details.items() if room in watched}
        for room_id in watched:
            info = status.get(room_id)
            if info:
                details = self.room_details.setdefault(room_id, {})
                if info.get('face') and info['face'] != details.get('face'):
                    faces[room_id] = info['face']
                details.update({key: info[key] for key in ('uname', 'uid', 'anchor_uid', 'display_room_id',
                                                          'platform', 'face') if info.get(key)})
                if info.get('live_known', True) and 'live' in info:
                    details['live'] = bool(info['live'])
        for source, session in tuple(host.recorder.sessions.items()):
            info = status.get(session.room_id, {})
            if (isinstance(source, BackgroundRecordingSource) and session.room_id not in rooms
                    and not session.stopping and info.get('live_known', True) and info.get('live') is False):
                host.recorder.stop(source, confirmed_offline=True)
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
            window = self.active_windows.get(room_id)
            until_offline = window is not None and window[2]
            if window is not None and (
                    any(session.room_id == room_id and session.recording
                        and not isinstance(session.tile, BackgroundRecordingSource)
                        for session in host.recorder.sessions.values())
                    or any(recording and str(tile.room.get('room_id')) == room_id
                           for tile, recording in host._pending_capture.items())):
                continue
            if until_offline:
                source = self.source_for(room_id)
                session = host.recorder.sessions.get(source)
                if (session is not None and session.recording and not session.stopping
                        and matches_recording_title(info.get('title'), profile.get('recording_title_keywords', ()))):
                    if source.scheduled_start is None:
                        source.scheduled_start = window[0]
                        source.scheduled_end = datetime.max
                    self.started_open_windows[room_id] = window[0]
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
            if not matches_recording_title(info.get('title'), profile.get('recording_title_keywords', ())):
                continue
            self.attempted[room_id] = started
            self.failed_to_start.discard(room_id)
            if (any(session.room_id == room_id and session.recording for session in existing)
                    or any(recording and str(tile.room.get('room_id')) == room_id
                           for tile, recording in host._pending_capture.items())):
                continue
            room = {'room_id': room_id, 'uname': info.get('uname') or profile.get('name') or room_id,
                    'title': info.get('title', ''), 'live': True}
            if window:
                room['scheduled_recording'] = True
            quality = profile.get('recording')
            if host.recorder.start_background(BackgroundRecordingSource(
                    room, quality, recording_mode=profile.get('auto_record_mode'),
                    scheduled_end=(datetime.max if until_offline else window[1]) if window else None,
                    scheduled_start=window[0] if until_offline else None)):
                if until_offline:
                    self.started_open_windows[room_id] = window[0]
            else:
                self.failed_to_start.add(room_id)
        return faces

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
        resolver = RecordingStreamResolver(session.room_id, request, host, platform=platform,
                                           codec=session.video_codec or host._codec_settings()['bili_codec'],
                                           check_status=session.retry_count > 0)
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

        def offline():
            if current():
                # Keep this broadcast marked as attempted until the regular poll catches up.
                print(f'[录制] {session.name} 续录前确认下播，结束自动录制', file=sys.stderr, flush=True)
                host.recorder.stop(source, confirmed_offline=True)

        resolver.resolved.connect(resolved)
        resolver.failed.connect(failed)
        resolver.offline.connect(offline)
        resolver.finished.connect(lambda: host._resolvers_running.discard(resolver))
        resolver.finished.connect(resolver.deleteLater)
        host._resolvers_running.add(resolver)
        resolver.start()
