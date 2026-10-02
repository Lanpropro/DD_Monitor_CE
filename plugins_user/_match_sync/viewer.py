"""One selectable match picture, independently mixed audio, and labelled chat."""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSlider, QSplitter, QVBoxLayout, QWidget)

from ddm.widgets import DanmakuPanel, ROOM_MIME
from .engine import Alignment, RATE, match_scenes, mix_pcm
from .media import Chat, Decoder

COLORS = ("#38bdf8", "#fb7185", "#a78bfa", "#4ade80", "#fbbf24", "#fb923c")


def parse_room(text: str) -> str:
    text = text.strip()
    if not text.isdigit():
        link = urlsplit(text)
        if link.scheme not in ("http", "https") or link.hostname != "live.bilibili.com":
            raise ValueError("请输入 B 站直播房间号或 live.bilibili.com 链接")
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
        self.frame_key = None
        self.selecting = selecting
        self.crop = QRectF(0, 0, 1, 1)
        self.anchor = None
        self.image_rect = QRectF()
        self.setMinimumSize(320, 180)

    def set_frame(self, item):
        key = item[0] if item is not None else None
        if key == self.frame_key:
            return
        self.frame_key = key
        self.image = QImage.fromData(item[1]) if item is not None else QImage()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        if self.image.isNull():
            painter.setPen(QColor("#a1a1aa"))
            painter.drawText(self.rect(), Qt.AlignCenter, "将左侧关注栏卡片拖到这里，加入比赛二路")
            return
        size = self.image.size().scaled(self.size(), Qt.KeepAspectRatio)
        self.image_rect = QRectF((self.width() - size.width()) / 2,
                                (self.height() - size.height()) / 2,
                                size.width(), size.height())
        painter.drawImage(self.image_rect, self.image)
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


