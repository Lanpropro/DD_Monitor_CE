"""One selectable match picture, independently mixed audio, and labelled chat."""
from __future__ import annotations

import re
import sys
import threading
import time
from collections import deque
from dataclasses import replace
from urllib.parse import urlsplit

from PySide6.QtCore import QEasingCurve, QEvent, QMetaObject, QMimeData, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QDrag, QIcon, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFrame,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLayout, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QTextEdit, QVBoxLayout, QWidget)

from ddm.widgets import AUTO_QUALITY, Avatar, DanmakuPanel, ROOM_MIME, Tile
from ddm.fullscreen_cursor import FullscreenCursor
from ddm.dialogs import SHORTCUT_ACTIONS
from ddm import config as config_module, motion, theme
from .engine import route_pcm_s16_stereo, Alignment, Match, RATE, SafetyBuffer, LateBuffer, match_scenes, refine_match, assisted_match, mix_pcm, resample_pcm
from .media import Chat, Decoder, PlatformChat

COLORS = ("#38bdf8", "#fb7185", "#a78bfa", "#4ade80", "#fbbf24", "#fb923c")
ROW_MIME = "application/x-ddm-match-sync-row"


def cache_gap(history, target):
    """Describe missing target content, separately from scene-match confidence."""
    bounds = history.bounds()
    if bounds is None:
        return "尚未收到播放缓存"
    previous = getattr(history, 'previous', None)
    previous_bounds = previous.bounds() if previous is not None else None
    earliest = min(bounds[0], previous_bounds[0]) if previous_bounds else bounds[0]
    latest = max(bounds[1], previous_bounds[1]) if previous_bounds else bounds[1]
    if target < earliest:
        return f"目标早于已保留缓存约 {earliest - target:.1f} 秒"
    if target > latest:
        return f"目标内容尚未收到，缺少约 {target - latest:.1f} 秒"
    continuous = history.bounds_at(target)
    if continuous is None or not continuous[0] <= target <= continuous[1]:
        return "目标位置存在断流缓存缺口"
    return ""


def parse_room(text: str, manager=None) -> str:
    text = text.strip()
    platform = manager.platform_for(text) if manager is not None else None
    if platform is not None:
        if platform.playback_mode != "stream":
            raise ValueError("此平台不提供直播流，无法加入比赛二路")
        return platform.normalize(text)
    if not text.isdigit():
        link = urlsplit(text)
        if link.scheme not in ("http", "https") or link.hostname != "live.bilibili.com":
            raise ValueError("请输入 B 站房间号，或已启用平台的房间号/官方链接")
        found = re.fullmatch(r"/(?:h5/)?([0-9]+)/?", link.path)
        if not found:
            raise ValueError("链接中没有有效的直播房间号")
        text = found[1]
    if int(text) <= 0:
        raise ValueError("直播房间号必须大于零")
    return str(int(text))


class Canvas(QFrame):
    def __init__(self, parent=None, selecting=False):
        super().__init__(parent)
        self.image = QImage()
        self.waiting = False
        self.zoom_crop = False
        self.frame_key = None
        self.frame = None
        self.missing_since = None
        self.preview_only = False
        self.preview_shift = None
        self.transparent_background = False
        self.presented = 0
        self.repeated = 0
        self.selecting = selecting
        self.crop = QRectF(0, 0, 1, 1)
        self.anchor = None
        self.image_rect = QRectF()
        self.setMinimumSize(320, 180)

    def set_frame(self, item):
        key = item[0] if item is not None else None
        if key == self.frame_key and (item is not None or self.image.isNull()):
            self.repeated += 1
            return
        if item is not None:
            self.presented += 1
        self.frame_key = key
        self.frame = item
        self.image = (item[1] if isinstance(item[1], QImage) else QImage.fromData(item[1])) if item is not None else QImage()
        self.update()

    def show_at(self, decoder, timestamp):
        frame = decoder.history.frame_at(timestamp)
        if frame is not None:
            ready = decoder.picture_at(timestamp) if hasattr(decoder, "picture_at") else frame
            if ready is not None:
                self.set_frame(ready)
            return ready
        return None

    def playback_waiting(self, decoder, timestamp, frame, shared_wait=False):
        if frame is not None:
            self.missing_since = None
            return shared_wait
        now = time.monotonic()
        if self.missing_since is None:
            self.missing_since = now
        bounds = decoder.history.bounds_at(timestamp) if decoder is not None else None
        retained = (bounds is not None and bounds[0] <= timestamp <= bounds[1]
                    and self.frame_key is not None and 0 <= timestamp - self.frame_key <= .15
                    and now - self.missing_since <= .15)
        return shared_wait or not retained

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.transparent_background:
            painter.fillRect(self.rect(), theme.qcolor(theme.CONTENT) if theme.is_light() else QColor("#101216"))
        if self.image.isNull():
            if self.waiting:
                return
            painter.setPen(theme.qcolor(theme.TEXT1 if self.transparent_background else theme.TEXT3))
            painter.drawText(self.rect(), Qt.AlignCenter, "将左侧关注栏卡片拖到这里，加入比赛二路")
            return
        image = self.image
        source = image.rect()
        if self.zoom_crop:
            rect = self.crop
            source = QRect(round(rect.x() * image.width()), round(rect.y() * image.height()),
                           max(1, round(rect.width() * image.width())),
                           max(1, round(rect.height() * image.height()))).intersected(source)
        size = source.size().scaled(self.size(), Qt.KeepAspectRatio)
        self.image_rect = QRectF((self.width() - size.width()) / 2,
                                (self.height() - size.height()) / 2,
                                size.width(), size.height())
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(self.image_rect, image, QRectF(source))
        if self.selecting:
            painter.setPen(QPen(QColor("#38bdf8"), 2))
            rect = self.crop
            painter.drawRect(QRectF(
                self.image_rect.x() + rect.x() * self.image_rect.width(),
                self.image_rect.y() + rect.y() * self.image_rect.height(),
                rect.width() * self.image_rect.width(), rect.height() * self.image_rect.height()))

    def _point(self, position):
        rect = self.image_rect
        return QPointF(max(0, min(1, (position.x() - rect.x()) / rect.width())),
                       max(0, min(1, (position.y() - rect.y()) / rect.height())))

    def mousePressEvent(self, event):
        if self.selecting and not self.image_rect.isEmpty() and event.button() == Qt.LeftButton:
            self.anchor = self._point(event.position())

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            self.crop = QRectF(self.anchor, self._point(event.position())).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        self.anchor = None


class AudioFeed(QObject):
    """Own the output device and its timer entirely on the audio thread."""
    def __init__(self, pump, output, fmt):
        super().__init__()
        self.pump, self.output, self.fmt = pump, output, fmt
        self.timer = None

    @Slot()
    def start(self):
        pump = self.pump
        pump.sink = QAudioSink(self.output, self.fmt, self)
        pump.sink.stateChanged.connect(self.state_changed)
        pump.sink.setBufferSize(RATE * 4 * 200 // 1000)
        pump.device = pump.sink.start()
        if pump.device is None:
            pump.status.emit("无法启动音频输出")
            self.stop()
            return
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.fill)
        self.timer.start()
        self.fill()
        pump.status.emit("声音已接管，结束观看后恢复原程序的静音设定")

    @Slot()
    def fill(self):
        self.pump.fill()

    @Slot()
    def state_changed(self):
        if self.pump.sink is not None and self.pump.sink.error().value:
            self.pump.status.emit("音频设备出错；检查系统默认设备后停止并重新开始")
            self.stop()

    @Slot()
    def stop(self):
        if self.timer is not None:
            self.timer.stop()
        with self.pump.lock:
            sink, self.pump.sink = self.pump.sink, None
            self.pump.device = None
        if sink is not None:
            sink.stop()
            sink.deleteLater()


class AudioPump(QObject):
    status = Signal(str)

    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.sink = None
        self.device = None
        self.anchor = 0.0
        self.written = 0
        self.media_written = 0.0
        self.clock_segments = deque()
        self.correction = 0.0
        self.last_fill = None
        self.lock = threading.RLock()
        self.thread = None
        self.feed = None
        self.snapshot = (1.0, ())
        self.played = 0
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.update_snapshot)
        self.devices = QMediaDevices(self)
        self.device_id = None
        self.devices.audioOutputsChanged.connect(self._device_changed)

    def start(self):
        self.stop()
        self.anchor = time.monotonic()
        self.written = 0
        self.media_written = 0.0
        self.clock_segments.clear()
        self.correction = 0.0
        self.played = 0
        output = QMediaDevices.defaultAudioOutput()
        self.device_id = bytes(output.id())
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if output.isNull() or not output.isFormatSupported(fmt):
            self.status.emit("音频输出不可用；请检查系统默认播放设备")
            return
        self.update_snapshot()
        self.thread = QThread(self)
        self.feed = AudioFeed(self, output, fmt)
        self.feed.moveToThread(self.thread)
        self.thread.started.connect(self.feed.start)
        self.thread.finished.connect(self.feed.deleteLater)
        self.thread.start()
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.last_fill = None
        if self.thread is not None:
            QMetaObject.invokeMethod(self.feed, "stop", Qt.BlockingQueuedConnection)
            self.thread.quit()
            self.thread.wait()
            self.thread.deleteLater()
            self.thread = self.feed = None
        sink, self.sink = self.sink, None
        if sink is not None:
            sink.stop()
            sink.deleteLater()
        self.device = None

    def clock(self):
        with self.lock:
            return self._clock()

    def _clock(self):
        if self.sink is None:
            return time.monotonic() + self.correction
        played = self.played if self.thread is not None else self.sink.processedUSecs() * RATE / 1_000_000
        while len(self.clock_segments) > 1 and self.clock_segments[0][1] <= played:
            self.clock_segments.popleft()
        if self.clock_segments:
            first, end, media, rate = self.clock_segments[0]
            return self.anchor + media + min(max(0, played - first), end - first) / RATE * rate + self.correction
        return self.anchor + played / RATE + self.correction

    def update_snapshot(self):
        # Widgets and room collections belong to the GUI thread. The output
        # thread receives only immutable values and thread-safe media histories.
        shifts = self.viewer.shifts()
        rate = self.viewer.playback_rate
        inputs = []
        for room_id, row in self.viewer.rows.items():
            if (row.decoder is not None and row.audible.isChecked() and not row.paused
                    and not self.viewer.sync_waiting and row.sync_state == "已同步"):
                inputs.append((row.decoder.history, shifts[room_id],
                               rate + self.viewer.relative_rates.get(room_id, 1.0) - 1.0,
                               row.channel.currentData(), row.volume.value() * row.mix_gain))
        self.snapshot = (rate, tuple(inputs))

    def fill(self):
        if self.thread is None:
            self.update_snapshot()
        with self.lock:
            self._fill()

    def _fill(self):
        if self.sink is None or self.device is None:
            return
        now = time.perf_counter()
        if self.last_fill is not None and now - self.last_fill > .1:
            print(f"[二路音频] 供给间隔 {(now - self.last_fill) * 1000:.1f}ms", file=sys.stderr, flush=True)
        self.last_fill = now
        self.played = self.sink.processedUSecs() * RATE / 1_000_000
        rate, sources = self.snapshot
        for _ in range(3):
            if self.sink is None or self.device is None:
                break
            frames = min(2048, self.sink.bytesFree() // 4)
            if frames < 240:
                break
            media_frames = max(1, round(frames * rate))
            clock = self.anchor + self.media_written + self.correction
            inputs = []
            for history, shift, local_rate, channel, volume in sources:
                pcm = history.pcm_at(clock + shift, max(1, round(frames * local_rate)))
                pcm = route_pcm_s16_stereo(pcm, channel)
                inputs.append((resample_pcm(pcm, frames), volume))
            count = self.device.write(mix_pcm(inputs, frames))
            if count <= 0:
                break
            written = count // 4
            actual_rate = media_frames / frames
            self.clock_segments.append((self.written, self.written + written, self.media_written, actual_rate))
            self.media_written += written / RATE * actual_rate
            self.written += written

    def _device_changed(self):
        current = bytes(QMediaDevices.defaultAudioOutput().id())
        if self.viewer.running and current != self.device_id:
            self.start()


class Results(QObject):
    matched = Signal(int, dict)
    completed = Signal(int, int, dict)


class ComparisonPanel(QFrame):
    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.cards = {}
        self.shown_rooms = ()
        self.setObjectName("MatchSyncCompare")
        self.setMinimumHeight(185)
        self.setMaximumHeight(300)
        self.setStyleSheet(f"""
            #MatchSyncCompare {{ background: {theme.CONTENT}; border: none;
                border-radius: {theme.RADIUS_MD}px; }}
            #MatchSyncCompare QLabel, #MatchSyncCompare QCheckBox {{ color: {theme.TEXT1}; }}
            #MatchSyncCompare QScrollArea {{ border: none; background: transparent; }}
        """)
        heading = QHBoxLayout()
        self.heading_label = QLabel()
        heading.addWidget(self.heading_label)
        heading.addStretch()
        self.target = QComboBox()
        self.target.setMinimumWidth(150)
        self.target.currentIndexChanged.connect(lambda: viewer.render())
        heading.addWidget(self.target)
        self.zoom = QCheckBox("放大框选区域")
        self.zoom.setChecked(True)
        heading.addWidget(self.zoom)
        self.close_button = QPushButton("收起对照")
        self.close_button.setObjectName("ChipButton")
        self.close_button.setToolTip("隐藏对照画面，保留已调整的偏移并继续播放。")
        self.close_button.clicked.connect(lambda: viewer.compare.setChecked(False))
        heading.addWidget(self.close_button)
        body = QWidget()
        self.cards_layout = QHBoxLayout(body)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.addLayout(heading)
        layout.addWidget(scroll, 1)
        self.hide()

    def rooms_to_show(self):
        reference, rows = self.viewer.alignment.reference, self.viewer.rows
        others = tuple(key for key in rows if key != reference)
        selected = self.target.currentData()
        secondary = others if len(rows) <= 4 else ((selected,) if selected in others else others[:1])
        return tuple(key for key in (reference, *secondary) if key in rows)

    def render(self, clock, shifts):
        rows = self.viewer.rows
        if tuple(self.cards) != tuple(rows):
            for card, *_ in self.cards.values():
                self.cards_layout.removeWidget(card)
                card.deleteLater()
            self.cards.clear()
            self.shown_rooms = ()
            for room_id in rows:
                card = QWidget()
                name = QLabel()
                canvas = Canvas()
                canvas.transparent_background = self.viewer.skin_visible
                canvas.setMinimumSize(200, 110)
                state = QLabel()
                state.setWordWrap(True)
                heading = QHBoxLayout()
                heading.addWidget(name, 1)
                assist = QPushButton("辅助自动对齐")
                assist.setObjectName("MatchSyncAssist")
                assist.clicked.connect(lambda _checked=False, key=room_id: self.viewer.assist_alignment(key))
                assist.setVisible(room_id != self.viewer.alignment.reference)
                heading.addWidget(assist)
                layout = QVBoxLayout(card)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addLayout(heading)
                layout.addWidget(canvas, 1)
                layout.addWidget(state)
                card.hide()
                self.cards[room_id] = (card, name, canvas, state)
        reference = self.viewer.alignment.reference
        for key, (card, *_rest) in self.cards.items():
            card.findChild(QPushButton, "MatchSyncAssist").setVisible(key != reference)
        selected = self.target.currentData()
        choices = [(key, row.label()) for key, row in rows.items() if key != reference]
        if choices != [(self.target.itemData(i), self.target.itemText(i))
                       for i in range(self.target.count())]:
            self.target.blockSignals(True)
            self.target.clear()
            for key, label in choices:
                self.target.addItem(label, key)
            self.target.setCurrentIndex(max(0, self.target.findData(selected)))
            self.target.blockSignals(False)
        self.target.setVisible(len(rows) > 4)
        self.heading_label.setText("偏移对照 · 全部直播间" if len(rows) <= 4 else "偏移对照 · 主画面与选中直播间")
        shown = self.rooms_to_show()
        if shown != self.shown_rooms:
            for card, *_ in self.cards.values():
                self.cards_layout.removeWidget(card)
                card.hide()
            for key in shown:
                card = self.cards[key][0]
                self.cards_layout.addWidget(card, 1)
                card.show()
            self.shown_rooms = shown
        for room_id, row in rows.items():
            if room_id not in shown:
                continue
            _card, name, canvas, state = self.cards[room_id]
            name.setText(f"{'主画面' if room_id == reference else '对照'} · {row.label()}")
            style = f"color: {row.color};"
            if name.styleSheet() != style:
                name.setStyleSheet(style)
            crop, zoom = QRectF(*row.crop), self.zoom.isChecked()
            repaint = canvas.crop != crop or canvas.zoom_crop != zoom
            canvas.crop, canvas.zoom_crop = crop, zoom
            if not row.paused:
                if room_id == reference:
                    canvas.preview_only = False
                    canvas.preview_shift = None
                    if self.viewer.canvas.frame is not None:
                        canvas.set_frame(self.viewer.canvas.frame)
                    waiting = self.viewer.canvas.waiting
                else:
                    target = clock + shifts[room_id]
                    bounds = row.decoder.history.bounds_at(target) if row.decoder else None
                    canvas.preview_only = False
                    if (self.viewer.alignment.automatic and row.match_confirmed and row.awaiting_confirmation and bounds is not None
                            and not bounds[0] <= target <= bounds[1] - .05):
                        latest = row.decoder.history.latest()
                        preview_bounds = row.decoder.history.bounds_at(latest[0]) if latest else None
                        if preview_bounds and preview_bounds[1] - preview_bounds[0] > .1:
                            preview = clock + canvas.preview_shift if canvas.preview_shift is not None else None
                            if preview is None or not preview_bounds[0] <= preview <= preview_bounds[1] - .05:
                                reserve = min(self.viewer.safety_buffer.target, preview_bounds[1] - preview_bounds[0] - .05)
                                canvas.preview_shift = preview_bounds[1] - reserve - clock
                            target = clock + canvas.preview_shift
                            canvas.preview_only = True
                    if not canvas.preview_only:
                        canvas.preview_shift = None
                    frame = canvas.show_at(row.decoder, target) if row.decoder else None
                    waiting = canvas.playback_waiting(row.decoder, target, frame, self.viewer.sync_waiting)
                repaint |= canvas.waiting != waiting
                canvas.waiting = waiting
            row.actual_position = canvas.frame_key
            if repaint:
                canvas.update()
            relative = shifts[room_id] - shifts.get(reference, 0)
            position = ("主画面基准" if room_id == reference else "与主画面偏移相同" if abs(relative) < .05 else
                        f"相对主画面{'提前' if relative >= 0 else '延后'} {abs(relative):.1f} 秒")
            if room_id != reference:
                if room_id in self.viewer.independent_shifts or (self.viewer.alignment.automatic and not row.match_confirmed):
                    position = "画面时间差尚未确认"
                elif not self.viewer.alignment.automatic:
                    position = f"设置偏移 {row.delay.value() - self.viewer.rows[reference].delay.value():+.2f} 秒"
            if canvas.preview_only:
                position = "同步目标超出当前缓存；正在独立预览，尚未与主画面对齐"
                playback = "已暂停" if row.paused else "正在准备预览画面" if canvas.waiting else "缓存预览播放中（本路静音）"
            else:
                playback = "已暂停" if row.paused else "等待播放缓存" if canvas.waiting else row.playback_status()
            text = f"{position} · {playback}"
            if state.text() != text:
                state.setText(text)


class SettingsPanel(QWidget):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.setObjectName("MatchSyncSettings")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumHeight(130)
        self.setMaximumHeight(240)
        self.setStyleSheet(f"""
            #MatchSyncSettings, #MatchSyncRows {{
                background: transparent; border: none;
            }}
            #MatchSyncSettings QLabel, #MatchSyncSettings QCheckBox {{ color: palette(window-text); }}
            #MatchSyncSettings QScrollArea, #MatchSyncSettings QScrollArea > QWidget {{
                background: transparent; border: none;
            }}
            #MatchSyncSettings QPushButton, #MatchSyncSettings QLineEdit,
            #MatchSyncSettings QComboBox, #MatchSyncSettings QDoubleSpinBox {{
                background: palette(button); color: palette(window-text);
                border: 1px solid palette(mid);
                border-radius: {theme.RADIUS_MD}px; padding: 4px 6px;
            }}
            #MatchSyncSettings QPushButton:hover {{
                background: palette(light); border-color: palette(highlight);
            }}
            #MatchSyncSettings QPushButton:checked {{
                background: rgba(251, 114, 153, 45); border-color: palette(highlight);
            }}
        """)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), theme.RADIUS_LG, theme.RADIUS_LG)
        top = QPainterPath()
        top.addRoundedRect(QRectF(0, 0, self.width(), self.height() / 2),
                           theme.RADIUS_MD, theme.RADIUS_MD)
        path = path.united(top)
        tint = QLinearGradient(0, 0, 0, self.height())
        top_color, bottom_color = theme.qcolor(theme.CONTENT), theme.qcolor(theme.BG)
        top_color.setAlpha(round(255 * self.viewer.panel_alpha) if self.viewer.skin_visible else 238)
        bottom_color.setAlpha(round(255 * self.viewer.panel_alpha) if self.viewer.skin_visible else 245)
        tint.setColorAt(0, top_color)
        tint.setColorAt(1, bottom_color)
        painter.fillPath(path, tint)


