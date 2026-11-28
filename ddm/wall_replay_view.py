"""Replace a tile's composer with its replay controls and present the cached media."""
from bisect import bisect_left, bisect_right
import math

from PySide6.QtCore import QEvent, QObject, QRect, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QStyle, QStyleOptionSlider, QVBoxLayout, QWidget
from shiboken6 import isValid

from . import theme
from .playback_controls import ReplayLatestButton
from .player import TilePlayer
from .ui import SettingsSlider
from .video_surface import VideoSurface
from .wall_replay_preview import ReplayPreview
from .wall_replay_timeline import format_time


class ReplaySlider(SettingsSlider):
    def event(self, event):
        if event.type() in (QEvent.Hide, QEvent.UngrabMouse) and self.isSliderDown():
            self.setSliderPosition(self.value())
            self.setSliderDown(False)
        return super().event(event)

    def value_at(self, x):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        size = self.style().pixelMetric(QStyle.PM_SliderLength, option, self)
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
            round(x) - size // 2, max(1, self.width() - size), option.upsideDown)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setSliderDown(True)
            self.setSliderPosition(self.value_at(event.position().x()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.setSliderPosition(self.value_at(event.position().x()))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderPosition(self.value_at(event.position().x()))
            self.setSliderDown(False)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ReplayScale(QWidget):
    def __init__(self, tile, parent):
        super().__init__(parent)
        self.tile = tile
        self.duration = 0
        self.setFixedHeight(12)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_duration(self, seconds):
        if self.duration != seconds:
            self.duration = seconds
            self.update()

    def paintEvent(self, _event):
        if not self.duration:
            return
        painter = QPainter(self)
        color = '#dbe4ed' if self.tile.bottom.property('overVideo') else theme.TEXT2
        painter.setPen(theme.qcolor(color))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        rect = QRect(2, 1, self.width() - 4, 11)
        if self.width() >= 56:
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, '00:00')
            painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, format_time(self.duration))
        if self.width() >= 115:
            painter.drawText(rect, Qt.AlignCenter, format_time(self.duration // 2))
        for x in (2, self.width() // 2, self.width() - 3):
            painter.drawPoint(x, 0)


class TileReplayView(QObject):
    failed = Signal()
    roomChanged = Signal()
    historyChanged = Signal()

    def __init__(self, tile, snapshot, comments, seconds, executable, recorder, *, parent):
        super().__init__(parent)
        self.tile = tile
        self.snapshot = snapshot
        self.comments = comments
        self._comment_times = [position for position, _ in comments]
        self._cursor = 0
        self._comment_through = -1
        self._limit = seconds
        self._recorder = recorder
        self._media = None
        self._lease = None
        self._pending_seek = None
        self._seek_started = False
        self._resume_after_seek = False
        self._room_id = tile.room.get('room_id')
        self.surface = VideoSurface(tile)
        self.surface.setObjectName('ReplayVideo')
        self.surface.setStyleSheet('#ReplayVideo {background: #000;}')
        self.surface.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.player = TilePlayer(self.surface, self)
        self.player.freeze_watch = False
        self.player.stateChanged.connect(self._state_changed)
        self.widget = QWidget(tile.bottom)
        self.widget.setObjectName('ReplayProgress')
        self.widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)
        track = QWidget(self.widget)
        track.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        timeline = QVBoxLayout(track)
        timeline.setContentsMargins(0, 0, 0, 0)
        timeline.setSpacing(0)
        self.slider = ReplaySlider(track, fixed_width=False)
        self.slider.setFixedHeight(16)
        self.slider.setAccessibleDescription('拖动时预览，松手后跳转')
        self.slider.setAccessibleName('回放时间轴')
        self.slider.setTracking(False)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.seek)
        self.scale = ReplayScale(tile, track)
        timeline.addWidget(self.slider)
        timeline.addWidget(self.scale)
        self.status = QLabel(self.widget, objectName='TileTitle')
        self.status.setToolTip('当前可回看的缓存时长')
        self.status.setAccessibleName(self.status.toolTip())
        self.latest = ReplayLatestButton(self.widget)
        self.latest.setProperty('overVideo', bool(tile.bottom.property('overVideo')))
        self.latest.clicked.connect(self.go_latest)
        layout.addWidget(track, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.latest)
        self.preview = ReplayPreview(self.slider, tile, lambda position: self.snapshot.frame_source(position), executable)
        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self.update_position)

    def start(self):
        tile = self.tile
        bar = tile.bottom.layout()
        bar.insertWidget(bar.indexOf(tile.status_label) + 1, self.widget, 1)
        tile.bottom.contrast_groups += ((self.widget,),)
        tile.roomChanged.connect(self._check_room)
        self.widget.show()
        tile._layout_bottom_controls()
        tile.installEventFilter(self)
        self.update_position()
        self._timer.start()

    def sync_surface(self):
        if not self.in_history:
            return
        self.surface.setGeometry(self.tile.video.geometry())
        self.surface.setMask(self.tile.video.mask())
        self.surface.raise_()

    def sync_audio(self):
        if self.in_history:
            self.player.sync_audio(int(self.tile.volume), self.tile.muted, int(self.tile.audio_channel))

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Move, QEvent.Resize, QEvent.Hide):
            self.preview.hide()
        return False

    def _check_room(self):
        if self.tile.room.get('room_id') != self._room_id:
            self.roomChanged.emit()

    def _state_changed(self, state):
        if state == 'error':
            self.failed.emit()

    def set_limit(self, seconds):
        self._limit = seconds

    @property
    def in_history(self):
        return self._media is not None

    def update_timeline(self, snapshot, events):
        self.snapshot = snapshot
        self.comments = snapshot.comments(events)
        self._comment_times = [position for position, _ in self.comments]
        self._cursor = bisect_right(self._comment_times, self._comment_through)

    def toggle_pause(self):
        if self._pending_seek is not None:
            self._resume_after_seek = not self._resume_after_seek
            self.tile.pause_button.set_paused(not self._resume_after_seek)
            return
        if (self.player._prop('eof-reached', False) and not self.tile.room.get('live')
                and self.snapshot.end <= self._media.end):
            self.seek(self.slider.minimum())
            self._resume_after_seek = True
            return
        paused = not self.player.paused
        self.player.set_paused(paused)
        self.tile.pause_button.set_paused(paused)

    def seek(self, position):
        if self.tile.room.get('live') and position == self.slider.maximum():
            self._return_to_live()
            return
        self._seek(position)

    def go_latest(self):
        self.preview.hide()
        if self.tile.room.get('live'):
            self._return_to_live()
        else:
            self._seek(self.snapshot.end)

    def _seek(self, position, *, continuous=False):
        if not self.snapshot.clips:
            return
        position = max(self.snapshot.start, self.snapshot.end - self._limit,
                       min(position, self.snapshot.end - .15))
        media = self._media
        if self._pending_seek is None:
            self._resume_after_seek = media is None or not self.player.paused
        if not continuous:
            self.tile.video_danmaku.clear_comments()
            self._comment_through = math.nextafter(position, -math.inf)
            self._cursor = bisect_left(self._comment_times, position)
        self._pending_seek = position
        self._seek_started = False
        if media is not None and media.start <= position <= media.end - .15:
            self.player.set_paused(True)
            return
        self._media = self.snapshot
        old_lease = self._lease
        self._lease = self._recorder.pin_parts([clip.path for clip in self._media.clips])
        try:
            self.player.play(self._media.media_url())
            self.player.set_paused(True)
        except (OSError, RuntimeError):
            self.failed.emit()
            return
        finally:
            if old_lease is not None:
                self._recorder.release_parts(old_lease)
        if media is None:
            tile = self.tile
            tile.video_danmaku.clear()
            tile.video_danmaku.set_active(True)
            tile.video_danmaku.set_paused(True)
            tile.pause_button.set_paused(True)
            tile.spinner.hide()
            tile.pause_overlay.hide()
            self.surface.show()
            tile.raise_overlays()
            self.sync_audio()
            self.historyChanged.emit()

    def _sync_slider(self, position):
        start = max(math.ceil(self.snapshot.start), math.ceil(self.snapshot.end - self._limit))
        end = max(start, math.ceil(self.snapshot.end))
        self.slider.setEnabled(end > start)
        self.latest.setEnabled(self.in_history or (bool(self.snapshot.clips) and not self.tile.room.get('live')))
        self.status.setVisible(self.widget.width() >= 86)
        retained = min(self._limit, self.snapshot.end - self.snapshot.start)
        self.status.setText(('已缓存 ' if self.widget.width() >= 175 else '') + format_time(retained))
        if not self.slider.isSliderDown():
            with QSignalBlocker(self.slider):
                self.slider.setRange(start, end)
                self.slider.setValue(end if position is None else int(position))
            self.scale.set_duration(end - start)

    def _return_to_live(self):
        if self.in_history:
            self.player.stop(keep_core=True)
            self.surface.hide()
            self._media = None
            self._pending_seek = None
            self._resume_after_seek = False
            self._release_lease()
            self._restore_live_tile()
            self.historyChanged.emit()
        self.update_position()

    def update_position(self):
        if not self.in_history:
            self._sync_slider(None)
            return
        local, duration = self.player.playback_timing()
        if local is None or not duration:
            self._sync_slider(self._pending_seek)
            return
        position = self._media.start + local
        if self._pending_seek is not None:
            target = min(self._pending_seek - self._media.start, max(0, duration - .15))
            if not self._seek_started:
                self._seek_started = self.player.seek_to(target)
                return
            if self.player._prop('seeking', False) or abs(local - target) > .35:
                return
            self._pending_seek = None
            if self._resume_after_seek:
                self._resume_after_seek = False
                self.player.set_paused(False)
        if position < max(self.snapshot.start, self.snapshot.end - self._limit) - .35:
            self._seek(max(self.snapshot.start, self.snapshot.end - self._limit))
            return
        self._sync_slider(position)
        eof = self.player._prop('eof-reached', False)
        if eof and not self.player.paused:
            if self.snapshot.end > self._media.end + .15:
                self._seek(self._media.end, continuous=True)
                return
            if self.tile.room.get('live'):
                self._return_to_live()
                return
            self.player.set_paused(True)
        if self.tile.pause_button.paused != (self.player.paused or eof):
            self.tile.pause_button.set_paused(self.player.paused or eof)
        paused = self.player.paused or eof or self.player._prop('paused-for-cache', False)
        if self.tile.video_danmaku.paused != paused:
            self.tile.video_danmaku.set_paused(paused)
        if not paused:
            while self._cursor < len(self.comments) and self.comments[self._cursor][0] <= position:
                self.tile.video_danmaku.add_event(self.comments[self._cursor][1])
                self._cursor += 1
            self._comment_through = max(self._comment_through, position)

    def _release_lease(self):
        if self._lease is not None:
            self._recorder.release_parts(self._lease)
            self._lease = None

    def _restore_live_tile(self):
        tile = self.tile
        tile.video_danmaku.clear()
        tile.video_danmaku.set_active(tile._player_active)
        tile.set_paused(tile.paused)
        if tile._buffering or tile._connecting:
            tile.spinner.start()
        tile._layout_areas()

    def stop(self):
        self._timer.stop()
        if isValid(self.preview):
            self.preview.stop()
        if isValid(self.surface):
            self.surface.hide()
        tile = self.tile
        self.player.release()
        self._release_lease()
        if not isValid(tile):
            self.deleteLater()
            return
        tile.removeEventFilter(self)
        tile.roomChanged.disconnect(self._check_room)
        self.surface.deleteLater()
        tile.bottom.contrast_groups = tuple(group for group in tile.bottom.contrast_groups if self.widget not in group)
        tile.bottom.layout().removeWidget(self.widget)
        self.widget.hide()
        self.widget.deleteLater()
        if self.in_history:
            self._restore_live_tile()
        else:
            tile._layout_bottom_controls()
        self.deleteLater()