class AudioPump(QObject):
    status = Signal(str)

    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.sink = None
        self.device = None
        self.anchor = 0.0
        self.written = 0
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.fill)
        self.devices = QMediaDevices(self)
        self.device_id = None
        self.devices.audioOutputsChanged.connect(self._device_changed)

    def start(self):
        self.stop()
        self.anchor = time.monotonic()
        self.written = 0
        output = QMediaDevices.defaultAudioOutput()
        self.device_id = bytes(output.id())
        fmt = QAudioFormat()
        fmt.setSampleRate(RATE)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if output.isNull() or not output.isFormatSupported(fmt):
            self.status.emit("音频输出不可用；请检查系统默认播放设备")
            return
        self.sink = QAudioSink(output, fmt, self)
        self.sink.stateChanged.connect(lambda: self._state_changed())
        self.sink.setBufferSize(RATE * 4 * 60 // 1000)
        self.device = self.sink.start()
        if self.sink is None or self.device is None:
            self.status.emit("无法启动音频输出")
            self.stop()
            return
        self.timer.start()
        self.status.emit("声音已接管，结束观看后恢复原程序的静音设定")

    def stop(self):
        self.timer.stop()
        sink, self.sink = self.sink, None
        if sink is not None:
            sink.stop()
            sink.deleteLater()
        self.device = None

    def _state_changed(self):
        if self.sink is not None and self.sink.error().value:
            self.status.emit("音频设备出错；检查系统默认设备后停止并重新开始")
            self.stop()

    def clock(self):
        return (self.anchor + self.sink.processedUSecs() / 1_000_000
                if self.sink is not None else time.monotonic())

    def fill(self):
        if self.sink is None or self.device is None:
            return
        shifts = self.viewer.shifts()
        for _ in range(3):
            frames = min(2048, self.sink.bytesFree() // 4)
            if frames < 240:
                break
            clock = self.anchor + self.written / RATE
            inputs = []
            for room_id, row in self.viewer.rows.items():
                if row.decoder is not None and row.audible.isChecked():
                    pcm = row.decoder.history.pcm_at(clock + shifts[room_id], frames)
                    inputs.append((pcm, row.volume.value()))
            count = self.device.write(mix_pcm(inputs, frames))
            if count <= 0:
                break
            self.written += count // 4

    def _device_changed(self):
        current = bytes(QMediaDevices.defaultAudioOutput().id())
        if self.viewer.running and current != self.device_id:
            self.start()


class Results(QObject):
    matched = Signal(int, dict)


class RoomRow(QFrame):
    def __init__(self, viewer, room_id, preferences, color):
        super().__init__(viewer)
        self.viewer = viewer
        self.room_id = room_id
        self.decoder = None
        self.chat = None
        self.pending = deque(maxlen=2000)
        self.color = preferences.get("color", color)
        self.crop = tuple(preferences.get("crop", (0, 0, 1, 1)))
        self.match_text = "等待画面"
        self.video_text = "未开始"
        self.chat_text = "弹幕未连接"
        self.buffer_text = ""
        self.alias = QLineEdit(preferences.get("alias", ""))
        self.alias.setPlaceholderText(f"房间 {room_id}")
        self.alias.setMaximumWidth(140)
        self.audible = QCheckBox("声音")
        self.audible.setChecked(preferences.get("audible", True))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(preferences.get("volume", 42))
        self.volume.setFixedWidth(90)
        self.delay = self._offset(preferences.get("delay", 0))
        self.chat_delay = self._offset(preferences.get("chat_delay", 0))
        self.show_chat = QCheckBox("弹幕")
        self.show_chat.setChecked(preferences.get("show_chat", True))
        self.color_button = QPushButton("来源颜色")
        self.color_button.setStyleSheet(f"color: {self.color}")
        self.color_button.clicked.connect(self._color)
        region = QPushButton("匹配区域")
        region.clicked.connect(lambda: viewer.choose_crop(self))
        remove = QPushButton("移除")
        remove.clicked.connect(lambda: viewer.remove_room(room_id))
        first = QHBoxLayout()
        for widget in (QLabel(room_id), self.alias, self.audible, self.volume,
                       QLabel("播放偏移"), self.delay, self.show_chat,
                       QLabel("弹幕微调"), self.chat_delay, self.color_button, region, remove):
            first.addWidget(widget)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(first)
        layout.addWidget(self.status)
        self.refresh_status()
        for spin in (self.delay, self.chat_delay):
            spin.setToolTip("单位秒；正值延后，负值提前。提前受已收到的内容限制。")
            spin.valueChanged.connect(viewer.changed)
        self.volume.valueChanged.connect(viewer.changed)
        self.audible.toggled.connect(viewer.changed)
        self.show_chat.toggled.connect(self._chat_toggle)
        self.alias.textChanged.connect(viewer.changed)
        self.alias.editingFinished.connect(viewer.update_main_choices)

    @staticmethod
    def _offset(value):
        spin = QDoubleSpinBox()
        spin.setRange(-60, 60)
        spin.setDecimals(1)
        spin.setSingleStep(0.1)
        spin.setSuffix(" s")
        spin.setValue(value)
        return spin

    def label(self):
        return self.alias.text().strip() or f"房间 {self.room_id}"

    def _color(self):
        color = QColorDialog.getColor(QColor(self.color), self, "弹幕来源颜色")
        if color.isValid():
            self.color = color.name()
            self.color_button.setStyleSheet(f"color: {self.color}")
            self.viewer.changed()

    def _chat_toggle(self):
        self.pending.clear()
        self.viewer.changed()

    def preferences(self):
        return {"room_id": self.room_id, "alias": self.alias.text(), "color": self.color,
                "audible": self.audible.isChecked(), "volume": self.volume.value(),
                "delay": self.delay.value(), "chat_delay": self.chat_delay.value(),
                "show_chat": self.show_chat.isChecked(), "crop": list(self.crop)}

    def refresh_status(self):
        text = f"{self.video_text} · {self.match_text} · {self.chat_text}"
        self.status.setText(text + (f" · {self.buffer_text}" if self.buffer_text else ""))


class Viewer(QDialog):
    def __init__(self, context, sources, initial_room=None):
        super().__init__(context.window)
        self.context = context
        self.sources = sources
        self.rows = {}
        self.running = False
        self.alignment = Alignment()
        self.generation = 0
        self.matching = False
        self.suppressed = {}
        self.embedded = False
        self.setAcceptDrops(True)
        self.setWindowTitle("比赛二路同步")
        self.setObjectName("MatchSync")
        self.setStyleSheet("""
            #MatchSync QPushButton, #MatchSync QDoubleSpinBox {
                background: #2a2d32; color: #e4e4e7;
                border: 1px solid #444952; border-radius: 5px; padding: 5px;
            }
            #MatchSync QPushButton:hover { border-color: #38bdf8; }
        """)
        self.resize(1320, 880)
        self.main = QComboBox()
        self.main.setMinimumWidth(160)
        self.main.currentIndexChanged.connect(self._main_changed)
        self.automatic = QCheckBox("自动对齐比赛画面")
        self.automatic.setChecked(context.setting("automatic", True))
        self.automatic.toggled.connect(self._automatic_changed)
        self.input = QLineEdit()
        self.input.setPlaceholderText("B 站房间号或直播链接")
        self.input.returnPressed.connect(self._add_input)
        add = QPushButton("添加直播间")
        add.clicked.connect(self._add_input)
        use_current = QPushButton("加入当前观看的房间")
        use_current.clicked.connect(self.import_current)
        self.add_controls = (self.input, add, use_current)
        self.start_button = QPushButton("开始观看")
        self.start_button.clicked.connect(self.toggle_running)
        top = QHBoxLayout()
        for widget in (QLabel("主画面"), self.main, self.automatic,
                       self.input, add, use_current, self.start_button):
            top.addWidget(widget)
        self.canvas = Canvas()
        self.panel = DanmakuPanel(self)
        self.panel.setMinimumWidth(260)
        self.panel.set_placeholder("各房间弹幕将标注主播及房间号，按播放延迟一起显示")
        settings = getattr(context.window, "settings", {})
        self.panel.apply_style(settings.get("danmaku_font", ""),
                               int(settings.get("danmaku_font_size") or 13))
        self.panel.set_max_blocks(int(settings.get("danmaku_max_blocks") or 3000))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.canvas)
        split.addWidget(self.panel)
        split.setSizes([930, 330])
        self.notice = QLabel("选择共同比赛区域可提高匹配成功率；自动估计约 0.5 秒分辨率，手动微调 0.1 秒。")
        self.notice.setWordWrap(True)
        body = QWidget()
        self.rows_layout = QVBoxLayout(body)
        self.rows_layout.setAlignment(Qt.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setMinimumHeight(160)
        scroll.setMaximumHeight(280)
        self.audio_status = QLabel()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        layout.addWidget(self.notice)
        layout.addWidget(scroll)
        layout.addWidget(self.audio_status)
        self.audio = AudioPump(self)
        self.audio.status.connect(self.audio_status.setText)
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(33)
        self.render_timer.timeout.connect(self.render)
        self.match_timer = QTimer(self)
        self.match_timer.setInterval(3000)
        self.match_timer.timeout.connect(self.analyse)
        self.results = Results()
        self.results.matched.connect(self._matched)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self.save)
        for preferences in context.setting("rooms", []):
            self.add_room(preferences["room_id"], preferences)
        if initial_room:
            self.add_room(str(initial_room.get("room_id") or ""),
                          {"alias": initial_room.get("uname") or ""})
        index = self.main.findData(context.setting("main_room", ""))
        if index >= 0:
            self.main.setCurrentIndex(index)
        self._automatic_changed()

    def embed(self, content):
        self.embedded = True
        self.setParent(content, Qt.Widget)
        self.setGeometry(content.rect())
        content.installEventFilter(self)
        for widget in self.add_controls:
            widget.hide()
        self.notice.setText("从左侧关注栏拖入直播间；选择主画面，各路声音与弹幕会合并。")

    def eventFilter(self, watched, event):
        if self.embedded and watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        return super().eventFilter(watched, event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(ROOM_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(ROOM_MIME):
            return
        room_id = bytes(event.mimeData().data(ROOM_MIME)).decode("utf-8", "ignore")
        room = next((item for item in getattr(self.context.window, "rooms", [])
                     if str(item.get("room_id") or "") == room_id), {})
        if self.add_room(room_id, {"alias": room.get("uname") or ""}):
            if self.embedded and not self.running:
                self.toggle_running()
            event.acceptProposedAction()

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
            room_id = parse_room(text)
        except ValueError as error:
            self.notice.setText(str(error))
            return False
        if room_id in self.rows:
            self.notice.setText(f"房间 {room_id} 已加入")
            return False
        row = RoomRow(self, room_id, preferences or {}, COLORS[len(self.rows) % len(COLORS)])
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
                if room_id.isdigit() and room_id not in self.rows:
                    self.add_room(room_id, {"alias": room.get("uname") or ""})

    def update_main_choices(self):
        selected = self.main.currentData()
        self.main.blockSignals(True)
        self.main.clear()
        for room_id, row in self.rows.items():
            self.main.addItem(f"{row.label()} ({room_id})", room_id)
        index = self.main.findData(selected)
        self.main.setCurrentIndex(max(0, index) if self.rows else -1)
        self.main.blockSignals(False)
        self._main_changed()

    def _main_changed(self, *_args):
        selected = self.main.currentData() or ""
        if selected != self.alignment.reference:
            self.alignment.select_reference(selected)
            self.generation += 1
            self.canvas.frame_key = None
            for key, row in self.rows.items():
                row.match_text = "主画面基准" if key == selected else "等待重新确认"
                row.refresh_status()
        self.changed()

    def _automatic_changed(self, *_args):
        self.alignment.automatic = self.automatic.isChecked()
        self.changed()

    def remove_room(self, room_id):
        row = self.rows.pop(room_id)
        self._stop_row(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self.alignment.lags.pop(room_id, None)
        self.alignment.candidates.pop(room_id, None)
        self.update_main_choices()
        self.generation += 1
        self.changed()

    def shifts(self):
        return self.alignment.shifts({key: row.delay.value() for key, row in self.rows.items()})

    def toggle_running(self):
        if self.running:
            self.stop()
            return
        if not self.rows:
            self.notice.setText("请先添加直播间")
            return
        self.running = True
        self.generation += 1
        self.alignment.lags = {self.alignment.reference: 0}
        self.alignment.candidates.clear()
        self.start_button.setText("停止观看")
        self.panel.set_status("多房间弹幕")
        for row in self.rows.values():
            self._start_row(row)
        self.audio.start()
        self.render_timer.start()
        self.match_timer.start()

    def _start_row(self, row):
        row.pending.clear()
        row.decoder = Decoder(row.room_id, self.sources.get(row.room_id))
        row.decoder.set_crop(row.crop)
        row.chat = Chat(row.room_id)
        decoder, chat = row.decoder, row.chat
        decoder.events.information.connect(lambda info, r=row, d=decoder: self._information(r, d, info))
        decoder.events.state.connect(lambda text, r=row, d=decoder: self._state(r, d, text, False))
        decoder.events.reset.connect(lambda r=row, d=decoder: self._reset(r, d))
        chat.events.state.connect(lambda text, r=row, c=chat: self._state(r, c, text, True))
        chat.events.message.connect(lambda event, r=row, c=chat: self._message(r, c, event))
        decoder.start()
        chat.start()

    def _valid(self, row, worker, chat=False):
        return (self.running and self.rows.get(row.room_id) is row and
                (row.chat if chat else row.decoder) is worker)

    def _information(self, row, worker, info):
        if self._valid(row, worker) and not row.alias.text().strip():
            row.alias.setText(info.get("uname") or f"房间 {row.room_id}")
            self.update_main_choices()

    def _state(self, row, worker, text, chat):
        if self._valid(row, worker, chat):
            if chat:
                row.chat_text = text
            else:
                row.video_text = text
            row.refresh_status()

    def _reset(self, row, worker):
        if self._valid(row, worker):
            self.alignment.lags = {self.alignment.reference: 0}
            self.alignment.candidates.clear()
            self.generation += 1
            row.pending.clear()

    def _message(self, row, worker, event):
        if self._valid(row, worker, True) and row.show_chat.isChecked():
            blocker = getattr(self.context.window, "_danmaku_blocked", None)
            if event.get("kind", "danmaku") == "danmaku" and blocker and blocker(event.get("text", "")):
                return
            row.pending.append((time.monotonic(), dict(event)))

    def render(self):
        if not self.running:
            return
        self._suppress_host_audio()
        clock = self.audio.clock()
        shifts = self.shifts()
        row = self.rows.get(self.alignment.reference)
        if row is not None and row.decoder is not None:
            frame = row.decoder.history.frame_at(clock + shifts[row.room_id])
            self.canvas.set_frame(frame)
            if frame is None:
                bounds = row.decoder.history.bounds()
                target = clock + shifts[row.room_id]
                if bounds and target < bounds[0]:
                    self.notice.setText(f"主画面当前缓存约 {bounds[1] - bounds[0]:.1f} 秒；"
                                        "偏移超出可用范围，请等待缓存或减小延后量")
                elif bounds and target > bounds[1] + 1:
                    self.notice.setText("主画面所需内容尚未收到；请减小提前量，或检查该路连接")
                else:
                    self.notice.setText("主画面等待缓存或连接；较大延后量需要先积累足够内容")
            else:
                delay = time.monotonic() - clock - shifts[row.room_id]
                self.notice.setText(f"主画面：{row.label()} · 延后约 {delay:.1f} 秒 · "
                                    "无法匹配时保持已确认偏移，可手动校正")
        eligible = []
        for room_id, row in self.rows.items():
            bounds = row.decoder.history.bounds() if row.decoder is not None else None
            text = ""
            if bounds:
                text = f"可用缓存约 {int(bounds[1] - bounds[0])} 秒"
                position = clock + shifts[room_id]
                if position < bounds[0] or position > bounds[1] + 1:
                    text += "，当前播放偏移超出范围"
            if row.buffer_text != text:
                row.buffer_text = text
                row.refresh_status()
            target = clock + shifts[room_id] - row.chat_delay.value()
            for _ in range(min(80, 200 - len(eligible))):
                if not row.pending or row.pending[0][0] > target:
                    break
                received, event = row.pending.popleft()
                if clock - received > 120:
                    continue
                event["uname"] = f"[{row.label()}｜{room_id}] {event.get('uname') or ''}"
                event["color"] = row.color
                eligible.append((received - shifts[room_id] + row.chat_delay.value(), event))
        for _due, event in sorted(eligible, key=lambda item: item[0]):
            self.panel.add_event(event)

    def analyse(self):
        if not self.running or not self.alignment.automatic or self.matching:
            return
        row = self.rows.get(self.alignment.reference)
        if row is None or row.decoder is None:
            return
        reference = row.decoder.history.snapshots()
        others = {key: value.decoder.history.snapshots() for key, value in self.rows.items()
                  if key != row.room_id and value.decoder is not None}
        epoch, bridge = self.generation, self.results
        self.matching = True

        def run():
            bridge.matched.emit(epoch, {key: match_scenes(reference, samples)
                                       for key, samples in others.items()})
        threading.Thread(target=run, name="match-sync-analysis", daemon=True).start()

    def _matched(self, epoch, results):
        self.matching = False
        if not self.running or epoch != self.generation or not self.alignment.automatic:
            return
        for room_id, match in results.items():
            row = self.rows.get(room_id)
            if row is None:
                continue
            applied = self.alignment.accept(room_id, match)
            if match.lag is None:
                row.match_text = match.reason
            else:
                row.match_text = (f"{'已对齐' if applied else '正在确认'}：相对主画面 {match.lag:+.1f} 秒，"
                                  f"置信度 {match.confidence:.0%}")
            row.refresh_status()

    def choose_crop(self, row):
        latest = row.decoder.history.latest() if row.decoder is not None else None
        if latest is None:
            self.notice.setText("请先开始观看，收到画面后再选择共同比赛区域")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{row.label()}：拖选共同比赛区域，尽量避开主播头像和字幕")
        dialog.resize(900, 600)
        canvas = Canvas(selecting=True)
        canvas.set_frame(latest)
        canvas.crop = QRectF(*row.crop)
        reset = QPushButton("使用整个画面")
        reset.clicked.connect(lambda: (setattr(canvas, "crop", QRectF(0, 0, 1, 1)), canvas.update()))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(canvas, 1)
        layout.addWidget(reset)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted and canvas.crop.width() > 0.02 and canvas.crop.height() > 0.02:
            rect = canvas.crop
            row.crop = (rect.x(), rect.y(), rect.width(), rect.height())
            row.decoder.set_crop(row.crop)
            self.alignment.lags = {self.alignment.reference: 0}
            self.alignment.candidates.clear()
            self.generation += 1
            self.changed()

    def _suppress_host_audio(self):
        players = getattr(self.context.window, "players", {})
        current = {}
        if self.audio.sink is not None:
            for tile, player in list(players.items()):
                if str((tile.room or {}).get("room_id") or "") in self.rows and not player._released:
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

    @staticmethod
    def _stop_row(row):
        if row.decoder is not None:
            row.decoder.stop()
        if row.chat is not None:
            row.chat.stop()
        row.decoder = None
        row.chat = None
        row.pending.clear()
        row.video_text = "已停止"
        row.chat_text = "弹幕已停止"
        row.match_text = "等待画面"
        row.buffer_text = ""
        row.refresh_status()

    def stop(self):
        self.running = False
        self.generation += 1
        self.render_timer.stop()
        self.match_timer.stop()
        self.audio.stop()
        for row in self.rows.values():
            self._stop_row(row)
        for player, tile in self.suppressed.items():
            if not player._released:
                self._restore_host_audio(player, tile)
        self.suppressed.clear()
        self.start_button.setText("开始观看")
        self.panel.set_status("已停止")
        self.canvas.set_frame(None)

    def closeEvent(self, event):
        self.stop()
        if self.save_timer.isActive():
            self.save_timer.stop()
            self.save()
        super().closeEvent(event)

    def reject(self):
        if self.embedded:
            self.stop()
            self.hide()
            self.finished.emit(0)
        else:
            super().reject()
