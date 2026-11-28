"""Opt-in rolling replay caches, owned by the room while it is on the wall."""
from collections import deque
from dataclasses import dataclass, field
from tempfile import TemporaryDirectory
import time

from PySide6.QtCore import QObject, QSize, QTimer
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

from .danmaku_sources import is_live_danmaku_source
from .recording import RecordingManager, RecordingSession, ffmpeg_path
from .toolbar_panel import ToolbarPanel
from .wall_replay_dialog import ReplaySelection
from .wall_replay_settings import MAX_MINUTES, cache_minutes
from .wall_replay_timeline import ReplayTimeline, completed_clips, replay_index_path
from .wall_replay_view import TileReplayView


@dataclass(eq=False)
class _ReplaySource:
    room: dict
    minutes: int
    stream_url: str = ''
    stream_codec: str = ''
    stream_headers: dict = field(default_factory=dict)
    comments: deque = field(default_factory=deque)

    def isVisible(self):
        # A selected room can remain on the wall in a temporarily hidden layout.
        return True


class _ReplaySession(RecordingSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.segment_seconds = 4
        self.settings['recording_replay_minutes'] = self.tile.minutes

    def parts_directory(self):
        return self.folder / self.session_id

    def segment_options(self, pattern):
        args = super().segment_options(pattern)
        args[-1:-1] = ['-segment_list', str(replay_index_path(pattern)), '-segment_list_type', 'csv',
                      '-segment_list_size', str(MAX_MINUTES * 60 // self.segment_seconds + 12)]
        return args


class _ReplayRecorder(RecordingManager):
    retain_cache_at_eof = True

    def _continue(self, session, url, headers):
        if not url:
            session.retry_at = 0.0  # Leave the cached preview available while the room is offline.
            return
        super()._continue(session, url, headers)

    def _finalize(self, session, *, save_replay=True):
        super()._finalize(session, save_replay=False)
        directory = session.parts_directory()
        for item in directory.iterdir() if directory.is_dir() else ():
            if item.suffix in ('.log', '.csv'):
                item.unlink(missing_ok=True)
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


class WallReplay(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        ui = host.state.get('ui') or {}
        saved = ui.get('wall_replay_minutes')
        self.durations = {key: cache_minutes(value) for key, value in saved.items()
                          if isinstance(key, str) and key} if isinstance(saved, dict) else {}
        options = ui.get('wall_replay_options')
        options = options if isinstance(options, dict) else {}
        self.individual = options.get('individual') is True
        self.shared_minutes = cache_minutes(options.get('shared_minutes'))
        size = options.get('picker_size')
        self.picker_size = (tuple(size) if isinstance(size, (tuple, list)) and len(size) == 2
                            and all(type(value) is int and 0 < value <= 32767 for value in size) else None)
        self.dialog = None
        self.sources = {}
        self._reviews = {}
        self._buttons = set()
        self._muted_players = {}
        self.recorder = None
        self._directory = None
        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self.sync)

    def _wall_rooms(self):
        return {str(tile.room['room_id']): tile for tile in self.host.wall.tiles
                if tile.room.get('room_id') and not tile.property('pictureInPictureTemporary')}

    def is_selected(self, tile):
        return tile in self.host.wall.tiles and str(tile.room.get('room_id') or '') in self.sources

    def _choices(self):
        return {room_id: tile for room_id, tile in self._wall_rooms().items()
                if room_id in self.sources or tile.room.get('live')}

    def chat_rooms(self):
        return (room_id for room_id, source in self.sources.items() if is_live_danmaku_source(source.room))

    def record_comment(self, room_id, event):
        if (source := self.sources.get(room_id)) is not None:
            now = time.time()
            source.comments.append((now, dict(event)))
            self._trim_comments(source, now)

    def _trim_comments(self, source, now):
        cutoff = now - (source.minutes * 60 + 30)
        while source.comments and source.comments[0][0] < cutoff:
            source.comments.popleft()

    def choose(self):
        if self.dialog is not None:
            self.dialog.reject()
            return
        sidebar = self.host.sidebar
        anchor = sidebar.replay_button
        if not anchor.isVisible():
            return
        dialog = self.dialog = ReplaySelection(self.host, self._choices(), self.sources, self.durations,
                                               individual=self.individual, shared_minutes=self.shared_minutes)
        dialog.finished.connect(self._finish_selection)
        panel = ToolbarPanel(dialog, self.host, anchor, below=sidebar.side == 'top',
                             preferred_size=QSize(*self.picker_size) if self.picker_size else dialog.COMPACT_SIZE,
                             remember_size=self._remember_picker_size)
        if panel.attach():
            dialog.show()
            dialog.activateWindow()

    def _finish_selection(self, result):
        dialog, self.dialog = self.dialog, None
        dialog.deleteLater()
        if result == QDialog.Accepted:
            self.individual = dialog.individual.isChecked()
            self.shared_minutes = dialog.shared_minutes.value()
            self.configure(dialog.selected_durations(), remember_room_durations=self.individual)
            self.host._save_timer.start()

    def _remember_picker_size(self, size):
        self.picker_size = size.toTuple()
        self.host._save_timer.start()

    def options_state(self):
        return dict(individual=self.individual, shared_minutes=self.shared_minutes, picker_size=self.picker_size)

    def configure(self, durations, *, remember_room_durations=True):
        rooms = self._wall_rooms()
        before = set(self.sources)
        selected = {room_id: rooms[room_id] for room_id in durations
                    if room_id in rooms and (room_id in self.sources or rooms[room_id].room.get('live'))}
        updated = {room_id: cache_minutes(durations[room_id]) for room_id in selected}
        if remember_room_durations and any(self.durations.get(key) != value for key, value in updated.items()):
            self.durations.update(updated)
            self.host._save_timer.start()
        if selected and self.recorder is None:
            if not ffmpeg_path(self.host.settings):
                self.host._record_notice('找不到 FFmpeg，无法开启直播回放缓存。', {})
                return
            try:
                self._directory = TemporaryDirectory(prefix='ddm-wall-replay-')
            except OSError as error:
                self.host._record_notice(f'无法创建回放缓存目录：{error}', {})
                return
            settings = dict(self.host.settings, recording_dir=self._directory.name,
                            recording_codec='copy', recording_format='mkv')
            self.recorder = _ReplayRecorder(settings, self)
            self.recorder.session_factory = _ReplaySession
            self.recorder.noticeWithRoom.connect(self.host._record_notice)
        for room_id in self.sources.keys() - selected.keys():
            self._remove(room_id)
        if self.recorder is None:
            return
        for room_id, tile in selected.items():
            minutes = updated[room_id]
            source = self.sources.setdefault(room_id, _ReplaySource(dict(tile.room), minutes))
            source.minutes = minutes
            self._trim_comments(source, time.time())
            if view := self._reviews.get(room_id):
                view.set_limit(minutes * 60)
            session = self.recorder.sessions.get(source)
            if session is not None:
                session.settings['recording_replay_minutes'] = minutes
                session.pruned_at = 0
            else:
                source.stream_url = ''   # Confirming again retries a failed start.
        self.sync()
        if self.sources:
            self._timer.start()
        if before != set(self.sources):
            self.host.sync_danmaku()

    def sync(self):
        if not self.sources:
            self._sync_buttons(())
            self._timer.stop()
            return
        rooms = self._wall_rooms()
        pip = self.host.picture_in_picture
        moved = pip.moved_room_ids
        rooms.update((str(tile.room['room_id']), tile) for tile in pip.moved_tiles)
        removed = False
        for room_id, source in tuple(self.sources.items()):
            if room_id not in rooms:
                self._remove(room_id)
                removed = True
                continue
            tile = rooms[room_id]
            source.room = dict(tile.room)
            session = self.recorder.sessions.get(source)
            if view := self._reviews.get(room_id):
                if view.tile is not tile or tile.property('pictureInPicture') or tile.isHidden():
                    self._close_review(room_id)
                else:
                    clips = self._review_clips(session, view.snapshot.clips)
                    if clips and clips != view.snapshot.clips:
                        view.update_timeline(ReplayTimeline(clips, view.snapshot), source.comments)
                    view.sync_audio()
                    self._set_live_mute(room_id, self.host.players.get(tile) if view.in_history else None)
            if tile.room.get('live') is False and tile.room.get('live_known', True):
                if source.stream_url and session is not None:
                    session.next_url = ''
                    self.recorder._end_process(session)
                source.stream_url = ''
                continue
            url = tile.stream_url
            if not tile.room.get('live') or not url:
                continue
            headers, codec = dict(tile.stream_headers or {}), tile.stream_codec
            if (url, headers, codec) != (source.stream_url, source.stream_headers, source.stream_codec):
                source.stream_url, source.stream_headers, source.stream_codec = url, headers, codec
                if session is None:
                    self.recorder.start(source, recording=False)
                else:
                    self.recorder.on_resolved(source)
        self._sync_buttons(rooms[room_id] for room_id in self.sources if room_id not in moved)
        if not self.sources:
            self._timer.stop()
        if removed:
            self.host.sync_danmaku()

    def _sync_buttons(self, tiles):
        tiles = set(tiles)
        for tile in self._buttons ^ tiles:
            if isValid(tile):
                tile.replay_button.setVisible(tile in tiles)
                tile._layout_bottom_controls()
        self._buttons = tiles

    def _set_live_mute(self, room_id, player):
        previous = self._muted_players.get(room_id)
        if previous is player:
            return
        if previous is not None:
            previous.set_replay_muted(False)
            self._muted_players.pop(room_id)
        if player is not None:
            player.set_replay_muted(True)
            self._muted_players[room_id] = player

    def _review_clips(self, session, current=()):
        if session is None:
            return ()
        count = session.tile.minutes * 60 // session.segment_seconds + 2
        parts = session.finished_parts()[-count:]
        if parts == [clip.path for clip in current]:
            return current
        return completed_clips(parts)

    def _review_state_changed(self, room_id, view):
        tile = view.tile
        text = '返回直播' if view.in_history else '关闭回放时间轴'
        tile.replay_button.setToolTip(text)
        tile.replay_button.setAccessibleName(text)
        self._set_live_mute(room_id, self.host.players.get(tile) if view.in_history else None)
        if not view.in_history:
            self.host._publish_super_chats(room_id)

    def toggle_review(self, tile):
        if not self.is_selected(tile):
            return
        room_id = str(tile.room['room_id'])
        if room_id in self._reviews:
            self._close_review(room_id)
            return
        source = self.sources[room_id]
        session = self.recorder.sessions.get(source)
        snapshot = ReplayTimeline(self._review_clips(session))
        view = TileReplayView(tile, snapshot, snapshot.comments(source.comments), source.minutes * 60,
                              ffmpeg_path(self.host.settings), self.recorder, parent=self)
        self._reviews[room_id] = tile._replay_view = view
        tile.replay_button.setChecked(True)
        self._review_state_changed(room_id, view)
        view.failed.connect(lambda: self._review_failed(room_id))
        view.roomChanged.connect(lambda: self._close_review(room_id))
        view.historyChanged.connect(lambda: self._review_state_changed(room_id, view))
        try:
            view.start()
        except (RuntimeError, OSError):
            self._review_failed(room_id)

    def _review_failed(self, room_id):
        self.host._record_notice('无法播放这段回放', self.sources[room_id].room)
        self._close_review(room_id)

    def _close_review(self, room_id):
        if view := self._reviews.pop(room_id, None):
            tile = view.tile
            if isValid(tile):
                tile._replay_view = None
                tile.replay_button.setChecked(False)
                tile.replay_button.setToolTip('回看这路直播')
                tile.replay_button.setAccessibleName('回看这路直播')
            view.stop()
            self.host._publish_super_chats(room_id)
        self._set_live_mute(room_id, None)

    def _remove(self, room_id):
        self._close_review(room_id)
        self.recorder.stop(self.sources.pop(room_id))

    def shutdown(self):
        if self.dialog is not None:
            self.dialog.reject()
        self._timer.stop()
        for room_id in tuple(self.sources):
            self._remove(room_id)
        self._sync_buttons(())
        if self.recorder is not None:
            self.recorder.shutdown()
            self._directory.cleanup()
            self.recorder = None
