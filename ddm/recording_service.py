"""Versioned plugin boundary for host capture operations and completed segments."""
from pathlib import Path
import time

from .recording import RecordingSession, ffmpeg_path


class RecordingService:
    api_version = 1

    def __init__(self, context):
        self.context = context
        self._leases = set()

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

    def register_backend(self, session_factory):
        """Use a RecordingSession subclass for new captures; existing ones keep running."""
        recorder = self._host().recorder
        if not isinstance(session_factory, type) or not issubclass(session_factory, RecordingSession):
            raise TypeError('Recording backend must extend RecordingSession')
        if recorder.backend_owner not in (None, self):
            raise RuntimeError('已有其他插件接管录制')
        recorder.backend_owner = self
        recorder.session_factory = session_factory

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
        for tile in host.wall.tiles:
            if not tile.room:
                continue
            session = host.recorder.sessions.get(tile)
            state = ('stopping' if session.stopping else
                     'reconnecting' if session.retry_at else
                     'recording' if session.recording else 'buffering') if session else 'idle'
            result.append({'source_id': str(id(tile)), 'room': dict(tile.room),
                           'session_id': session.session_id if session else '',
                           'state': state, 'created_at': session.created_at if session else 0})
        return result

    def _tile(self, source_id):
        host = self._host()
        return next((tile for tile in host.wall.tiles if str(id(tile)) == source_id), None)

    def control(self, source_id, action, *, session_id=None):
        host = self._host()
        tile = self._tile(source_id)
        if tile is None or not tile.room:
            raise RuntimeError('房间已移出画面墙')
        session = host.recorder.sessions.get(tile)
        if session_id is not None and (session.session_id if session else '') != session_id:
            raise RuntimeError('录制会话已变化，请刷新后重试')
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
        parts = list(dict.fromkeys(session.replay_parts + session.finished_parts()))
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