class RoomRow(QFrame):
    def __init__(self, viewer, room_id, preferences, color):
        super().__init__(viewer)
        self.viewer = viewer
        self.room_id = room_id
        self.setObjectName("MatchSyncRoomRow")
        self.anchor = None
        self.setAcceptDrops(True)
        self.platform = viewer.context.manager.platform_for(room_id)
        self.decoder = None
        self.chat = None
        self.paused = False
        self.sync_state = "准备缓存"
        self.mix_gain = 0.0
        self.recovery_since = None
        self.was_isolated = False
        self.actual_position = None
        self.picture_wait_since = None
        self.match_confirmed = False
        self.match_failures = 0
        self.alignment_started = time.monotonic()
        self.recheck_alignment = False
        self.rematch_locally = False
        self.user_confirmed = False
        self.user_confirmed_lag = None
        self.review_alignment = False
        self.awaiting_confirmation = False
        self.next_analysis = 0.0
        self.alignment_hint = None
        self.large_candidate = None
        self.correction_remaining = 0.0
        self.reset_pending = False
        self.needs_epoch_samples = False
        room = next((item for item in getattr(viewer.context.window, "rooms", [])
                     if str(item.get("room_id") or "") == room_id), {})
        self.title = room.get("title") or (viewer.sources.get(room_id) or {}).get("title") or ""
        self.quality = int(preferences.get("quality", 10000 if self.platform is not None else 250))
        self.actual_quality = 0
        self.pending = deque(maxlen=2000)
        self.color = preferences.get("color", color)
        if self.color not in COLORS:
            self.color = color
        self.crop = tuple(preferences.get("crop", (0, 0, 1, 1)))
        self.match_text = "等待画面"
        self.video_text = "未开始"
        self.chat_text = "弹幕未连接"
        self.buffer_text = ""
        self.alias = QLineEdit(preferences.get("alias", ""))
        self.alias.setParent(self)
        self.alias.hide()
        self.alias.setPlaceholderText("主播名称")
        self.alias.setFixedWidth(100)
        self.avatar = Avatar(self.label(), len(viewer.rows), size=32, parent=self)
        self.avatar_key = None
        self.setCursor(Qt.OpenHandCursor)
        self.refresh_avatar()
        self.main_button = QPushButton("主画面")
        self.main_button.setCheckable(True)
        self.main_button.setFixedWidth(64)
        self.main_button.setToolTip("选择这位主播作为主画面，其他路声音与弹幕继续播放。")
        self.main_button.clicked.connect(lambda: viewer.select_main(room_id))
        self.audible = QCheckBox("声音")
        self.audible.setChecked(preferences.get("audible", True))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(preferences.get("volume", getattr(
            viewer.context.window, "settings", {}).get("default_volume", config_module.DEFAULT_VOLUME))))
        self.volume.setFixedWidth(72)
        self.volume_number = QLabel(str(self.volume.value()))
        self.volume_number.setFixedWidth(26)
        self.volume_number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.volume.valueChanged.connect(lambda value: self.volume_number.setText(str(value)))
        self.channel = QComboBox()
        for label, value in (("原始声道", 0), ("仅左输出", 3), ("仅右输出", 4)):
            self.channel.addItem(label, value)
        self.channel.setCurrentIndex(max(0, self.channel.findData(preferences.get("audio_channel", 0))))
        self.channel.setToolTip("仅左/仅右：将完整声音混为单声道，送到指定耳机一侧。")
        self.channel.setFixedWidth(100)
        self.channel.currentIndexChanged.connect(viewer.changed)
        for signal in (self.channel.currentIndexChanged, self.volume.valueChanged, self.audible.toggled):
            signal.connect(viewer.sync_picture)
        self.delay = self._offset(0 if viewer.automatic.isChecked() else preferences.get("delay", 0))
        self.previous_delay = self.delay.value()
        self.delay.setFixedWidth(74)
        self.delay.installEventFilter(viewer)
        self.show_chat = QCheckBox("弹幕")
        self.show_chat.setChecked(preferences.get("show_chat", True))
        self.color_choice = QComboBox()
        for name, value in zip(("蓝色", "粉色", "紫色", "绿色", "黄色", "橙色"), COLORS):
            swatch = QPixmap(16, 16)
            swatch.fill(QColor(value))
            self.color_choice.addItem(QIcon(swatch), name, value)
        self.color_choice.setCurrentIndex(self.color_choice.findData(self.color))
        self.color_choice.currentIndexChanged.connect(self._color)
        self.color_choice.setFixedWidth(82)
        self.color_choice.setToolTip("弹幕来源颜色")
        self.decrease = QPushButton("−")
        self.increase = QPushButton("+")
        self.decrease.setToolTip("− 负数：相对提前本路画面、声音和弹幕。单位秒；必要时同时延后其他路。")
        self.increase.setToolTip("+ 正数：延后本路画面、声音和弹幕。单位秒，例如 +3 表示延后 3 秒。")
        for button in (self.decrease, self.increase):
            button.setFixedWidth(24)
        self.decrease.clicked.connect(lambda: viewer.show_comparison(self.room_id))
        self.increase.clicked.connect(lambda: viewer.show_comparison(self.room_id))
        self.decrease.clicked.connect(self.delay.stepDown)
        self.increase.clicked.connect(self.delay.stepUp)
        region = QPushButton("选择比赛画面")
        region.setFixedWidth(112)
        region.setToolTip("仅在自动对齐困难时使用：框选各主播画面中相同的比赛内容，避开头像和字幕。")
        region.clicked.connect(lambda: viewer.choose_crop(self))
        self.realign = QPushButton("重新对齐")
        policy = self.realign.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.realign.setSizePolicy(policy)
        self.realign.setToolTip("重新匹配本路比赛画面，不重启直播流，不改变其他路已确认偏移。")
        self.realign.clicked.connect(lambda: viewer.retry_alignment(room_id))
        remove = QPushButton("移除")
        remove.setFixedWidth(52)
        remove.clicked.connect(lambda: viewer.remove_room(room_id))
        self.join = QPushButton("增加延后并加入")
        self.join.setSizePolicy(policy)
        self.join.setToolTip("本路内容到达更晚；增加整组观看延迟后加入，原有各路保持相对同步。")
        self.join.clicked.connect(lambda: viewer.confirm_alignment(room_id))
        self.join.hide()
        self.control_widgets = (self.avatar, self.main_button, self.realign, self.join, self.audible, self.volume,
                                self.volume_number, self.channel,
                                self.show_chat, self.color_choice, QLabel("偏移"), self.decrease,
                                self.delay, self.increase, region, remove)
        controls = QGridLayout()
        self.controls_grid = controls
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(4)
        columns = []
        column = 0
        for index, widget in enumerate(self.control_widgets):
            if index in (4, 8, 10, 14):
                controls.setColumnStretch(column, 1)
                column += 1
            columns.append(column)
            controls.addWidget(widget, 0, column)
            column += 1
        self.control_columns = columns
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.status.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.offset_hint = QLabel("单位：秒 · + 正数延后本路 · − 负数相对提前本路")
        self.offset_hint.setObjectName("MatchSyncOffsetHint")
        self.offset_hint.setWordWrap(True)
        self.offset_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.offset_hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.offset_hint.setStyleSheet(
            f"QLabel#MatchSyncOffsetHint {{ color: palette(window-text); font-size: {theme.FONT_CAPTION}px; }}")
        controls.addWidget(self.status, 1, 0, 1, columns[10] - 1)
        controls.addWidget(self.offset_hint, 1, columns[10], 1, columns[14] - columns[10])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        line = QHBoxLayout()
        line.addLayout(controls, 1)
        layout.addLayout(line)
        self.setFrameShape(QFrame.NoFrame)
        self.refresh_status()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.delay.setToolTip("单位秒；+ 延后本路，− 相对提前本路（必要时延后其他路）。画面、声音和弹幕一起移动。")
        self.delay.valueChanged.connect(viewer._delay_changed)
        self.volume.valueChanged.connect(viewer.changed)
        self.audible.toggled.connect(viewer.changed)
        self.show_chat.toggled.connect(self._chat_toggle)
        self.alias.textChanged.connect(viewer.changed)
        self.alias.textChanged.connect(self.refresh_avatar)
        self.alias.editingFinished.connect(viewer.update_main_choices)

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.LayoutRequest and hasattr(self, 'control_columns'):
            self.viewer.align_room_controls()
        return result

    @staticmethod
    def _offset(value):
        spin = QDoubleSpinBox()
        spin.setRange(-60, 60)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setSuffix(" s")
        spin.setValue(value)
        return spin

    def refresh_avatar(self, *_args):
        self.avatar.setToolTip(f"{self.label()} · 拖动整张卡片调整顺序，右键修改名称")
        self.setToolTip(self.avatar.toolTip())
        sidebar = getattr(self.viewer.context.window, "sidebar", None)
        item = next((item for item in getattr(sidebar, "_items", [])
                     if str(item.room.get("room_id") or "") == self.room_id), None)
        pixmap = item.thumb.face_pixmap() if item is not None else None
        if pixmap is not None and not pixmap.isNull():
            if self.avatar_key != pixmap.cacheKey():
                self.avatar_key = pixmap.cacheKey()
                self.avatar.set_pixmap_image(pixmap)
        elif self.avatar_key is None:
            self.avatar.setText(self.label()[0])

    def contextMenuEvent(self, event):
        menu = motion.AnimatedMenu(self)
        action = menu.addAction("修改主播名称")
        def rename():
            value, accepted = QInputDialog.getText(self, "修改主播名称", "主播名称", text=self.alias.text())
            if accepted and value.strip():
                self.alias.setText(value.strip())
                self.viewer.update_main_choices()
        action.triggered.connect(rename)
        menu.exec_context(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.anchor = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.anchor is not None and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self.anchor).manhattanLength() >= QApplication.startDragDistance()):
            anchor, self.anchor = self.anchor, None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(ROW_MIME, self.room_id.encode("utf-8"))
            drag.setMimeData(mime)
            pixmap = QPixmap(self.size())
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1))
            painter.setBrush(theme.qcolor(theme.ELEVATED))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
            painter.end()
            self.render(pixmap, QPoint(), QRegion(), QWidget.DrawChildren)
            pixmap, hotspot = motion.lifted_drag(pixmap, anchor)
            drag.setPixmap(pixmap)
            drag.setHotSpot(hotspot)
            self.viewer.begin_row_drag(self.room_id)
            try:
                drag.exec(Qt.MoveAction)
            finally:
                self.viewer.end_row_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.anchor = None
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        source = event.source()
        if isinstance(source, RoomRow) and source.viewer is self.viewer and event.mimeData().hasFormat(ROW_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(ROOM_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)
        if isinstance(event.source(), RoomRow) and event.source().viewer is self.viewer:
            self.viewer.preview_row_drag(self.mapTo(self.viewer.controls.widget(), event.position().toPoint()))

    def dropEvent(self, event):
        source = event.source()
        if isinstance(source, RoomRow) and source.viewer is self.viewer and event.mimeData().hasFormat(ROW_MIME):
            if self.viewer.dragged_row is not None:
                self.viewer.finish_row_drag(self.mapTo(self.viewer.controls.widget(), event.position().toPoint()))
            else:
                self.viewer.reorder_room(source.room_id, self.room_id, event.position().y() >= self.height() / 2)
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(ROOM_MIME):
            self.viewer.dropEvent(event)
        else:
            event.ignore()

    def label(self):
        return self.alias.text().strip() or "未命名主播"

    def _color(self, *_args):
        self.color = self.color_choice.currentData()
        self.viewer.changed()

    def _chat_toggle(self):
        self.pending.clear()
        if self.viewer.running:
            self.viewer._start_chat(self)
        self.viewer.changed()

    def preferences(self):
        return {"room_id": self.room_id, "alias": self.alias.text(), "color": self.color,
                "audible": self.audible.isChecked(), "volume": self.volume.value(),
                "audio_channel": self.channel.currentData(),
                "quality": self.quality,
                "delay": self.delay.value(),
                "show_chat": self.show_chat.isChecked(), "crop": list(self.crop)}

    def refresh_status(self):
        self.realign.setVisible(self.viewer.alignment.automatic and self.room_id != self.viewer.alignment.reference)
        match_text = self.match_text
        if not self.viewer.alignment.automatic:
            match_text = "自动对齐已关闭；手动偏移"
        elif self.room_id == self.viewer.alignment.reference:
            match_text = "主画面基准"
        text = f"{self.video_text} · {match_text} · {self.chat_text}"
        self.status.setText(text + f" · {self.playback_status()}" + (f" · {self.buffer_text}" if self.buffer_text else ""))

    def playback_status(self):
        if self.room_id in self.viewer.independent_shifts and self.viewer.alignment.automatic:
            return "独立播放（未对齐，已静音）"
        if self.sync_state == "已同步":
            if self.room_id in self.viewer.independent_shifts:
                return "独立播放（未对齐）"
            if self.viewer.alignment.automatic and self.correction_remaining > .1001:
                return f"平滑校正中，剩余约 {self.correction_remaining:.2f} 秒"
            return "播放正常" if self.room_id == self.viewer.alignment.reference else (
                "已对齐" if self.viewer.alignment.automatic else "按当前偏移播放")
        return self.sync_state


class Viewer(QDialog):
    def __init__(self, context, sources, initial_room=None):
        super().__init__(context.window)
        self.context = context
        self.sources = sources
        self.rows = {}
        self.dragged_row = None
        self.row_animations = {}
        self.row_preview = []
        self.saved_rooms = {str(item["room_id"]): item for item in context.setting("rooms", [])}
        self.running = False
        self.overlay_pending = {}
        self.overlay_last = ""
        self.alignment = Alignment()
        self.alignment.buffer_seconds = 6.0
        self.safety_buffer = SafetyBuffer()
        self.late_buffer = LateBuffer()
        self.playback_rate = 1.0
        self.stable_reference_shift = None
        self.skin_visible = False
        self.panel_alpha = 1.0
        self.independent_shifts = {}
        self.rematch_rooms = set()
        self.rematch_admit = set()
        self.last_health_update = None
        self.analysis_cursor = 0
        self.admitted_rooms = set()
        self.rendered_shifts = {}
        self.relative_rates = {}
        self.shift_reference = None
        self.shift_updated = None
        self.generation = 0
        self.matching = False
        self.analysis_serial = 0
        self.locked_clock = None
        self.sync_waiting = False
        self.offset_repositioning = False
        self.offset_target = None
        self.suppressed = {}
        self.prefer_highest = False
        self.embedded = False
        self.hidden_host_widgets = {}
        self.sidebar_style = None
        self.setAcceptDrops(True)
        self.setWindowTitle("比赛二路同步")
        self.setObjectName("MatchSync")
        self.setStyleSheet("#MatchSync { background: transparent; }")
        self.resize(1320, 880)
        self.main = QComboBox(self)
        self.main.setFixedWidth(180)
        self.main.currentIndexChanged.connect(self._main_changed)
        self.automatic = QCheckBox("自动对齐比赛画面")
        self.automatic.setToolTip("关闭时保存当前相对偏移；重新勾选或主动修改偏移可解除保存状态。切换不收起对照。")
        self.automatic.setChecked(context.setting("automatic", True))
        self.alignment.automatic = self.automatic.isChecked()
        self.automatic.toggled.connect(self._automatic_changed)
        self.compare = QCheckBox("对照微调")
        self.compare.toggled.connect(self.set_comparison_visible)
        self.late_notice = QLabel()
        self.late_notice.setObjectName("MatchSyncLateNotice")
        self.late_notice.setTextFormat(Qt.PlainText)
        self.late_notice.setWordWrap(True)
        self.late_notice.setMinimumWidth(0)
        self.late_notice.setMaximumWidth(420)
        self.late_notice.hide()
        self.input = QLineEdit()
        self.input.setPlaceholderText("房间号、平台前缀或官方直播链接")
        self.input.returnPressed.connect(self._add_input)
        add = QPushButton("添加直播间")
        add.clicked.connect(self._add_input)
        use_current = QPushButton("加入当前观看的房间")
        use_current.clicked.connect(self.import_current)
        self.add_controls = (self.input, add, use_current)
        self.settings_panel = SettingsPanel(self)
        self.settings_height = 220
        self.minimize_settings = QPushButton("最小化")
        self.minimize_settings.setFixedWidth(68)
        self.minimize_settings.setToolTip("收起设置栏，保留画面、声音和弹幕播放。")
        self.minimize_settings.clicked.connect(lambda: self.set_settings_visible(False))
        self.restore_settings = QPushButton("展开设置")
        self.restore_settings.setFixedWidth(90)
        self.restore_settings.clicked.connect(lambda: self.set_settings_visible(True))
        self.restore_settings.hide()
        heading = QHBoxLayout()
        heading.setSpacing(6)
        self.main.hide()
        heading.addWidget(self.automatic)
        heading.addWidget(self.compare)
        heading.addWidget(self.late_notice)
        for widget in self.add_controls:
            heading.addWidget(widget)
        heading.addStretch()
        heading.addWidget(self.minimize_settings)
        self.picture = Tile({})
        self.restore_settings.setParent(self.picture.bottom)
        self.restore_settings.setObjectName("TileCtrl")
        self.restore_settings.setFixedHeight(26)
        self.picture.bottom.layout().insertWidget(self.picture.bottom.layout().indexOf(self.picture.danmaku_button),
                                                 self.restore_settings, 0, Qt.AlignVCenter)
        self.restore_settings.hide()
        self.picture.bottom.installEventFilter(self)
        self.canvas = Canvas(self.picture.video)
        # Canvas owns the empty-state prompt, including when its skin is transparent.
        self.picture.cover.installEventFilter(self)
        self.picture.cover.hide()
        video_layout = QVBoxLayout(self.picture.video)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.addWidget(self.canvas)
        self.picture.roomDropped.connect(self._add_dragged)
        self.picture.qualityChanged.connect(self._quality_changed)
        self.picture.volumeChanged.connect(lambda _room, value: self._picture_setting("volume", value))
        self.picture.muteToggled.connect(lambda _room, muted: self._picture_setting("audible", not muted))
        self.picture.audioChannelChanged.connect(lambda _room, value: self._picture_setting("channel", value))
        self.picture.reloadRequested.connect(lambda _room: self._reload_picture())
        self.picture.closeRequested.connect(lambda room: self.remove_room(str(room.get("room_id") or "")))
        self.picture.pauseToggled.connect(lambda _room: self._pause_picture())
        self.picture.fullscreenRequested.connect(lambda _tile: self._fullscreen_picture())
        self.picture.recordingRequested.connect(self._record_picture)
        self.fullscreen_dialog = None
        self.panel = DanmakuPanel(self)
        self.panel.roomDropped.connect(self._add_dragged)
        self.panel.body.setAcceptDrops(False)
        self.panel.body.viewport().setAcceptDrops(False)
        self.panel.setMinimumWidth(260)
        self.panel.set_placeholder("各路弹幕以主播名称标注来源直播间")
        settings = getattr(context.window, "settings", {})
        self.video_danmaku = getattr(self.picture, "video_danmaku", None)
        if self.video_danmaku is not None:
            # Canvas is painted by Qt; a native VLC overlay can obscure its backing store.
            if hasattr(self.video_danmaku, "set_native_video"):
                self.video_danmaku.set_native_video(False)
            self.video_danmaku.apply_settings(settings)
            self.picture.videoDanmakuChanged.connect(lambda: self.overlay_pending.clear())
        self.panel.apply_style(settings.get("danmaku_font", ""),
                               int(settings.get("danmaku_font_size") or 13))
        self.panel.set_max_blocks(int(settings.get("danmaku_max_blocks") or 3000))
        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(4)
        split.setStyleSheet("QSplitter::handle { background: transparent; } QSplitter::handle:hover { background: palette(mid); }")
        self.picture_split = split
        self.notice = QLabel("选择共同比赛区域可提高匹配成功率；自动估计约 0.5 秒分辨率，手动微调 0.1 秒。")
        self.notice.setWordWrap(True)
        body = QWidget()
        body.setObjectName("MatchSyncRows")
        self.rows_layout = QVBoxLayout(body)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(2)
        self.rows_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.rows_layout.setAlignment(Qt.AlignTop)
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.controls = QScrollArea()
        self.controls.setFrameShape(QFrame.NoFrame)
        self.controls.viewport().setAutoFillBackground(False)
        self.controls.setWidgetResizable(True)
        self.controls.setWidget(body)
        body.installEventFilter(self)
        self.controls.viewport().installEventFilter(self)
        body.setAcceptDrops(True)
        self.controls.viewport().setAcceptDrops(True)
        self.controls.setMinimumHeight(60)
        self.body_split = QSplitter(Qt.Vertical)
        self.body_split.setHandleWidth(4)
        self.body_split.setStyleSheet("QSplitter::handle { background: transparent; } QSplitter::handle:hover { background: palette(mid); }")
        self.body_split.addWidget(self.picture)
        self.comparison_panel = ComparisonPanel(self)
        self.body_split.addWidget(self.comparison_panel)
        self.body_split.addWidget(self.settings_panel)
        self.body_split.setSizes([660, 0, 220])
        self.audio_status = QLabel()
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(12, 8, 12, 8)
        settings_layout.setSpacing(4)
        settings_layout.addLayout(heading)
        settings_layout.addWidget(self.controls, 1)
        footer = QHBoxLayout()
        footer.setSpacing(16)
        footer.addWidget(self.notice, 1)
        self.audio_status.setWordWrap(True)
        self.audio_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        footer.addWidget(self.audio_status, 1)
        settings_layout.addLayout(footer)
        self.left_pane = QWidget()
        left_layout = QVBoxLayout(self.left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(self.body_split, 1)
        split.addWidget(self.left_pane)
        split.addWidget(self.panel)
        split.setSizes([930, 330])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(split)
        self.audio = AudioPump(self)
        self.audio.status.connect(self.audio_status.setText)
        self.host_audio_timer = QTimer(self)
        self.host_audio_timer.setInterval(100)
        self.host_audio_timer.timeout.connect(self._suppress_host_audio)
        self.render_timer = QTimer(self)
        self.render_timer.setTimerType(Qt.PreciseTimer)
        self.render_timer.setInterval(33)
        self.render_timer.timeout.connect(self.render)
        self.match_timer = QTimer(self)
        self.match_timer.setInterval(500)
        self.match_timer.timeout.connect(self.analyse)
        self.results = Results()
        self.results.matched.connect(self._matched)
        self.results.completed.connect(self._analysis_finished)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self.save)
        if initial_room:
            self.add_room(str(initial_room.get("room_id") or ""),
                          {"alias": initial_room.get("uname") or ""})
        index = self.main.findData(context.setting("main_room", ""))
        if index >= 0:
            self.main.setCurrentIndex(index)
        self._automatic_changed()
        theme.signals().changed.connect(self.refresh_appearance)
        controller = getattr(context.window, "skin_controller", None)
        if controller is not None:
            controller.changed.connect(self.refresh_appearance)
        self.refresh_appearance()

    def refresh_appearance(self, *_args):
        if not hasattr(self, "appearance_styles"):
            self.appearance_styles = {}
        def styled(widget, value):
            if self.appearance_styles.get(widget) != value:
                self.appearance_styles[widget] = value
                widget.setStyleSheet(value)
        controller = getattr(self.context.window, "skin_controller", None)
        self.skin_visible = bool(controller is not None and controller.layer.path and not controller.layer.error)
        # A fully transparent panel cannot keep text legible over a detailed skin.
        # Keep a readable theme veil even at zero mask; the same slider strengthens it.
        self.panel_alpha = .72 + .28 * max(0, min(100, controller.layer.mask)) / 100 if self.skin_visible else 1.0
        color = theme.qcolor(theme.CONTENT)
        background = (f"rgba({color.red()}, {color.green()}, {color.blue()}, {round(255 * self.panel_alpha)})"
                      if self.skin_visible else "palette(base)")
        styled(self.comparison_panel, f"""
            #MatchSyncCompare {{ background: {background}; border: none; border-radius: 8px; }}
            #MatchSyncCompare QLabel, #MatchSyncCompare QCheckBox {{ color: palette(window-text); }}
            #MatchSyncCompare QScrollArea, #MatchSyncCompare QScrollArea > QWidget {{ background: transparent; border: none; }}
        """)
        styled(self.panel, f"#MatchSync #DanmakuPanel {{ background: {background}; border: none; }}")
        for widget, name in ((self.panel.bar, "DanmakuBar"),
                             (self.panel.findChild(QWidget, "DanmakuHeader"), "DanmakuHeader")):
            styled(widget, f"#MatchSync #{name} {{ background: transparent; border: none; }}")
        for label in self.panel.bar.findChildren(QLabel):
            styled(label, "color: palette(window-text); background: transparent;")
        self.panel.body.viewport().setAutoFillBackground(False)
        styled(self.picture, f"#MatchSync #Tile {{ background: {background}; }} "
                                   "#MatchSync #TileVideo, #MatchSync #TileBottom { background: transparent; }"
                                   if self.skin_visible else "")
        self.canvas.transparent_background = self.skin_visible
        self.canvas.update()
        for _card, _name, canvas, _state in self.comparison_panel.cards.values():
            canvas.transparent_background = self.skin_visible
            canvas.update()
        self.settings_panel.update()

    def embed(self, content):
        self.embedded = True
        self.setParent(content, Qt.Widget)
        self.setGeometry(content.rect())
        content.installEventFilter(self)
        for widget in self.add_controls:
            widget.hide()
        self.notice.setText("从左侧关注栏拖入直播间；选择主画面，各路声音与弹幕会合并。")

    def _shortcut_action(self, watched, event):
        if not self.isVisible() or not isinstance(watched, QWidget):
            return None
        if watched.window() not in (self.window(), self.fullscreen_dialog):
            return None
        if QApplication.activeModalWidget() not in (None, self, self.fullscreen_dialog):
            return None
        if isinstance(watched, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return None
        if isinstance(watched, QComboBox) and watched.isEditable():
            return None
        pressed = QKeySequence(event.keyCombination()).toString()
        shortcuts = getattr(self.context.window, "shortcuts", {})
        return next((action for action, _label, default in SHORTCUT_ACTIONS
                     if pressed and pressed == shortcuts.get(action, default)), None)

    def _handle_shortcut(self, action):
        if action == "restore":
            if self.fullscreen_dialog is not None:
                self.fullscreen_dialog.close()
            return
        if action == "focus" and self.fullscreen_dialog is not None:
            self.fullscreen_dialog.close()
            return
        point = QCursor.pos()
        target = None
        if self.picture.isVisible() and self.picture.rect().contains(self.picture.mapFromGlobal(point)):
            target = self.rows.get(self.main.currentData())
        else:
            for key, (card, _name, _canvas, _state) in self.comparison_panel.cards.items():
                if card.isVisible() and card.rect().contains(card.mapFromGlobal(point)):
                    target = self.rows.get(key)
                    break
        if action == "solo":
            for row in self.rows.values():
                row.audible.setChecked(row is target)
        elif target is not None:
            if action == "focus":
                self._fullscreen_picture()
            elif action == "mute":
                target.audible.toggle()
            elif action == "video_danmaku":
                self.picture.danmaku_button.toggle()
            elif action == "audio_cycle":
                if not target.audible.isChecked():
                    target.channel.setCurrentIndex(0)
                    target.audible.setChecked(True)
                elif target.channel.currentIndex() == target.channel.count() - 1:
                    target.audible.setChecked(False)
                else:
                    target.channel.setCurrentIndex(target.channel.currentIndex() + 1)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress):
            action = self._shortcut_action(watched, event)
            if action is not None:
                event.accept()
                if event.type() == QEvent.KeyPress and not event.isAutoRepeat():
                    self._handle_shortcut(action)
                return True
        if watched is self.picture.cover and event.type() == QEvent.Show:
            watched.hide()
            return False
        if (getattr(self, "controls", None) is not None
                and watched in (self.controls.widget(), self.controls.viewport())
                and event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop)
                and isinstance(event.source(), RoomRow) and event.source().viewer is self
                and event.mimeData().hasFormat(ROW_MIME)):
            point = watched.mapTo(self.controls.widget(), event.position().toPoint())
            if event.type() == QEvent.Drop:
                self.finish_row_drag(point)
            else:
                self.preview_row_drag(point)
            event.acceptProposedAction()
            return True
        if watched is self.picture.bottom and event.type() == QEvent.Resize:
            QTimer.singleShot(0, self._layout_restore_control)
        if event.type() == QEvent.FocusIn:
            for key, row in self.rows.items():
                if watched is row.delay:
                    self.show_comparison(key)
                    break
        if watched in self.hidden_host_widgets and event.type() == QEvent.Show:
            watched.hide()
        if self.embedded and watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        QApplication.instance().installEventFilter(self)
        if self.embedded:
            suspend = getattr(self.context.window, "set_match_sync_playback", None)
            if callable(suspend):
                suspend(True)
            self.host_audio_timer.start()
            self._suppress_host_audio()
        if self.embedded and not self.hidden_host_widgets:
            host = self.context.window
            for widget in (getattr(host, "wall", None), getattr(host, "empty_hint", None)):
                if widget is not None:
                    self.hidden_host_widgets[widget] = not widget.isHidden()
                    widget.installEventFilter(self)
                    widget.hide()
        self._sync_sidebar_marks()
        super().showEvent(event)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def _sync_sidebar_marks(self):
        sidebar = getattr(self.context.window, "sidebar", None)
        if not self.embedded or sidebar is None or self.isHidden():
            return
        now = time.monotonic()
        state = (self.running, tuple((key, id(row.decoder)) for key, row in self.rows.items()),
                 getattr(sidebar, "side", "left"), getattr(sidebar, "collapsed", False),
                 len(getattr(sidebar, "_items", [])), theme.is_light())
        if state == getattr(self, "sidebar_marks_state", None) and now < self.sidebar_marks_due:
            return
        self.sidebar_marks_state, self.sidebar_marks_due = state, now + .25
        for row in self.rows.values():
            row.refresh_avatar()
        if self.sidebar_style is None:
            self.sidebar_style = sidebar.styleSheet()
            sidebar.setStyleSheet(self.sidebar_style + """
                #NavItem[onWall="true"] { border: none; }
                #NavItem[matchSync="true"], #NavItem[matchSync="true"][onWall="true"] {
                    border: 1px solid #fb7299;
                }
            """)
        for item in getattr(sidebar, "_items", []):
            row = self.rows.get(str(item.room.get("room_id") or ""))
            active = self.running and row is not None and row.decoder is not None
            if item.property("matchSync") != active:
                item.setProperty("matchSync", active)
                item.style().unpolish(item)
                item.style().polish(item)
                item.update()
        self._sync_strip_marks(sidebar, True)

    def _sync_strip_marks(self, sidebar, enabled):
        strip = getattr(sidebar, "_head_strip", None)
        for room_id, avatar in getattr(strip, "_avatars", {}).items():
            for mark in avatar.findChildren(QLabel, options=Qt.FindDirectChildrenOnly):
                if f"background: {theme.ACCENT};" in mark.styleSheet():
                    if enabled:
                        mark.setProperty("matchSyncHidden", True)
                        mark.hide()
                    elif mark.property("matchSyncHidden"):
                        mark.setProperty("matchSyncHidden", False)
                        mark.show()
            frame = avatar.findChild(QFrame, "MatchSyncStripMark")
            row = self.rows.get(room_id)
            active = enabled and self.running and row is not None and row.decoder is not None
            if active and frame is None:
                frame = QFrame(avatar)
                frame.setObjectName("MatchSyncStripMark")
                frame.setAttribute(Qt.WA_TransparentForMouseEvents)
                frame.setGeometry(avatar.rect())
                frame.setStyleSheet(f"background: transparent; border: 1px solid {theme.PINK};"
                                   f" border-radius: {avatar.width() // 2}px;")
            if frame is not None:
                frame.setVisible(bool(active))
                frame.raise_()

    def set_settings_visible(self, visible):
        if visible and self.fullscreen_dialog is not None:
            self.fullscreen_dialog.close()
        if not visible:
            self.settings_height = self.settings_panel.height()
            self.compare.setChecked(False)
        self.settings_panel.setVisible(visible)
        self.restore_settings.setVisible(not visible)
        self._layout_restore_control()
        if visible:
            self.left_pane.layout().activate()
            self.body_split.setSizes([
                max(1, self.body_split.height() - self.settings_height -
                    (self.comparison_panel.height() if self.compare.isChecked() else 0)),
                self.comparison_panel.height() if self.compare.isChecked() else 0, self.settings_height])

    def _layout_restore_control(self):
        tile = self.picture
        tile._layout_bottom_controls()
        if self.restore_settings.isHidden():
            return
        self.restore_settings.setFixedWidth(58 if tile.width() < 420 else 90)
        self.restore_settings.setText("展开" if tile.width() < 420 else "展开设置")
        layout = tile.bottom.layout()
        fixed = [layout.itemAt(i).widget() for i in range(layout.count())]
        fixed = [widget for widget in fixed if widget is not None and not widget.isHidden()
                 and widget not in (tile.volume_slider, tile.status_label)]
        margins = layout.contentsMargins()
        remaining = tile.width() - margins.left() - margins.right() - layout.spacing() * (len(fixed) + 1) - 8
        remaining -= sum(widget.sizeHint().width() if widget is tile.recording_time else widget.width() for widget in fixed)
        tile.volume_slider.setFixedWidth(max(18, min(86, remaining)))
        layout.activate()

    def set_comparison_visible(self, visible):
        sizes = self.body_split.sizes()
        self.comparison_panel.setVisible(visible)
        self.generation += 1
        height = 240 if visible else 0
        self.body_split.setSizes([max(1, sizes[0] + sizes[1] - height), height, sizes[2]])
        if visible:
            self.comparison_panel.render(self.audio.clock(), self.shifts())

    def reorder_room(self, room_id, target_id, after=False):
        if room_id == target_id or room_id not in self.rows or target_id not in self.rows:
            return
        keys = list(self.rows)
        keys.remove(room_id)
        keys.insert(keys.index(target_id) + int(after), room_id)
        self.rows = {key: self.rows[key] for key in keys}
        for index, row in enumerate(self.rows.values()):
            self.rows_layout.insertWidget(index, row)
        self.update_main_choices()
        self.changed()

    def align_room_controls(self):
        rows = list(self.rows.values())
        if not rows:
            return
        widths = [max(min(widget.maximumWidth(), max(widget.minimumWidth(), widget.sizeHint().width()))
                      for widget in widgets) for widgets in zip(*(row.control_widgets for row in rows))]
        for row in rows:
            for column, width in zip(row.control_columns, widths):
                if row.controls_grid.columnMinimumWidth(column) != width:
                    row.controls_grid.setColumnMinimumWidth(column, width)

    def begin_row_drag(self, room_id):
        self.dragged_row = room_id
        self.row_preview = list(self.rows)
        self.row_slots = {key: row.geometry() for key, row in self.rows.items()}
        self.rows_layout.setEnabled(False)
        self.rows[room_id].hide()

    def preview_row_drag(self, point):
        if self.dragged_row is None:
            return
        order = [key for key in self.rows if key != self.dragged_row]
        index = sum(point.y() >= self.row_slots[key].center().y() for key in order)
        order.insert(index, self.dragged_row)
        if order != self.row_preview:
            self.row_preview = order
            y = 0
            for key in order:
                row = self.rows[key]
                if key != self.dragged_row:
                    previous = self.row_animations.pop(key, None)
                    if previous is not None:
                        previous.stop()
                        previous.deleteLater()
                    target = QPoint(self.row_slots[key].x(), y)
                    if motion.enabled():
                        animation = QPropertyAnimation(row, b"pos", self)
                        animation.setDuration(150)
                        animation.setEasingCurve(QEasingCurve.OutCubic)
                        animation.setStartValue(row.pos())
                        animation.setEndValue(target)
                        self.row_animations[key] = animation
                        animation.start()
                    else:
                        row.move(target)
                y += self.row_slots[key].height() + self.rows_layout.spacing()
        viewport = self.controls.viewport()
        local = self.controls.widget().mapTo(viewport, point)
        bar = self.controls.verticalScrollBar()
        if local.y() < 24:
            bar.setValue(bar.value() - 12)
        elif local.y() > viewport.height() - 24:
            bar.setValue(bar.value() + 12)

    def finish_row_drag(self, point):
        if self.dragged_row is None:
            return
        self.preview_row_drag(point)
        self.rows = {key: self.rows[key] for key in self.row_preview}
        self.end_row_drag()
        self.update_main_choices()
        self.changed()

    def end_row_drag(self):
        for animation in self.row_animations.values():
            animation.stop()
            animation.deleteLater()
        self.row_animations.clear()
        if self.dragged_row in self.rows:
            self.rows[self.dragged_row].show()
        self.dragged_row = None
        for index, row in enumerate(self.rows.values()):
            self.rows_layout.insertWidget(index, row)
        self.rows_layout.setEnabled(True)
        self.rows_layout.activate()

    def _queue_rematch(self, row, local=False):
        row.alignment_hint = None
        row.large_candidate = None
        row.match_confirmed = False
        row.match_failures = 0
        row.alignment_started = time.monotonic()
        row.recheck_alignment = False
        row.rematch_locally = local
        row.next_analysis = 0.0
        row.match_text = "正在重新对齐比赛画面"
        self.independent_shifts.pop(row.room_id, None)
        self.alignment.candidates.pop(row.room_id, None)
        self.rematch_rooms.add(row.room_id)
        if row.room_id in self.admitted_rooms:
            self.rematch_admit.add(row.room_id)
        row.refresh_status()

    def assist_alignment(self, room_id):
        reference = self.alignment.reference
        cards = self.comparison_panel.cards
        if room_id == reference or reference not in cards or room_id not in cards:
            return
        frames = (self.canvas.frame, cards[room_id][2].frame)
        if not self.running or any(frame is None for frame in frames):
            self.notice.setText("请等待两路对照都有画面，再辅助自动对齐")
            return
        decoders = (self.rows[reference].decoder, self.rows[room_id].decoder)
        origins = tuple(decoder.history.origin for decoder in decoders)
        dialog = QDialog(self)
        dialog.setWindowTitle("辅助自动对齐")
        dialog.resize(1000, 430)
        layout = QVBoxLayout(dialog)
        hint = QLabel("根据下方定格画面判断副路比主画面快或慢多少秒；主画面继续播放。"
                      "请比较同一回合的计时器或共同事件，软件会在估计附近验证连续画面。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        pictures = QHBoxLayout()
        for key, frame in zip((reference, room_id), frames):
            column = QVBoxLayout()
            column.addWidget(QLabel(self.rows[key].label()))
            canvas = Canvas()
            canvas.set_frame(frame)
            column.addWidget(canvas)
            pictures.addLayout(column)
        layout.addLayout(pictures, 1)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("副路比主画面"))
        direction = QComboBox()
        direction.addItem("快（副路已发生主画面之后的内容）", 1)
        direction.addItem("慢（副路还在播放主画面之前的内容）", -1)
        controls.addWidget(direction)
        seconds = QDoubleSpinBox()
        seconds.setRange(0, 120)
        seconds.setSuffix(" 秒")
        seconds.setValue(16)
        controls.addWidget(seconds)
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("开始精校正")
        buttons.button(QDialogButtonBox.Ok).setObjectName("PrimaryButton")
        buttons.button(QDialogButtonBox.Cancel).setObjectName("IconButton")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            if (reference != self.alignment.reference or room_id not in self.rows
                    or decoders != (self.rows[reference].decoder, self.rows[room_id].decoder)
                    or origins != tuple(decoder.history.origin for decoder in decoders)):
                self.notice.setText("直播间或匹配状态已变化，请重新打开辅助对齐")
                return
            # Positive content lead means the matching other timestamp is earlier.
            lag = frames[1][0] - frames[0][0] - direction.currentData() * seconds.value()
            self.retry_alignment(room_id, hint=lag)

    def retry_alignment(self, room_id, hint=None):
        if not self.running or room_id not in self.rows or self.rows[room_id].decoder is None:
            self.notice.setText("请先播放直播间，再重新对齐比赛画面")
            return
        self.analysis_serial += 1
        self.matching = False
        reference = self.alignment.reference
        before = self.shifts()
        if not self.alignment.automatic:
            self.alignment.lags = {key: value - before[reference] for key, value in before.items()}
        self.stable_reference_shift = before[reference]
        self.alignment.automatic = True
        self.alignment.manual_locked = False
        self.automatic.blockSignals(True)
        self.automatic.setChecked(True)
        self.automatic.blockSignals(False)
        targets = set(self.rows) - {reference} if room_id == reference else {room_id}
        for key in targets:
            self.alignment.lags[key] = before[key] - before[reference]
            row = self.rows[key]
            self._queue_rematch(row, local=row.user_confirmed and not row.needs_epoch_samples)
            if hint is not None:
                self.rows[key].alignment_hint = (hint, time.monotonic() + 60)
            self.rematch_admit.add(key)
        self.generation += 1
        self.changed()
        self.render()
        self.analyse()

    def _delay_changed(self, *_args):
        key = next((key for key, row in self.rows.items() if row.delay is self.sender()), "")
        if self.alignment.automatic:
            value = self.rows[key].delay.value()
            self._save_delay_offsets(self.shifts())
            self.rows[key].delay.blockSignals(True)
            self.rows[key].delay.setValue(value)
            self.rows[key].delay.blockSignals(False)
            self.automatic.setChecked(False)
        self.offset_target = key
        before = self.alignment.shifts({key: 0 if self.alignment.automatic else row.previous_delay
                                       for key, row in self.rows.items()})
        if self.stable_reference_shift is not None and self.alignment.reference in before:
            main = self.rows[self.alignment.reference]
            previous_delay = 0 if self.alignment.automatic else main.previous_delay
            correction = self.stable_reference_shift - previous_delay - before[self.alignment.reference]
            before = {room_id: position + correction for room_id, position in before.items()}
        for row in self.rows.values():
            row.previous_delay = row.delay.value()
        if not self.alignment.automatic and not self.alignment.manual_locked:
            self.alignment.lags = {self.alignment.reference: 0}
        self.alignment.manual_locked = True
        self.automatic.setChecked(False)
        self.alignment.candidates.clear()
        self.locked_clock = None
        self.sync_waiting = False
        self.offset_repositioning = key != self.alignment.reference
        reference = self.alignment.reference
        shifts = self.shifts()
        ranges = [(bounds[0] - shifts[key], bounds[1] - shifts[key])
                  for key, row in self.rows.items() if row.decoder is not None and not row.paused
                  if (bounds := row.decoder.history.bounds())]
        if key != reference and (not ranges or max(start for start, _ in ranges) > min(end for _, end in ranges) - .25):
            self.audio.correction += before.get(reference, 0) - shifts.get(reference, 0)
        for row in self.rows.values():
            if row.user_confirmed and (row.room_id == key or key == reference):
                row.review_alignment = True
            row.match_text = "手动时间已锁定；勾选自动对齐可解除"
            row.refresh_status()
        self.show_comparison(key)
        self.generation += 1
        self.changed()
        self.render()

    def show_comparison(self, room_id):
        self.compare.setChecked(True)
        self.comparison_panel.render(self.audio.clock(), self.shifts())
        index = self.comparison_panel.target.findData(room_id)
        if index >= 0:
            self.comparison_panel.target.setCurrentIndex(index)

    def _restore_host_widgets(self):
        self.host_audio_timer.stop()
        self._release_host_audio()
        sidebar = getattr(self.context.window, "sidebar", None)
        if sidebar is not None and self.sidebar_style is not None:
            sidebar.setStyleSheet(self.sidebar_style)
            self.sidebar_style = None
            for item in getattr(sidebar, "_items", []):
                item.setProperty("matchSync", False)
                item.style().unpolish(item)
                item.style().polish(item)
                item.update()
            self._sync_strip_marks(sidebar, False)
        previous, self.hidden_host_widgets = self.hidden_host_widgets, {}
        for widget, visible in previous.items():
            widget.removeEventFilter(self)
            widget.setVisible(visible)
        resume = getattr(self.context.window, "set_match_sync_playback", None)
        if self.embedded and callable(resume):
            resume(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(ROOM_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(ROOM_MIME):
            return
        room_id = bytes(event.mimeData().data(ROOM_MIME)).decode("utf-8", "ignore")
        if self._add_dragged(room_id):
            event.acceptProposedAction()

    def _add_dragged(self, room_id):
        room = next((item for item in getattr(self.context.window, "rooms", [])
                     if str(item.get("room_id") or "") == room_id), {})
        if self.add_room(room_id, {"alias": room.get("uname") or ""}):
            if self.embedded and not self.running:
                self.toggle_running()
            return True
        return False

    def changed(self, *_args):
        self.save_timer.start()

    def save(self):
        self.context.set_setting("rooms", [row.preferences() for row in self.rows.values()])
        self.context.set_setting("main_room", self.main.currentData() or "")
        self.context.set_setting("automatic", self.automatic.isChecked())

    def _add_input(self):
        if self.add_room(self.input.text()):
            self.input.clear()

    def add_room(self, text, preferences=None):
        try:
            room_id = parse_room(text, self.context.manager)
        except ValueError as error:
            self.notice.setText(str(error))
            return False
        if room_id in self.rows:
            self.notice.setText("这位主播已经加入")
            return False
        options = dict(self.saved_rooms.get(room_id, {}))
        options.update(preferences or {})
        row = RoomRow(self, room_id, options, COLORS[len(self.rows) % len(COLORS)])
        self.rows[room_id] = row
        self.rows_layout.addWidget(row)
        self.update_main_choices()
        if self.running:
            self._start_row(row)
        self.changed()
        return True

    def import_current(self):
        wall = getattr(self.context.window, "wall", None)
        if wall is not None:
            for tile in wall.visible_tiles():
                room = tile.room or {}
                room_id = str(room.get("room_id") or "")
                if room_id and room_id not in self.rows:
                    self.add_room(room_id, {"alias": room.get("uname") or ""})

    def update_main_choices(self):
        selected = self.main.currentData()
        self.main.blockSignals(True)
        self.main.clear()
        for room_id, row in self.rows.items():
            self.main.addItem(row.label(), room_id)
        index = self.main.findData(selected)
        self.main.setCurrentIndex(max(0, index) if self.rows else -1)
        self.main.blockSignals(False)
        self._main_changed()

    def _main_changed(self, *_args):
        selected = self.main.currentData() or ""
        for room_id, row in self.rows.items():
            row.main_button.setChecked(room_id == selected)
            row.realign.setVisible(self.automatic.isChecked() and room_id != selected)
        if selected != self.alignment.reference:
            self.late_buffer = LateBuffer()
            self.late_notice.hide()
            for current in self.rows.values():
                current.alignment_hint = None
                current.large_candidate = None
            saved = self.shifts() if self.alignment.manual_locked else None
            self.stable_reference_shift = self.independent_shifts.pop(selected, None)
            self.prefer_highest = True
            self.alignment.select_reference(selected)
            if saved is not None:
                self._save_delay_offsets(saved)
            self.generation += 1
            self.canvas.frame_key = None
            for key, row in self.rows.items():
                row.match_text = ("手动时间已锁定；勾选自动对齐可解除" if self.alignment.manual_locked else
                                  "主画面基准" if key == selected else "等待重新确认")
                row.refresh_status()
            row = self.rows.get(selected)
            if row is not None:
                options = row.platform.room_quality_options(selected) if row.platform is not None else []
                seed = getattr(row.decoder, "seed", None) or {}
                known_highest = seed.get("quality", 10000) if seed.get("highest_quality") else 10000
                highest = next((int(item["qn"]) for item in options if int(item["qn"]) != AUTO_QUALITY), known_highest)
                reload_needed = row.quality != highest or (not seed.get("highest_quality") and row.actual_quality != highest)
                row.quality = highest
                if reload_needed:
                    self._reload_picture()
                elif row.decoder is not None:
                    row.decoder.seed["highest_quality"] = True
        self.sync_picture()
        self.changed()

    def select_main(self, room_id):
        self.main.setCurrentIndex(self.main.findData(room_id))
        self._main_changed()

    def _show_buffering(self, active):
        if self.canvas.waiting != bool(active):
            self.canvas.waiting = bool(active)
            self.canvas.update()
        if getattr(self.picture, "_buffering", False) != bool(active):
            self.picture.set_buffering(bool(active))

    def sync_picture(self, *_args):
        row = self.rows.get(self.main.currentData())
        interval = max(4, int(1000 / getattr(row.decoder, "fps", 30))) if row is not None else 33
        if self.render_timer.interval() != interval:
            self.render_timer.setInterval(interval)
        tile = self.picture
        if row is None:
            self._stop_recording()
            tile.set_room(None)
            self.canvas.set_frame(None)
            self._show_buffering(False)
            return
        tile.blockSignals(True)
        try:
            if str(tile.room.get("room_id") or "") != row.room_id:
                controls_visible = tile._overlay_visible
                self._stop_recording()
                self.canvas.set_frame(None)
                tile.set_room({"room_id": row.room_id, "uname": row.label(), "live": True,
                               "quality": row.quality})
                tile.set_controls_visible(controls_visible)
            tile.room["title"] = row.title
            tile.title_badge.set_text(row.title or row.label(), "")
            tile.title_badge.setToolTip(row.title or row.label())
            tile.stream_badge.set_state(True, "")
            if row.platform is not None:
                options = row.platform.room_quality_options(row.room_id)
                if options and tile.quality_options != options:
                    tile.set_quality_options(options)
            if tile.quality != row.quality:
                tile.set_quality(row.quality)
            if row.platform is not None and tile.actual_quality != row.actual_quality:
                tile.set_actual_quality(row.actual_quality)
            if tile.volume != row.volume.value():
                tile.set_volume(row.volume.value())
            if tile.audio_channel != row.channel.currentData():
                tile.set_audio_channel(row.channel.currentData())
            if tile.muted != (not row.audible.isChecked()):
                tile.set_muted(not row.audible.isChecked())
            if tile.paused != row.paused:
                tile.set_paused(row.paused)
            if not tile._player_active:
                tile.set_video_active(True)
            tile.cover.hide()
            tile.stream_url = getattr(row.decoder, "source_url", "") if row.decoder else ""
            tile.stream_headers = getattr(row.decoder, "source_headers", {}) if row.decoder else {}
        finally:
            tile.blockSignals(False)
        self._show_buffering(self.running and not row.paused and
                             (self.canvas.image.isNull() or self.canvas.waiting))

    def _picture_setting(self, key, value):
        row = self.rows.get(self.main.currentData())
        if row is None:
            return
        widget = getattr(row, key)
        if key == "channel":
            widget.setCurrentIndex(max(0, widget.findData(value)))
        elif key == "audible":
            widget.setChecked(value)
        else:
            widget.setValue(value)

    def _quality_changed(self, _room, quality):
        row = self.rows.get(self.main.currentData())
        if row is not None:
            self.prefer_highest = False
            row.quality = quality
            self._reload_picture()
            self.changed()

    def _reload_picture(self):
        row = self.rows.get(self.main.currentData())
        if row is None or not self.running:
            return
        self._stop_row(row)
        self.sources.pop(row.room_id, None)
        self._start_row(row)
        if not self.alignment.manual_locked:
            self.alignment.lags = {self.alignment.reference: 0}
        self.alignment.candidates.clear()
        self.generation += 1
        self.canvas.set_frame(None)
        self._show_buffering(True)

    def _pause_picture(self):
        row = self.rows.get(self.main.currentData())
        if row is not None:
            row.paused = not row.paused
            self.sync_picture()

    def _fullscreen_picture(self):
        if self.fullscreen_dialog is not None:
            self.fullscreen_dialog.close()
            return
        if not self.rows:
            return
        dialog = QDialog(self.window())
        dialog.setWindowTitle("比赛二路主画面")
        dialog._fullscreen_tile = self.picture
        dialog._fullscreen_cursor = FullscreenCursor(dialog)
        sizes = self.body_split.sizes()
        QVBoxLayout(dialog).addWidget(self.picture)
        def restore(_result):
            dialog._fullscreen_cursor.stop()
            self.body_split.insertWidget(0, self.picture)
            self.body_split.setSizes(sizes)
            self.fullscreen_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(restore)
        self.fullscreen_dialog = dialog
        dialog.showFullScreen()
        dialog._fullscreen_cursor.start()

    def _stop_recording(self):
        recorder = getattr(self.context.window, "recorder", None)
        if recorder is not None and self.picture in recorder.sessions:
            recorder.stop(self.picture)

    def _record_picture(self):
        recorder = getattr(self.context.window, "recorder", None)
        if recorder is not None:
            session = recorder.sessions.get(self.picture)
            if session and session.recording:
                recorder.stop(self.picture)
            else:
                recorder.start(self.picture, recording=True)

    def _save_delay_offsets(self, shifts):
        reference = self.alignment.reference
        if reference in shifts:
            origin = shifts[reference]
            for key, row in self.rows.items():
                row.delay.blockSignals(True)
                row.delay.setValue(origin - shifts[key])
                row.delay.blockSignals(False)
                row.previous_delay = row.delay.value()
            # Retain the sub-display rounding residual, without applying the offset twice.
            self.alignment.lags = {key: value - origin + self.rows[key].delay.value()
                                   for key, value in shifts.items()}
            self.stable_reference_shift = origin
        self.alignment.manual_locked = True
        self.independent_shifts.clear()
        self.rematch_rooms.clear()
        self.rematch_admit.clear()

    def _automatic_changed(self, *_args):
        self.analysis_serial += 1
        self.matching = False
        preserved_main = (self.shifts().get(self.alignment.reference)
                          if self.running and not self.alignment.automatic else None)
        main = self.rows.get(self.alignment.reference)
        bounds = main.decoder.history.bounds() if main is not None and main.decoder is not None else None
        if bounds is None or preserved_main is None or not bounds[0] <= self.audio.clock() + preserved_main <= bounds[1] - .05:
            preserved_main = None
        if (not self.automatic.isChecked() and self.alignment.automatic and not self.alignment.manual_locked
                and (self.running or self.rendered_shifts)):
            self._save_delay_offsets(self.shifts())
        self.alignment.automatic = self.automatic.isChecked()
        if self.alignment.automatic:
            self.independent_shifts.clear()
            self.rematch_rooms = set(self.rows) - {self.alignment.reference}
            self.rematch_admit = set(self.rematch_rooms) if self.running else set()
            self.alignment.lags = {self.alignment.reference: 0}
            self.stable_reference_shift = preserved_main
            self.rendered_shifts.clear()
            self.relative_rates.clear()
            self.shift_reference = None
            self.shift_updated = None
            for row in self.rows.values():
                row.match_confirmed = False
                row.match_failures = 0
                row.alignment_started = time.monotonic()
                row.next_analysis = 0.0
            for row in self.rows.values():
                row.delay.blockSignals(True)
                row.delay.setValue(0)
                row.delay.blockSignals(False)
                row.previous_delay = 0
            if self.alignment.manual_locked:
                for key, row in self.rows.items():
                    row.match_text = "主画面基准" if key == self.alignment.reference else "等待重新确认"
                    row.refresh_status()
            self.alignment.manual_locked = False
            self.sync_waiting = False
            self.locked_clock = None
            self.offset_repositioning = False
            self.alignment.candidates.clear()
            self.generation += 1
        for row in self.rows.values():
            row.realign.setVisible(self.alignment.automatic and row.room_id != self.alignment.reference)
            row.refresh_status()
        self.changed()

    def remove_room(self, room_id):
        row = self.rows.pop(room_id)
        self.rematch_rooms.discard(room_id)
        self.rematch_admit.discard(room_id)
        self.independent_shifts.pop(room_id, None)
        self.admitted_rooms.discard(room_id)
        self.rendered_shifts.pop(room_id, None)
        self.relative_rates.pop(room_id, None)
        self.safety_buffer.arrivals.pop(room_id, None)
        self.overlay_pending.pop(room_id, None)
        self._stop_row(row)
        self.sources.pop(room_id, None)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self.alignment.lags.pop(room_id, None)
        self.alignment.candidates.pop(room_id, None)
        self.update_main_choices()
        self.generation += 1
        self._sync_sidebar_marks()
        if not self.rows:
            self.stop()
            self.panel.set_placeholder("将左侧关注栏卡片拖到这里，加入比赛二路")
            self.notice.setText("请从左侧关注栏拖入直播间")
        self.changed()

    def target_shifts(self):
        shifts = self.alignment.shifts({key: 0 if self.alignment.automatic else row.delay.value()
                                       for key, row in self.rows.items() if key not in self.independent_shifts})
        reference = self.alignment.reference
        if self.stable_reference_shift is not None and reference in shifts:
            delay = 0 if self.alignment.automatic else self.rows[reference].delay.value()
            correction = self.stable_reference_shift - delay - shifts[reference]
            shifts = {key: value + correction for key, value in shifts.items()}
        shifts.update(self.independent_shifts)
        return shifts

    def _block_alignment(self, room_id, reason):
        self.rematch_rooms.add(room_id)
        self.rematch_admit.add(room_id)
        main = self.rows.get(self.alignment.reference)
        main_bounds = main.decoder.history.bounds() if main is not None and main.decoder is not None else None
        main_shift = self.shifts().get(self.alignment.reference)
        if main_bounds is not None and main_shift is not None and main_bounds[0] <= self.audio.clock() + main_shift <= main_bounds[1] - .05:
            self.stable_reference_shift = main_shift
        row = self.rows[room_id]
        bounds = row.decoder.history.bounds() if row.decoder is not None else None
        self.independent_shifts[room_id] = (bounds[1] - self.safety_buffer.target - self.audio.clock()
                                           if bounds is not None else -self.safety_buffer.target)
        self.alignment.candidates.pop(room_id, None)
        self.admitted_rooms.discard(room_id)
        self.rendered_shifts.clear()
        row.match_confirmed = False
        row.awaiting_confirmation = False
        row.mix_gain = 0.0
        row.rematch_locally = False
        row.next_analysis = time.monotonic() + 2
        row.match_failures = 0
        row.alignment_started = time.monotonic()
        row.match_text = reason + "；后台继续重新搜索"
        row.refresh_status()

    def shifts(self):
        if (self.alignment.automatic and self.shift_reference == self.alignment.reference
                and set(self.rendered_shifts) == set(self.rows)):
            return dict(self.rendered_shifts)
        self.relative_rates.clear()
        return self.target_shifts()

    def _smooth_shifts(self, wanted):
        now = time.monotonic()
        dt = max(0, min(.1, now - self.shift_updated)) if self.shift_updated is not None else 0
        self.shift_updated = now
        previous = self.rendered_shifts if self.shift_reference == self.alignment.reference else {}
        self.shift_reference = self.alignment.reference
        self.relative_rates = {}
        result = dict(wanted)
        for row in self.rows.values():
            row.correction_remaining = 0.0
        if self.alignment.automatic:
            for key in wanted:
                if key == self.alignment.reference or key not in previous or key in self.independent_shifts:
                    continue
                delta = wanted[key] - previous[key]
                row = self.rows[key]
                tracking = (row.user_confirmed and row.match_confirmed and row.sync_state == "已同步" and not row.needs_epoch_samples
                            and now - row.alignment_started >= 10
                            and key not in self.rematch_rooms and row.decoder is not None)
                buffered = False
                if tracking and .2 < abs(delta) <= .8:
                    clock = self.audio.clock()
                    bounds = row.decoder.history.bounds_at(clock + previous[key])
                    buffered = (bounds is not None and bounds[0] <= clock + min(previous[key], wanted[key])
                                and clock + max(previous[key], wanted[key]) <= bounds[1] - .05)
                if abs(delta) <= .2 or buffered:
                    rate = .04 if abs(delta) > .2 else .02
                    step = 0 if abs(delta) <= .1 else max(-rate * dt, min(rate * dt, delta))
                    result[key] = previous[key] + step
                    self.relative_rates[key] = 1 + step / dt if dt else 1
                    row.correction_remaining = abs(wanted[key] - result[key])
        self.rendered_shifts = result
        return result

    def toggle_running(self):
        if self.running:
            self.stop()
            return
        if not self.rows:
            self.notice.setText("请先添加直播间")
            return
        self.running = True
        self.independent_shifts.clear()
        self.rematch_rooms = set(self.rows) - {self.alignment.reference} if self.alignment.automatic else set()
        self.rematch_admit.clear()
        self.safety_buffer = SafetyBuffer()
        self.late_buffer = LateBuffer()
        self.late_notice.hide()
        if not self.alignment.manual_locked:
            self.stable_reference_shift = None
        self.last_health_update = None
        self.playback_rate = 1.0
        self.admitted_rooms.clear()
        self.rendered_shifts.clear()
        self.shift_reference = None
        self.shift_updated = None
        self.relative_rates.clear()
        self.generation += 1
        if not self.alignment.manual_locked:
            self.alignment.lags = {self.alignment.reference: 0}
        self.locked_clock = None
        self.sync_waiting = False
        self.alignment.candidates.clear()
        self.panel.set_status("多房间弹幕")
        for row in self.rows.values():
            row.user_confirmed = False
            self._start_row(row)
        self.sync_picture()
        self._sync_sidebar_marks()
        self.audio.start()
        self.render_timer.start()
        self.match_timer.start()

    def _start_row(self, row):
        row.alignment_hint = None
        row.large_candidate = None
        row.paused = False
        row.sync_state = "准备缓存"
        row.mix_gain = 0.0
        row.recovery_since = None
        row.was_isolated = False
        row.actual_position = None
        row.picture_wait_since = None
        row.match_confirmed = False
        row.awaiting_confirmation = False
        row.review_alignment = False
        row.reset_pending = False
        row.needs_epoch_samples = row.user_confirmed
        row.match_failures = 0
        row.alignment_started = time.monotonic()
        row.recheck_alignment = False
        if self.alignment.manual_locked:
            row.match_text = "手动时间已锁定；勾选自动对齐可解除"
        row.pending.clear()
        row.actual_quality = 0
        seed = dict(self.sources.get(row.room_id) or {})
        seed["title"] = seed.get("title") or row.title
        if seed.get("quality", row.quality) != row.quality:
            seed.pop("url", None)
        seed["quality"] = row.quality
        seed["highest_quality"] = self.prefer_highest and row.room_id == self.alignment.reference
        row.decoder = Decoder(row.room_id, seed, row.platform)
        row.decoder.set_crop(row.crop)
        decoder = row.decoder
        decoder.events.information.connect(lambda info, r=row, d=decoder: self._information(r, d, info))
        decoder.events.state.connect(lambda text, r=row, d=decoder: self._state(r, d, text, False))
        decoder.events.reset.connect(lambda r=row, d=decoder: self._reset(r, d))
        decoder.start()
        self._start_chat(row)
        self._sync_sidebar_marks()

    def _start_chat(self, row):
        self.overlay_pending.pop(row.room_id, None)
        previous, row.chat = row.chat, None
        if previous is not None:
            previous.stop()
        row.pending.clear()
        if not row.show_chat.isChecked():
            row.chat_text = "弹幕已关闭"
            row.refresh_status()
            return
        row.chat_text = "弹幕连接中…"
        row.refresh_status()
        chat = (PlatformChat(row.room_id, row.platform, self.context.window)
                if row.platform is not None else Chat(row.room_id))
        row.chat = chat
        chat.events.state.connect(lambda text, r=row, c=chat: self._state(r, c, text, True))
        chat.events.message.connect(lambda event, r=row, c=chat: self._message(r, c, event))
        chat.start()

    def _valid(self, row, worker, chat=False):
        return (self.running and self.rows.get(row.room_id) is row and
                (row.chat if chat else row.decoder) is worker)

    def _information(self, row, worker, info):
        if not self._valid(row, worker):
            return
        if info.get("requested_quality"):
            row.quality = int(info["requested_quality"])
        if "title" in info:
            row.title = info.get("title") or ""
        if not row.alias.text().strip() and info.get("uname"):
            row.alias.setText(info.get("uname") or "未命名主播")
            self.update_main_choices()
        if info.get("actual_quality"):
            row.actual_quality = int(info["actual_quality"])
            if (row.platform is not None and row.platform.kind != "douyu"
                    and not (self.prefer_highest and row.room_id == self.alignment.reference)):
                row.quality = row.actual_quality
            if row.room_id == self.main.currentData():
                self.sync_picture()
                self.picture.set_quality_options(info.get("quality_options") or [])
                self.picture.set_actual_quality(row.actual_quality)
            self.changed()
        if row.room_id == self.main.currentData():
            self.sync_picture()
            options = info.get("quality_options")
            if options and self.picture.quality_options != options:
                self.picture.set_quality_options(options)

    def _state(self, row, worker, text, chat):
        if self._valid(row, worker, chat):
            if chat:
                row.chat_text = text
            else:
                row.video_text = text
            row.refresh_status()

    def _reset(self, row, worker):
        if self._valid(row, worker):
            row.alignment_hint = None
            row.large_candidate = None
            previous = getattr(row.decoder.history, 'previous', None)
            position = self.audio.clock() + self.shifts().get(row.room_id, 0)
            if previous is not None and previous.frame_at(position) is not None:
                row.reset_pending = True
                return
            row.reset_pending = False
            row.needs_epoch_samples = row.user_confirmed
            row.was_isolated = True
            row.match_confirmed = False
            row.mix_gain = 0
            row.recovery_since = None
            row.picture_wait_since = None
            self.alignment.candidates.pop(row.room_id, None)
            row.match_failures = 0
            row.alignment_started = time.monotonic()
            if self.alignment.automatic and row.room_id != self.alignment.reference:
                self._queue_rematch(row)
            if row.room_id == self.alignment.reference:
                for peer in self.rows.values():
                    peer.needs_epoch_samples = peer.user_confirmed
                    peer.match_confirmed = False
                    peer.match_failures = 0
                    peer.alignment_started = time.monotonic()
                    if peer.room_id != row.room_id and self.alignment.automatic:
                        self._queue_rematch(peer)
                self.alignment.candidates.clear()
            self.generation += 1

    def _message(self, row, worker, event):
        if self._valid(row, worker, True) and row.show_chat.isChecked():
            blocker = getattr(self.context.window, "_danmaku_blocked", None)
            if event.get("kind", "danmaku") == "danmaku" and blocker and blocker(event.get("text", "")):
                return
            now = time.monotonic()
            received = now + self.audio.correction
            decoder = row.decoder
            if decoder is not None:
                latest = decoder.history.latest()
                arrival = getattr(decoder, "last_frame_received", 0)
                if latest is not None and arrival and 0 <= now - arrival <= 3:
                    # Messages arrive in wall time; playback follows decoded frame time.
                    received = latest[0] + now - arrival
            row.pending.append((received, dict(event)))

    def _recover_clock(self, clock, shifts):
        now = time.monotonic()
        main = self.rows.get(self.alignment.reference)
        if main is None or main.decoder is None or main.paused:
            self.late_buffer = LateBuffer()
            self.late_notice.hide()
            self.playback_rate = 1.0
            self.sync_waiting = False
            return clock
        secondary_edit = self.offset_target in self.rows and self.offset_target != main.room_id
        main_bounds = main.decoder.history.bounds_at(clock + shifts[main.room_id])
        if main_bounds is None or not main_bounds[0] <= clock + shifts[main.room_id] <= main_bounds[1]:
            self.late_buffer = LateBuffer()
            self.late_notice.hide()
        if (self.offset_repositioning and secondary_edit and main_bounds
                and main_bounds[0] <= clock + shifts[main.room_id] <= main_bounds[1] - .05):
            self.offset_repositioning = False
        if self.offset_repositioning:
            reposition_rows = {self.alignment.reference}
            if not secondary_edit:
                reposition_rows |= {self.offset_target} | {
                    key for key in self.admitted_rooms
                    if key in self.rows and self.rows[key].sync_state == "已同步"}
            ranges = [(bounds[0] - shifts[key], bounds[1] - shifts[key])
                      for key, row in self.rows.items() if key in reposition_rows and row.decoder is not None and not row.paused
                      if (bounds := row.decoder.history.bounds())]
            if len(ranges) == sum(row.decoder is not None and not row.paused for key, row in self.rows.items() if key in reposition_rows):
                lower = max((start for start, _end in ranges), default=clock)
                upper = min((end for _start, end in ranges), default=clock)
                if lower <= upper - .25:
                    recovered = min(max(clock, lower + .1), upper - .25)
                    self.audio.correction += recovered - clock
                    clock = recovered
                    self.offset_repositioning = False
        bounds = main.decoder.history.bounds_at(clock + shifts[main.room_id])
        reserve = self.safety_buffer.target + (max(0, main.delay.value()) if not self.alignment.automatic else 0)
        if bounds is None:
            self.sync_waiting = main.was_isolated
            recovered = self.locked_clock if self.sync_waiting and self.locked_clock is not None else clock
            self.audio.correction += recovered - clock
            return recovered
        arrival = getattr(main.decoder, "last_frame_received", 0)
        fresh = not arrival or now - arrival <= 3
        if clock + shifts[main.room_id] < bounds[0]:
            starting = self.alignment.automatic and self.stable_reference_shift is None
            if (main.was_isolated or starting) and fresh and bounds[1] - bounds[0] >= reserve:
                recovered = bounds[1] - shifts[main.room_id] - reserve
                self.audio.correction += recovered - clock
                self.sync_waiting = False
                return recovered
            self.sync_waiting = main.was_isolated
            recovered = self.locked_clock if self.sync_waiting and self.locked_clock is not None else clock
            self.audio.correction += recovered - clock
            return recovered
        upper = bounds[1] - shifts[main.room_id]
        if clock > upper + 1 and fresh:
            recovered = max(bounds[0] - shifts[main.room_id] + .1, upper - reserve)
            self.audio.correction += recovered - clock
            self.sync_waiting = False
            return recovered
        waiting = clock > upper - (.3 if self.sync_waiting else .05)
        recovered = min(clock, self.locked_clock if self.sync_waiting and self.locked_clock is not None else upper - .05) if waiting else clock
        self.sync_waiting = waiting
        self.locked_clock = recovered
        self.audio.correction += recovered - clock
        ahead = bounds[1] - recovered - shifts[main.room_id]
        self._update_late_buffer(now, recovered, shifts, ahead, bounds[1] - bounds[0] - .5)
        self.playback_rate = self.safety_buffer.rate(now, ahead, minimum=self.late_buffer.floor)
        if self.late_buffer.building:
            self.playback_rate = min(self.playback_rate, .98)
        return recovered

    def _update_late_buffer(self, now, clock, shifts, ahead, capacity):
        if not self.alignment.automatic:
            self.late_buffer = LateBuffer()
            self.late_notice.hide()
            return
        deficits = {}
        main = self.rows[self.alignment.reference]
        if not self.sync_waiting and ahead >= .05 and main.sync_state == "已同步":
            for key, row in self.rows.items():
                trusted = row.match_confirmed or (row.user_confirmed and row.rematch_locally and not row.needs_epoch_samples)
                if (key == main.room_id or row.paused or row.decoder is None or not trusted
                        or row.reset_pending or key in self.independent_shifts
                        or key not in self.alignment.lags):
                    continue
                arrival = getattr(row.decoder, 'last_frame_received', 0)
                bounds = row.decoder.history.bounds()
                if bounds is not None and (not arrival or 0 <= now - arrival <= 3):
                    target = clock + shifts[main.room_id] + self.alignment.lags[key]
                    deficits[key] = target - bounds[1]
        self.late_buffer.update(now, ahead, capacity, deficits)
        blocked = [self.rows[key].label() for key in self.rows if key in self.late_buffer.blocked]
        if blocked:
            text = f"{'、'.join(blocked)}过慢，请更换主画面"
            detail = "该路持续晚到，超出平滑建立缓冲的能力；可将较晚的一路设为主画面，或移除该路。"
        elif self.late_buffer.building:
            names = [self.rows[key].label() for key in self.rows if key in self.late_buffer.rooms]
            text = f"{'、'.join(names)}持续晚到，正在平滑增加主路缓冲"
            detail = "主画面持续播放，以最多约 2% 的轻微降速积累共同缓冲，最长尝试 2 分钟。"
        else:
            text, detail = "", ""
        self.late_notice.setVisible(bool(text))
        if self.late_notice.text() != text:
            self.late_notice.setText(text)
            self.late_notice.setToolTip(detail)

    def _update_sync_health(self, clock, shifts):
        now = time.monotonic()
        dt = max(0, min(.25, now - self.last_health_update)) if self.last_health_update is not None else 0
        self.last_health_update = now
        for key, row in self.rows.items():
            decoder = row.decoder
            bounds = decoder.history.bounds_at(clock + shifts[key]) if decoder is not None else None
            arrival = getattr(decoder, "last_frame_received", 0)
            fresh = not arrival or now - arrival <= 3
            target = clock + shifts[key]
            available = bounds is not None and bounds[0] <= target <= bounds[1] - .05
            if self.alignment.automatic and key != self.alignment.reference and key not in self.independent_shifts:
                if not available and row.match_confirmed and not row.paused and (row.sync_state == "已同步" or row.was_isolated):
                    row.recheck_alignment = True
                elif fresh and available and row.recheck_alignment:
                    self._queue_rematch(row, local=True)
                    self.generation += 1
            visible = key == self.alignment.reference or (self.compare.isChecked() and key in self.comparison_panel.shown_rooms)
            if available and visible and key != self.alignment.reference and hasattr(decoder, "picture_at"):
                displayed = row.actual_position is not None and abs(row.actual_position - target) <= .2
                if displayed:
                    row.picture_wait_since = None
                else:
                    if row.picture_wait_since is None:
                        row.picture_wait_since = now
                    # RGB preparation can briefly lag valid compressed/PCM history.
                    # Do not turn a short cache miss into repeated half-second mutes.
                    available = row.sync_state == "已同步" and now - row.picture_wait_since <= .3
            else:
                row.picture_wait_since = None
            known = (key == self.alignment.reference or not self.alignment.automatic
                     or key in self.alignment.lags and row.match_confirmed)
            known = known and not (key != self.alignment.reference and row.awaiting_confirmation)
            ready = (decoder is not None and not row.paused and available and known
                     and not (self.sync_waiting and key == self.alignment.reference))
            before = row.sync_state
            if not ready:
                row.was_isolated |= before == "已同步"
                row.sync_state = ("等待确认对齐" if row.awaiting_confirmation else "等待对齐" if not known else "暂时隔离" if row.was_isolated else "准备缓存")
                row.mix_gain = 0.0
                row.recovery_since = None
            else:
                if row.recovery_since is None:
                    row.recovery_since = now
                recovered = not row.was_isolated or (now - row.recovery_since >= .5 and bounds[1] - target >= .3)
                row.sync_state = "已同步" if recovered else "恢复缓存"
                if recovered:
                    if key not in self.independent_shifts:
                        self.admitted_rooms.add(key)
                    row.mix_gain = min(1.0, row.mix_gain + dt / .2)
            if before != row.sync_state:
                row.refresh_status()
            if row.sync_state == "已同步" and key == self.alignment.reference:
                self.safety_buffer.observe(key, arrival, getattr(decoder, "fps", 30))
            else:
                self.safety_buffer.arrivals.pop(key, None)
            confirming = key != self.alignment.reference and row.awaiting_confirmation and row.match_confirmed
            reviewing = key != self.alignment.reference and row.review_alignment and row.match_confirmed
            row.join.setVisible(confirming or reviewing)
            if confirming:
                row.join.setText("确认微调并持续同步" if not self.alignment.automatic else
                                 "确认当前偏移" if not available else "确认对齐并加入")
                row.join.setToolTip("仅记录偏移，不改变主画面或副路播放进度；缺少同步内容时本路继续静音等待，缓存覆盖后自动加入。")
            elif reviewing:
                row.join.setText("确认当前偏移（可选）" if self.alignment.automatic else "确认微调并持续同步")
                row.join.setToolTip("当前继续播放；不点击不会撤销偏移或反复重新对齐。确认用于加强当前偏移的依据，不改变播放进度。")
        main = self.rows.get(self.alignment.reference)
        if (self.alignment.automatic and self.stable_reference_shift is None
                and main is not None and main.sync_state == "已同步"):
            self.stable_reference_shift = shifts[self.alignment.reference]

    def confirm_alignment(self, room_id):
        row = self.rows.get(room_id)
        if row is None:
            return
        if (row.awaiting_confirmation or row.review_alignment) and not self.alignment.automatic:
            before = self.shifts()
            reference = self.alignment.reference
            self.analysis_serial += 1
            self.matching = False
            self.alignment.lags = {key: shift - before[reference] for key, shift in before.items()}
            self.stable_reference_shift = before[reference]
            self.alignment.automatic = True
            self.alignment.manual_locked = False
            self.alignment.candidates.clear()
            self.automatic.blockSignals(True)
            self.automatic.setChecked(True)
            self.automatic.blockSignals(False)
            for item in self.rows.values():
                item.delay.blockSignals(True)
                item.delay.setValue(0)
                item.delay.blockSignals(False)
                item.previous_delay = 0
            self.rendered_shifts.clear()
            self.shift_reference = None
            self.generation += 1
        if (row.review_alignment and row.user_confirmed and row.match_confirmed
                and not row.awaiting_confirmation and row.sync_state == "已同步"):
            # A later human review reinforces the displayed offset, without
            # seeking the clock or restoring the initial admission reserve.
            shifts = self.shifts()
            lag = shifts[room_id] - shifts[self.alignment.reference]
            self.alignment.lags[room_id] = lag
            self.alignment.candidates.pop(room_id, None)
            row.user_confirmed_lag = lag
            row.review_alignment = False
            row.match_failures = 0
            row.next_analysis = time.monotonic() + 2
            self.analysis_serial += 1
            self.matching = False
            self.generation += 1
            row.match_text = "用户已确认当前偏移，继续自动同步"
            self.render()
        else:
            self.admit_pending(room_id)
        self.changed()

    def admit_pending(self, room_id, automatic=False):
        row = self.rows.get(room_id)
        main = self.rows.get(self.alignment.reference)
        if (row is None or main is None or row.decoder is None or main.decoder is None
                or not self.alignment.automatic or room_id not in self.alignment.lags or row.paused):
            return
        clock, shifts = self.audio.clock(), self.shifts()
        target = clock + shifts[room_id]
        bounds = row.decoder.history.bounds_at(target)
        if row.needs_epoch_samples and bounds is not None and target < bounds[0]:
            self._queue_rematch(row)
            self.generation += 1
            row.match_text = "候选偏移对应的内容早于副路缓存，继续重新匹配"
            row.refresh_status()
            return False
        if not automatic:
            row.user_confirmed = True
            row.user_confirmed_lag = self.alignment.lags[room_id]
            row.review_alignment = False
            row.awaiting_confirmation = False
            row.recheck_alignment = False
            self.rematch_rooms.discard(room_id)
            self.rematch_admit.discard(room_id)
            row.rematch_locally = False
            self.analysis_serial += 1
            self.matching = False
        if bounds is None or not bounds[0] <= target <= bounds[1] - .05:
            row.match_text = (cache_gap(row.decoder.history, target) or "正在准备目标画面") + "；本路静音，主画面继续播放"
            row.mix_gain = 0.0
            row.refresh_status()
            self.render()
            return False
        row.needs_epoch_samples = False
        self.generation += 1
        self.render()
        return True

    def _render_overlay(self, clock, shifts):
        if self.video_danmaku is None:
            return
        if not self.video_danmaku.enabled:
            self.overlay_pending.clear()
            return
        keys = list(self.rows)
        start = keys.index(self.overlay_last) + 1 if self.overlay_last in keys else 0
        for key in keys[start:] + keys[:start]:
            pending = self.overlay_pending.get(key)
            if pending is None:
                continue
            received, event = pending
            if not self.rows[key].show_chat.isChecked() or clock + shifts[key] - received > 5:
                self.overlay_pending.pop(key, None)
            elif self.video_danmaku.add_event(event):
                self.overlay_pending.pop(key, None)
                self.overlay_last = key

    def render(self):
        if not self.running:
            return
        if not self.embedded:
            self._suppress_host_audio()
        self._sync_sidebar_marks()
        self.sync_picture()
        clock = self.audio.clock()
        wanted = self.target_shifts()
        shifts = self._smooth_shifts(wanted)
        if self.alignment.automatic:
            origin = shifts.get(self.alignment.reference, 0)
            for key, row in self.rows.items():
                if not row.delay.lineEdit().isModified():
                    row.delay.blockSignals(True)
                    row.delay.setValue(origin - shifts[key])
                    row.delay.blockSignals(False)
                    row.previous_delay = row.delay.value()
        self._configure_picture_budget()
        for key, current in self.rows.items():
            if current.reset_pending and current.decoder is not None:
                previous = getattr(current.decoder.history, 'previous', None)
                retained = previous.bounds() if previous is not None else None
                if retained is None or clock + shifts[key] >= retained[1] - .06 or previous.frame_at(clock + shifts[key]) is None:
                    current.decoder.history.previous = None
                    self._reset(current, current.decoder)
        clock = self._recover_clock(clock, shifts)
        row = self.rows.get(self.alignment.reference)
        if row is not None and row.decoder is not None and not row.paused:
            frame = self.canvas.show_at(row.decoder, clock + shifts[row.room_id])
            row.actual_position = self.canvas.frame_key
            waiting = self.canvas.playback_waiting(row.decoder, clock + shifts[row.room_id], frame, self.sync_waiting)
            self._show_buffering(waiting)
            if self.sync_waiting:
                self.notice.setText("主画面等待缓存恢复；异常二路已静音，已确认偏移保持不变")
            elif waiting:
                bounds = row.decoder.history.bounds_at(clock + shifts[row.room_id])
                target = clock + shifts[row.room_id]
                if bounds and target < bounds[0]:
                    self.notice.setText(f"主画面当前缓存约 {bounds[1] - bounds[0]:.1f} 秒；"
                                        "偏移超出可用范围，请等待缓存或减小延后量")
                elif bounds and target > bounds[1] + 1:
                    self.notice.setText("主画面所需内容尚未收到；请减小提前量，或检查该路连接")
                elif bounds and bounds[0] <= target <= bounds[1]:
                    self.notice.setText("主画面显示帧准备较慢；正在追赶播放进度，声音继续播放")
                else:
                    self.notice.setText("主画面等待缓存或连接；较大延后量需要先积累足够内容")
            else:
                delay = time.monotonic() - clock - shifts[row.room_id]
                mode = ("自动对齐已开启" if self.alignment.automatic else
                        "自动对齐已关闭；手动偏移")
                self.notice.setText(f"主画面：{row.label()} · 本地播放延后约 {delay:.1f} 秒 · {mode}")
        if self.compare.isChecked():
            self.comparison_panel.render(clock, shifts)
        self._update_sync_health(clock, shifts)
        eligible = []
        chat_budget = min(80, max(1, 200 // max(1, len(self.rows))))
        for room_id, row in self.rows.items():
            bounds = row.decoder.history.bounds_at(clock + shifts[room_id]) if row.decoder is not None else None
            text = ""
            if bounds:
                text = f"历史缓存约 {int(bounds[1] - bounds[0])} 秒"
                position = clock + shifts[room_id]
                ahead = max(0, bounds[1] - position) if bounds[0] <= position <= bounds[1] else 0
                text += f"，{'同步目标' if room_id != self.alignment.reference else ''}前方可播放约 {ahead:.1f} 秒"
                if room_id != self.alignment.reference and self.alignment.automatic and not row.match_confirmed:
                    text += "（候选偏移，尚未验证）"
                if position < bounds[0] or position > bounds[1] + 1:
                    text += "，当前播放偏移超出范围"
                    text += "（" + cache_gap(row.decoder.history, position) + "）"
            if row.sync_state != "已同步":
                text += " · 本路暂时静音"
            elif self.alignment.automatic and row.correction_remaining > .1001:
                reference = self.alignment.reference
                text += (f" · 播放偏移：目标 {wanted[reference] - wanted[room_id]:+.2f} 秒，"
                         f"当前 {shifts[reference] - shifts[room_id]:+.2f} 秒")
            if row.buffer_text != text:
                row.buffer_text = text
                row.refresh_status()
            target = clock + shifts[room_id]
            for _ in range(chat_budget):
                if not row.pending or row.pending[0][0] > target:
                    break
                received, event = row.pending.popleft()
                if clock - received > 120:
                    continue
                event["medal"] = {}
                event["uname"] = f"【{row.label()}】 {event.get('uname') or ''}"
                event["source_label"] = row.label()
                event["source_room"] = room_id
                event["color"] = row.color
                eligible.append((received - shifts[room_id], event))
        for _due, event in sorted(eligible, key=lambda item: item[0]):
            self.panel.add_event(event)
            received = _due + shifts[event["source_room"]]
            self.overlay_pending[event["source_room"]] = (received, {**event,
                "text": f"【{event['source_label']}】 {event.get('text') or ''}"})
        self._render_overlay(clock, shifts)

    def _configure_picture_budget(self):
        reference = self.alignment.reference
        shown = self.comparison_panel.rooms_to_show() if self.compare.isChecked() else (reference,)
        comparisons = max(0, len(shown) - 1)
        inactive = max(1, len(self.rows) - len(shown))
        for key, row in self.rows.items():
            visible = key in shown
            if row.decoder is not None and hasattr(row.decoder, "analysis_size"):
                row.decoder.analysis_size = (640, 360) if visible else (320, 180)
            reader = getattr(row.decoder, "pictures", None)
            if reader is not None:
                if key == reference:
                    megabytes = 192 if comparisons else 256
                elif visible:
                    megabytes = max(1, 128 // comparisons)
                else:
                    megabytes = max(1, (64 if comparisons else 128) // inactive)
                reader.configure(megabytes * 1024 * 1024, getattr(row.decoder, "fps", 30), active=visible)

    def analyse(self):
        if not self.running or not self.alignment.automatic or self.matching:
            return
        row = self.rows.get(self.alignment.reference)
        if row is None or row.decoder is None:
            return
        if row.reset_pending:
            return
        reference = row.decoder.history.snapshots()
        others = {key: value.decoder.history.snapshots() for key, value in self.rows.items()
                  if key != row.room_id and not value.paused and value.decoder is not None
                  and not value.reset_pending
                  and time.monotonic() >= value.next_analysis}
        if not others:
            return
        keys = list(others)
        key = keys[self.analysis_cursor % len(keys)]
        self.analysis_cursor += 1
        others = {key: others[key]}
        details = {}
        for key, value in self.rows.items():
            if value.decoder is not None:
                with value.decoder.history.lock:
                    details[key] = (list(getattr(value.decoder.history, "details", ()))
                                    if value.decoder.history.origin is not None else [])
        known = dict(self.alignment.lags)
        hints = {}
        for key, value in self.rows.items():
            if value.alignment_hint is not None:
                lag, expires = value.alignment_hint
                if time.monotonic() < expires:
                    hints[key] = lag
                else:
                    value.alignment_hint = None
        for key in self.rematch_rooms:
            if not self.rows[key].rematch_locally:
                known.pop(key, None)
        confirmed_peers = {key for key, value in self.rows.items()
                           if value.match_confirmed and value.sync_state == "已同步"}
        tracking_rooms = {key for key, value in self.rows.items()
                          if value.match_confirmed and key in known and key not in self.rematch_rooms}
        reacquiring_rooms = {key for key, value in self.rows.items() if value.needs_epoch_samples}
        focused_rooms = {key for key, value in self.rows.items() if tuple(value.crop) != (0, 0, 1, 1)}
        reference_id = row.room_id
        clock, shifts = self.audio.clock(), self.shifts()
        positions = {key: clock + shifts[key] for key in details}
        has_picture = self.canvas.frame_key is not None
        if has_picture:
            positions[reference_id] = self.canvas.frame_key
        preview_rooms = set()
        for key in self.comparison_panel.shown_rooms if self.compare.isChecked() else ():
            canvas = self.comparison_panel.cards[key][2]
            if canvas.preview_only:
                preview_rooms.add(key)
            elif canvas.frame_key is not None:
                positions[key] = canvas.frame_key
        epoch, bridge = self.generation, self.results
        self.analysis_serial += 1
        serial = self.analysis_serial
        self.matching = True

        def calculate():
            results = {}
            for key, samples in others.items():
                focused = reference_id in focused_rooms and key in focused_rooms
                reference_details = details.get(reference_id, [])
                other_details = details.get(key, [])
                if key in tracking_rooms and has_picture:
                    reference_details = [sample for sample in reference_details if sample.time <= positions[reference_id]]
                if reference_details and other_details:
                    candidate = (assisted_match(hints[key], reference_details, other_details, focused=focused)
                                 if key in hints else refine_match(Match(known[key], .9, "跟踪已确认偏移"), reference_details, other_details, focused=focused)
                                 if key in known else Match(None, 0, "首次匹配"))
                    if candidate.lag is None and key not in hints:
                        candidate = match_scenes(reference_details[::4], other_details[::4], focused=focused)
                else:
                    candidate = match_scenes(reference, samples, focused=focused)
                if reference_details and other_details:
                    if candidate.lag is None and not candidate.candidates and key in known and key not in hints:
                        candidate = Match(known[key], .9, "复核已确认偏移")
                    if not candidate.refined:
                        candidate = refine_match(candidate, reference_details, other_details, focused=focused)
                    if candidate.lag is not None and key in known and has_picture and key not in preview_rooms:
                        shown_reference = [s for s in details[reference_id] if s.time <= positions[reference_id]]
                        shown_other = [s for s in details[key] if s.time <= positions[key]]
                        verified = refine_match(Match(known[key], .9, "播放进度复核"), shown_reference, shown_other, focused=focused)
                        if verified.lag is not None:
                            candidate = replace(candidate, playback_error=verified.lag - (positions[key] - positions[reference_id]))
                    peers = [peer for peer in known if peer not in (key, reference_id)
                             and peer in confirmed_peers and details.get(peer)]
                    if candidate.lag is not None and peers:
                        peer = peers[0]
                        peer_details = details[peer]
                        if key in tracking_rooms and has_picture:
                            peer_details = [sample for sample in peer_details if sample.time <= positions[peer]]
                        check = refine_match(Match(candidate.lag - known[peer], .9, "三路一致性检查"), peer_details, other_details,
                                             focused=peer in focused_rooms and key in focused_rooms)
                        if check.lag is None and key not in known:
                            candidate = Match(None, 0, "三路共同动态画面不足，继续复核已确认偏移")
                        elif check.lag is not None and abs(check.lag - (candidate.lag - known[peer])) > .2:
                            candidate = Match(None, 0, "三路时间差不一致，保持已确认偏移")
                if (key in reacquiring_rooms and candidate.refined and reference_details and other_details
                        and min(reference_details[-1].time - reference_details[0].time,
                                other_details[-1].time - other_details[0].time) < 4):
                    candidate = Match(None, 0, "恢复精校正需要连续至少 4 秒比赛画面，继续收集")
                results[key] = candidate
            return results

        def run():
            try:
                results = calculate()
            except Exception as error:
                results = {room: Match(None, 0, f"匹配异常：{type(error).__name__}: {error}") for room in others}
            bridge.completed.emit(serial, epoch, results)
        threading.Thread(target=run, name="match-sync-analysis", daemon=True).start()

    def _analysis_finished(self, serial, epoch, results):
        if serial == self.analysis_serial:
            self.results.matched.emit(epoch, results)

    def _matched(self, epoch, results):
        self.matching = False
        if not self.running or epoch != self.generation or not self.alignment.automatic:
            return
        for room_id, match in results.items():
            row = self.rows.get(room_id)
            if row is None:
                continue
            if match.reason.startswith("匹配异常："):
                row.match_text = match.reason + "；稍后自动重试"
                row.next_analysis = time.monotonic() + 2
                row.refresh_status()
                continue
            if match.lag is not None and match.confidence >= .65 and abs(match.lag) > 15:
                hint = row.alignment_hint
                assisted = hint is not None and time.monotonic() < hint[1] and abs(match.lag - hint[0]) <= 4
                changed = (row.user_confirmed and row.user_confirmed_lag is not None and abs(match.lag - row.user_confirmed_lag) > 3
                           and not row.needs_epoch_samples)
                if changed and not assisted:
                    row.match_text = "候选与已确认偏移相差较大；保留当前进度，请用辅助自动对齐复核"
                    row.next_analysis = time.monotonic() + 2
                    row.refresh_status()
                    continue
                previous, count, observed, evidence = row.large_candidate or (match.lag, 0, -float('inf'), -float('inf'))
                now = time.monotonic()
                if not match.refined or abs(previous - match.lag) > .15:
                    count, observed, evidence = 0, -float('inf'), -float('inf')
                fresh = match.evidence_end is None or match.evidence_end - evidence >= 1
                if match.refined and fresh and (now - observed >= 2 or row.needs_epoch_samples and row.user_confirmed):
                    count, observed = count + 1, now
                    evidence = match.evidence_end if match.evidence_end is not None else evidence
                row.large_candidate = (match.lag, count, observed, evidence)
                if count < (2 if assisted or row.needs_epoch_samples and row.user_confirmed else 3):
                    row.match_text = "大偏差候选正在连续精校验；保持当前播放，后台复核"
                    row.next_analysis = now + 2
                    row.refresh_status()
                    continue
                self.alignment.candidates[room_id] = (match.lag, count - 1)
            else:
                row.large_candidate = None
            main = self.rows.get(self.alignment.reference)
            if match.lag is not None and match.confidence >= .65 and main is not None and main.decoder is not None and row.decoder is not None:
                main_bounds, other_bounds = main.decoder.history.bounds(), row.decoder.history.bounds()
                main_shift = self.shifts()[main.room_id]
                if self.stable_reference_shift is None:
                    main_shift = min(main_shift, -self.alignment.buffer_seconds - max(0, match.lag))
                target = self.audio.clock() + main_shift
                if self.stable_reference_shift is None and main_bounds and other_bounds and not (
                        main_bounds[0] <= target <= main_bounds[1] - .05
                        and other_bounds[0] <= target + match.lag <= other_bounds[1] - .05):
                    row.match_text = "正在积累对齐所需缓存；主画面继续播放"
                    row.refresh_status()
                    continue
            was_confirmed = row.match_confirmed
            previous_lag = self.alignment.lags.get(room_id)
            position = self.audio.clock() + self.shifts().get(room_id, 0)
            bounds = row.decoder.history.bounds_at(position) if row.decoder is not None else None
            buffered = bounds is not None and bounds[0] <= position <= bounds[1] - .05
            established = was_confirmed and previous_lag is not None and room_id not in self.independent_shifts
            inconclusive = match.lag is None or match.confidence < .65 or not match.refined
            if established and buffered and inconclusive and "三路时间差不一致" not in match.reason:
                self.alignment.candidates.pop(room_id, None)
                row.match_failures = 0
                row.next_analysis = time.monotonic() + 2
                row.match_text = match.reason + "；沿用已确认偏移，继续缓存播放"
                row.refresh_status()
                continue
            applied = self.alignment.accept(room_id, match)
            if match.lag is None:
                row.large_candidate = None
                focused = main is not None and tuple(main.crop) != (0, 0, 1, 1) and tuple(row.crop) != (0, 0, 1, 1)
                insufficient = any(reason in match.reason for reason in (
                    "变化不足", "正在收集", "需要连续", "共同动态画面不足", "共同比赛区域不足"))
                if not insufficient and not focused:
                    row.match_failures += 1
                if row.match_failures >= 3 or (not row.match_confirmed and time.monotonic() - row.alignment_started >= (25 if focused else 10)):
                    row.match_confirmed = False
                    self._block_alignment(room_id, "无法确认共同比赛画面；本路已静音，可框选比赛区域帮助匹配")
                    continue
                row.match_text = match.reason
            elif match.confidence < .65:
                row.match_failures += 1
                if row.match_failures >= 3:
                    row.match_confirmed = False
                    self._block_alignment(room_id, "无法确认共同比赛画面；本路已静音，可框选比赛区域帮助匹配")
                    continue
                row.match_text = "匹配置信度不足；保持已确认偏移，继续收集画面"
            else:
                row.match_failures = 0
                if match.refined:
                    if applied:
                        row.alignment_hint = None
                        if room_id in self.independent_shifts:
                            self.independent_shifts.pop(room_id)
                            self.rendered_shifts.clear()
                            self.shift_reference = None
                        # playback_error describes the old displayed position;
                        # it is not evidence against the correction just applied.
                        row.match_confirmed = (was_confirmed and row.user_confirmed) or match.playback_error is None or abs(match.playback_error) <= .2
                        if row.user_confirmed and (not was_confirmed or row.user_confirmed_lag is None
                                                   or abs(self.alignment.lags[room_id] - row.user_confirmed_lag) > .2):
                            row.review_alignment = True
                        if row.match_confirmed:
                            row.awaiting_confirmation = not row.user_confirmed
                            if room_id in self.rematch_admit:
                                self.rendered_shifts.clear()
                                self.shift_reference = None
                            if room_id not in self.rematch_admit or self.admit_pending(room_id, automatic=True):
                                self.rematch_rooms.discard(room_id)
                                self.rematch_admit.discard(room_id)
                                row.rematch_locally = False
                            else:
                                row.rematch_locally = row.match_confirmed
                                continue
                    verified = match.playback_error is not None and abs(match.playback_error) <= .15
                    status = "播放进度已复核" if applied and verified else "已应用精校正，待复核" if applied else "正在确认精校正"
                    actual = self.compare.isChecked() and room_id in self.comparison_panel.shown_rooms
                    error = f"，{'实际画面' if actual else '预计播放'}误差约 {abs(match.playback_error):.2f} 秒" if match.playback_error is not None else ""
                    row.match_text = f"{status}：相对主画面 {match.lag:+.2f} 秒{error}"
                    if row.awaiting_confirmation:
                        row.match_text += "；请打开对照检查并确认对齐"
                else:
                    if applied:
                        row.match_confirmed = False
                    row.match_text = (f"{'已应用粗匹配，待精校正' if applied else '正在确认'}：相对主画面 {match.lag:+.1f} 秒，"
                                      f"置信度 {match.confidence:.0%}")
            row.refresh_status()

    def choose_crop(self, row):
        frozen = None
        if row.room_id == self.alignment.reference:
            frame = self.canvas.frame
        elif self.compare.isChecked() and row.room_id in self.comparison_panel.shown_rooms:
            frame = self.comparison_panel.cards[row.room_id][2].frame
        else:
            frame = (row.decoder.history.frame_at(self.audio.clock() + self.shifts()[row.room_id])
                     if row.decoder is not None else None)
            if frame is not None and hasattr(row.decoder, "picture_at"):
                history = row.decoder.history
                frozen = (history.segment_at(frame[0]) if hasattr(history, 'segment_at') else history, frame)
                frame = row.decoder.picture_at(frame[0], exact=True)
        if frame is None and frozen is None:
            self.notice.setText("请先开始观看，收到画面后再选择共同比赛区域")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{row.label()}：拖选共同比赛区域，尽量避开主播头像和字幕")
        dialog.resize(900, 600)
        canvas = Canvas(selecting=True)
        canvas.set_frame(frame)
        canvas.waiting = frame is None
        canvas.crop = QRectF(*row.crop)
        reset = QPushButton("使用整个画面")
        reset.clicked.connect(lambda: (setattr(canvas, "crop", QRectF(0, 0, 1, 1)), canvas.update()))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("MatchSyncCropConfirm")
        dialog.setStyleSheet(f"""
            QPushButton {{
                background: {theme.CONTENT_HOVER}; color: {theme.TEXT1};
                border: 1px solid {theme.BORDER_STRONG}; border-radius: 6px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{ background: {theme.ELEVATED}; border-color: {theme.ACCENT}; }}
            QPushButton:pressed {{ background: {theme.CONTENT}; }}
            QPushButton:focus {{ border: 2px solid {theme.ACCENT}; }}
            QPushButton#MatchSyncCropConfirm {{ background: #006a92; color: #ffffff; border-color: #006a92; }}
            QPushButton#MatchSyncCropConfirm:hover {{ background: #007ba8; }}
            QPushButton#MatchSyncCropConfirm:pressed {{ background: #005778; }}
            QPushButton:disabled, QPushButton#MatchSyncCropConfirm:disabled {{
                background: {theme.CONTENT_HOVER}; color: {theme.TEXT3}; border-color: {theme.BORDER};
            }}
        """)
        if frame is None:
            buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            prepare = QTimer(dialog)
            prepare.setInterval(16)

            def show_frozen():
                ready = row.decoder.pictures.get(*frozen, exact=True) if row.decoder is not None else None
                if ready is not None:
                    canvas.set_frame(ready)
                    canvas.waiting = False
                    buttons.button(QDialogButtonBox.Ok).setEnabled(True)
                    prepare.stop()

            prepare.timeout.connect(show_frozen)
            prepare.start()
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        hint = QLabel("自动对齐请保留完整画面；如需人工细调，可只框选计时区域。"
                      "两路请选择相同内容，框选不会自动读取计时器数字。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(canvas, 1)
        layout.addWidget(reset)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted and canvas.crop.width() > 0.02 and canvas.crop.height() > 0.02:
            rect = canvas.crop
            row.crop = (rect.x(), rect.y(), rect.width(), rect.height())
            row.decoder.set_crop(row.crop)
            self.retry_alignment(row.room_id)
            self.changed()

    def _suppress_host_audio(self):
        players = getattr(self.context.window, "players", {})
        current = {}
        active = self.host_audio_timer.isActive() if self.embedded else self.audio.sink is not None
        if active:
            for tile, player in list(players.items()):
                if (self.embedded or str((tile.room or {}).get("room_id") or "") in self.rows) and not player._released:
                    player.set_muted(True)
                    current[player] = tile
        for player, tile in self.suppressed.items():
            if player not in current and not player._released:
                self._restore_host_audio(player, tile)
        self.suppressed = current

    def _restore_host_audio(self, player, old_tile):
        players = getattr(self.context.window, "players", {})
        owner = next((tile for tile, value in players.items() if value is player), old_tile)
        player.set_muted(bool(owner.muted))

    def _release_host_audio(self):
        for player, tile in self.suppressed.items():
            if not player._released:
                self._restore_host_audio(player, tile)
        self.suppressed.clear()

    @staticmethod
    def _stop_row(row):
        if row.decoder is not None:
            row.decoder.stop()
        if row.chat is not None:
            row.chat.stop()
        row.decoder = None
        row.chat = None
        row.mix_gain = 0
        row.match_confirmed = False
        row.sync_state = "已停止"
        row.actual_position = None
        row.join.hide()
        row.pending.clear()
        row.video_text = "已停止"
        row.chat_text = "弹幕已停止"
        row.match_text = "等待画面"
        row.buffer_text = ""
        row.refresh_status()

    def stop(self):
        self.analysis_serial += 1
        self.late_buffer = LateBuffer()
        self.late_notice.hide()
        self.matching = False
        if self.fullscreen_dialog is not None:
            self.fullscreen_dialog.close()
        self._stop_recording()
        self.running = False
        self.sync_waiting = False
        self.locked_clock = None
        self.offset_repositioning = False
        self.generation += 1
        self.render_timer.stop()
        self.match_timer.stop()
        self.compare.setChecked(False)
        self.audio.stop()
        for _card, _name, canvas, state in self.comparison_panel.cards.values():
            canvas.set_frame(None)
            canvas.waiting = True
            state.setText("已停止")
        for row in self.rows.values():
            self._stop_row(row)
            seed = self.sources.get(row.room_id) or {}
            if str(seed.get("url") or "").startswith(("http://", "https://")):
                self.sources.pop(row.room_id, None)
        if not self.host_audio_timer.isActive():
            self._release_host_audio()
        self.panel.set_status("已停止")
        self.overlay_pending.clear()
        self.overlay_last = ""
        if self.video_danmaku is not None:
            self.video_danmaku.clear()
        self.canvas.set_frame(None)
        self._show_buffering(False)
        self._sync_sidebar_marks()

    def closeEvent(self, event):
        self.stop()
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.save()
        super().closeEvent(event)
        self._restore_host_widgets()

    def reject(self):
        if self.embedded:
            self.stop()
            self.hide()
            self._restore_host_widgets()
            self.finished.emit(0)
        else:
            super().reject()
