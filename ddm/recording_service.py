"""Versioned plugin boundary for host capture operations and completed segments."""
from pathlib import Path
import time

from .recording import RecordingSession, ffmpeg_path
from .recording_session import BackgroundRecordingSource


class RecordingService:
    api_version = 1

    def __init__(self, context):
        self.context = context
        self._leases = set()
        self._session_factory = None
        self._background_clip_factory = None

    def _host(self):
        host = self.context.window
        if not self.context._active or host is None or getattr(host, '_closing', False):
            raise RuntimeError('录制服务已停止')
        if not hasattr(host, 'recorder') or not hasattr(host, 'capture_control'):
            raise RuntimeError('当前窗口不提供录制服务')
        return host

    def options(self):
        host = self._host()
        return {'directory': str(host.settings.get('recording_dir') or ''),
                'ffmpeg': ffmpeg_path(host.settings),
                'pending_outputs': [str(result.resolve()) for _process, result, _parts, _full
                                    in host.recorder.exports]}

    def register_backend(self, session_factory, *, enabled=True):
        """Use a RecordingSession subclass for new captures; existing ones keep running."""
        recorder = self._host().recorder
        if not isinstance(session_factory, type) or not issubclass(session_factory, RecordingSession):
            raise TypeError('Recording backend must extend RecordingSession')
        if recorder.backend_owner not in (None, self):
            raise RuntimeError('已有其他插件接管录制')
        recorder.backend_owner = self
        self._session_factory = session_factory
        recorder.session_factory = session_factory if enabled else RecordingSession

    def set_backend_enabled(self, enabled):
        host = self._host()
        recorder = host.recorder
        if recorder.backend_owner is not self or self._session_factory is None:
            raise RuntimeError('录制后端未注册')
        factory = self._session_factory if enabled else RecordingSession
        if recorder.session_factory is factory:
            return
        if recorder.sessions:
            raise RuntimeError('请先停止当前录制和缓存，再切换录制方式')
        recorder.session_factory = factory

    @property
    def background_clip_factory(self):
        if self._background_clip_factory is not None:
            return self._background_clip_factory
        # DDCut versions before explicit registration already register their
        # clip-only factory in the 普通 and 切片 modes.
        if (getattr(self.context, 'name', '').casefold() == 'ddcut_replay'
                and not getattr(self._session_factory, 'supports_replay', True)):
            return self._session_factory
        return None

    def register_background_clip_backend(self, factory):
        if self._host().recorder.backend_owner is not self:
            raise RuntimeError('录制后端未注册')
        if not isinstance(factory, type) or not issubclass(factory, RecordingSession):
            raise TypeError('Recording backend must extend RecordingSession')
        self._background_clip_factory = factory

    def select_backend(self, session_factory=None):
        """Select the native or a plugin session class while all captures are idle."""
        recorder = self._host().recorder
        if recorder.backend_owner is not self or self._session_factory is None:
            raise RuntimeError('录制后端未注册')
        factory = session_factory or RecordingSession
        if not isinstance(factory, type) or not issubclass(factory, RecordingSession):
            raise TypeError('Recording backend must extend RecordingSession')
        if recorder.session_factory is factory:
            return
        if recorder.sessions:
            raise RuntimeError('请先停止当前录制和缓存，再切换录制方式或切片设置')
        recorder.session_factory = factory

    def record_danmaku(self, room_id, message):
        """Deliver captured chat to interested session backends in the GUI thread."""
        for session in tuple(self._host().recorder.sessions.values()):
            callback = getattr(session, 'record_danmaku', None)
            if callback is not None and session.room_id == str(room_id):
                callback(dict(message))

    def live_recording(self, source_id, session_id):
        host = self._host()
        session = host.recorder.sessions.get(self._tile(source_id))
        if session is None or session.session_id != session_id:
            raise RuntimeError('录制会话已变化，请刷新后重试')
        info = session.review_info()
        if not info:
            raise RuntimeError('尚无可回看的录制分段；请在插件加载后开始录制，等待首个关键帧分段完成')
        return dict(info)

    def sources(self):
        host = self._host()
        result = []
        for tile in self._sources(host):
            if not tile.room:
                continue
            session = host.recorder.sessions.get(tile)
            state = ('stopping' if session.stopping else
                     'reconnecting' if session.retry_at or getattr(session, 'refreshing', False) else
                     'recording' if session.recording else 'buffering') if session else 'idle'
            row = {'source_id': str(id(tile)), 'room': dict(tile.room),
                   'session_id': session.session_id if session else '',
                   'state': state, 'created_at': session.created_at if session else 0}
            if isinstance(tile, BackgroundRecordingSource):
                row['recording_mode'] = tile.recording_mode
            result.append(row)
        return result

    def _tile(self, source_id):
        host = self._host()
        return next((tile for tile in self._sources(host) if str(id(tile)) == source_id), None)

    @staticmethod
    def _sources(host):
        yield from host.wall.tiles
        yield from (source for source in host.recorder.sessions if isinstance(source, BackgroundRecordingSource))

    def control(self, source_id, action, *, session_id=None):
        host = self._host()
        tile = self._tile(source_id)
        if tile is None or not tile.room:
            raise RuntimeError('房间已移出画面墙')
        session = host.recorder.sessions.get(tile)
        if session_id is not None and (session.session_id if session else '') != session_id:
            raise RuntimeError('录制会话已变化，请刷新后重试')
        auto = getattr(host, 'auto_recording', None)
        background = isinstance(tile, BackgroundRecordingSource)
        if (background and action != 'save_replay'
                or action in ('record', 'stop') and auto and auto.controls_room(tile.room.get('room_id'))):
            raise RuntimeError('后台录制由「主播监控」管理')
        if action == 'record':
            host.capture_control.start_capture(tile, recording=True)
        elif action == 'stop':
            host.recorder.stop(tile)
        elif action == 'buffer':
            host.capture_control.start_replay(tile)
        elif action == 'stop_buffer':
            host.capture_control.stop_replay(tile)
        elif action == 'save_replay':
            return host.recorder.save_replay(tile)
        else:
            raise ValueError('Unknown recording action')
        return True

    def snapshot(self, source_id, session_id):
        host = self._host()
        tile = self._tile(source_id)
        session = host.recorder.sessions.get(tile)
        if session is None or session.session_id != session_id:
            raise RuntimeError('录制会话已变化，请刷新后重试')
        parts = session.review_parts()
        parts = [Path(part) for part in parts if Path(part).is_file()]
        if not parts:
            raise RuntimeError('尚无已封口分段，请稍后重试')
        info = session.snapshot_info(parts)
        init_files = [Path(segment['init']) for segment in info.get('segments', []) if segment.get('init')]
        token = host.recorder.pin_parts(parts + init_files)
        self._leases.add(token)
        return {'lease': token, 'session_id': session_id,
                'room': dict(session.room), 'parts': [str(part) for part in parts],
                'created_at': session.created_at, 'snapshot_at': time.time(), **info}

    def release(self, token):
        # Release remains valid after context deactivation during app shutdown.
        host = self.context.window
        if token in self._leases:
            host.recorder.release_parts(token)
            self._leases.discard(token)

    def close(self):
        for token in tuple(self._leases):
            self.release(token)
        recorder = getattr(self.context.window, 'recorder', None)
        if recorder is not None and getattr(recorder, 'backend_owner', None) is self:
            recorder.session_factory = RecordingSession
            recorder.backend_owner = None

    def open_settings(self):
        return self._host().open_settings('recording')
