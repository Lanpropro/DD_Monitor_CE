"""One selectable match picture, independently mixed audio, and labelled chat."""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import replace
from urllib.parse import urlsplit

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSplitter, QVBoxLayout, QWidget)

from ddm.widgets import AUTO_QUALITY, DanmakuPanel, ROOM_MIME, Tile
from ddm.audio_output import route_pcm_s16_stereo
from ddm.fullscreen_cursor import FullscreenCursor
from ddm import theme
from .engine import Alignment, Match, RATE, match_scenes, refine_match, mix_pcm
from .media import Chat, Decoder, PlatformChat

COLORS = ("#38bdf8", "#fb7185", "#a78bfa", "#4ade80", "#fbbf24", "#fb923c")


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
        return frame

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        if self.image.isNull():
            if self.waiting:
                return
            painter.setPen(QColor("#a1a1aa"))
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


class AudioPump(QObject):
    status = Signal(str)

    def __init__(self, viewer):
        super().__init__(viewer)
        self.viewer = viewer
        self.sink = None
        self.device = None
        self.anchor = 0.0
        self.written = 0
        self.correction = 0.0
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
        self.correction = 0.0
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
                if self.sink is not None else time.monotonic()) + self.correction

    def fill(self):
        if self.sink is None or self.device is None:
            return
        shifts = self.viewer.shifts()
        for _ in range(3):
            frames = min(2048, self.sink.bytesFree() // 4)
            if frames < 240:
                break
            clock = self.anchor + self.written / RATE + self.correction
            inputs = []
            for room_id, row in self.viewer.rows.items():
                if (row.decoder is not None and row.audible.isChecked() and not row.paused
                        and not self.viewer.sync_waiting):
                    pcm = row.decoder.history.pcm_at(clock + shifts[room_id], frames)
                    pcm = route_pcm_s16_stereo(pcm, row.channel.currentData())
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
        heading.addWidget(QLabel("偏移对照 · 主画面与选中直播间"))
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
                canvas.setMinimumSize(200, 110)
                state = QLabel()
                state.setWordWrap(True)
                layout = QVBoxLayout(card)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(name)
                layout.addWidget(canvas, 1)
                layout.addWidget(state)
                card.hide()
                self.cards[room_id] = (card, name, canvas, state)
        reference = self.viewer.alignment.reference
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
        self.target.setVisible(len(choices) > 1)
        shown = tuple(key for key in (reference, self.target.currentData()) if key in rows)
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
                    if self.viewer.canvas.frame is not None:
                        canvas.set_frame(self.viewer.canvas.frame)
                    waiting = self.viewer.canvas.waiting
                else:
                    frame = canvas.show_at(row.decoder, clock + shifts[room_id]) if row.decoder else None
                    waiting = frame is None or self.viewer.sync_waiting
                repaint |= canvas.waiting != waiting
                canvas.waiting = waiting
            if repaint:
                canvas.update()
            relative = shifts[room_id] - shifts.get(reference, 0)
            position = ("主画面基准" if room_id == reference else
                        f"相对主画面{'提前' if relative >= 0 else '延后'} {abs(relative):.1f} 秒")
            state.setText(f"{position} · {'已暂停' if row.paused else '等待播放缓存' if canvas.waiting else '播放中'}")


class SettingsPanel(QWidget):
    def __init__(self, viewer):
        super().__init__(viewer)
        self.setObjectName("MatchSyncSettings")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumHeight(130)
        self.setMaximumHeight(240)
        self.setStyleSheet(f"""
            #MatchSyncSettings, #MatchSyncRows {{
                background: transparent; border: none;
            }}
            #MatchSyncSettings QLabel, #MatchSyncSettings QCheckBox {{ color: {theme.TEXT1}; }}
            #MatchSyncSettings QScrollArea, #MatchSyncSettings QScrollArea > QWidget {{
                background: transparent; border: none;
            }}
            #MatchSyncSettings QPushButton, #MatchSyncSettings QLineEdit,
            #MatchSyncSettings QComboBox, #MatchSyncSettings QDoubleSpinBox {{
                background: rgba(58, 63, 71, 170); color: {theme.TEXT1};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_MD}px; padding: 4px 6px;
            }}
            #MatchSyncSettings QPushButton:hover {{
                background: {theme.ACCENT_SOFT}; border-color: {theme.ACCENT};
            }}
            #MatchSyncSettings QPushButton:checked {{
                background: rgba(251, 114, 153, 45); border-color: {theme.PINK};
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
        tint.setColorAt(0, QColor(48, 53, 62, 238))
        tint.setColorAt(1, QColor(29, 33, 40, 245))
        painter.fillPath(path, tint)


class RoomRow(QFrame):
    def __init__(self, viewer, room_id, preferences, color):
        super().__init__(viewer)
        self.viewer = viewer
        self.room_id = room_id
        self.platform = viewer.context.manager.platform_for(room_id)
        self.decoder = None
        self.chat = None
        self.paused = False
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
        self.alias.setPlaceholderText("主播名称")
        self.alias.setFixedWidth(100)
        self.main_button = QPushButton("主画面")
        self.main_button.setCheckable(True)
        self.main_button.setFixedWidth(64)
        self.main_button.setToolTip("选择这位主播作为主画面，其他路声音与弹幕继续播放。")
        self.main_button.clicked.connect(lambda: viewer.select_main(room_id))
        self.audible = QCheckBox("声音")
        self.audible.setChecked(preferences.get("audible", True))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(preferences.get("volume", 42))
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
        remove = QPushButton("移除")
        remove.setFixedWidth(52)
        remove.clicked.connect(lambda: viewer.remove_room(room_id))
        self.control_widgets = (self.alias, self.main_button, self.audible, self.volume,
                                self.volume_number, self.channel,
                                self.show_chat, self.color_choice, QLabel("偏移"), self.decrease,
                                self.delay, self.increase, region, remove)
        controls = QGridLayout()
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(4)
        columns = []
        column = 0
        for index, widget in enumerate(self.control_widgets):
            if index in (2, 6, 8, 12, 13):
                controls.setColumnStretch(column, 1)
                column += 1
            columns.append(column)
            controls.addWidget(widget, 0, column)
            column += 1
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.offset_hint = QLabel("单位：秒 · + 正数延后本路 · − 负数相对提前本路")
        self.offset_hint.setObjectName("MatchSyncOffsetHint")
        self.offset_hint.setWordWrap(True)
        self.offset_hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.offset_hint.setStyleSheet(
            f"QLabel#MatchSyncOffsetHint {{ color: {theme.TEXT3}; font-size: {theme.FONT_CAPTION}px; }}")
        controls.addWidget(self.status, 1, 0, 1, columns[8] - 1)
        controls.addWidget(self.offset_hint, 1, columns[8], 1, columns[12] - columns[8])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        layout.setSizeConstraint(QLayout.SetMinimumSize)
        layout.addLayout(controls)
        self.setFrameShape(QFrame.NoFrame)
        self.refresh_status()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.delay.setToolTip("单位秒；+ 延后本路，− 相对提前本路（必要时延后其他路）。画面、声音和弹幕一起移动。")
        self.delay.valueChanged.connect(viewer._delay_changed)
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
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setSuffix(" s")
        spin.setValue(value)
        return spin

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
        text = f"{self.video_text} · {self.match_text} · {self.chat_text}"
        self.status.setText(text + (f" · {self.buffer_text}" if self.buffer_text else ""))


class Viewer(QDialog):
    def __init__(self, context, sources, initial_room=None):
        super().__init__(context.window)
        self.context = context
        self.sources = sources
        self.rows = {}
        self.saved_rooms = {str(item["room_id"]): item for item in context.setting("rooms", [])}
        self.running = False
        self.overlay_pending = {}
        self.overlay_last = ""
        self.alignment = Alignment()
        self.generation = 0
        self.matching = False
        self.locked_clock = None
        self.sync_waiting = False
        self.offset_repositioning = False
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
        self.automatic.setToolTip("手动修改偏移会锁定相对时间；重新勾选会清零手动偏移、收起对照并恢复自动对齐。")
        self.automatic.setChecked(context.setting("automatic", True))
        self.automatic.toggled.connect(self._automatic_changed)
        self.compare = QCheckBox("对照微调")
        self.compare.toggled.connect(self.set_comparison_visible)
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
        self.restore_settings.setStyleSheet(f"""
            QPushButton {{ background: rgba(58, 63, 71, 170); color: {theme.TEXT1};
                border: 1px solid {theme.BORDER}; border-radius: {theme.RADIUS_MD}px;
                padding: 4px 6px; }}
            QPushButton:hover {{ background: {theme.ACCENT_SOFT}; border-color: {theme.ACCENT}; }}
        """)
        self.restore_settings.clicked.connect(lambda: self.set_settings_visible(True))
        self.restore_settings.hide()
        heading = QHBoxLayout()
        heading.setSpacing(6)
        self.main.hide()
        heading.addWidget(self.automatic)
        heading.addWidget(self.compare)
        for widget in self.add_controls:
            heading.addWidget(widget)
        heading.addStretch()
        heading.addWidget(self.minimize_settings)
        self.picture = Tile({})
        self.canvas = Canvas(self.picture.video)
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
        self.focus_shortcut = QShortcut(QKeySequence(
            getattr(context.window, "shortcuts", {}).get("focus", "F")), self.picture)
        self.focus_shortcut.setAutoRepeat(False)
        self.focus_shortcut.activated.connect(self._fullscreen_picture)
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
        split.setStyleSheet("QSplitter::handle { background: #30343a; }")
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
        self.controls.setMinimumHeight(60)
        self.body_split = QSplitter(Qt.Vertical)
        self.body_split.setHandleWidth(4)
        self.body_split.setStyleSheet("QSplitter::handle { background: #30343a; }")
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
        left_layout.addWidget(self.restore_settings, 0, Qt.AlignRight)
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
        self.match_timer.setInterval(1500)
        self.match_timer.timeout.connect(self.analyse)
        self.results = Results()
        self.results.matched.connect(self._matched)
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

    def embed(self, content):
        self.embedded = True
        self.setParent(content, Qt.Widget)
        self.setGeometry(content.rect())
        content.installEventFilter(self)
        for widget in self.add_controls:
            widget.hide()
        self.notice.setText("从左侧关注栏拖入直播间；选择主画面，各路声音与弹幕会合并。")

    def eventFilter(self, watched, event):
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
        if self.embedded:
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

    def _sync_sidebar_marks(self):
        sidebar = getattr(self.context.window, "sidebar", None)
        if not self.embedded or sidebar is None or self.isHidden():
            return
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
        if not visible:
            self.settings_height = self.settings_panel.height()
            self.compare.setChecked(False)
        self.settings_panel.setVisible(visible)
        self.restore_settings.setVisible(not visible)
        if visible:
            self.left_pane.layout().activate()
            self.body_split.setSizes([
                max(1, self.body_split.height() - self.settings_height -
                    (self.comparison_panel.height() if self.compare.isChecked() else 0)),
                self.comparison_panel.height() if self.compare.isChecked() else 0, self.settings_height])

    def set_comparison_visible(self, visible):
        sizes = self.body_split.sizes()
        self.comparison_panel.setVisible(visible)
        self.generation += 1
        height = 240 if visible else 0
        self.body_split.setSizes([max(1, sizes[0] + sizes[1] - height), height, sizes[2]])
        if visible:
            self.comparison_panel.render(self.audio.clock(), self.shifts())

    def _delay_changed(self, *_args):
        key = next((key for key, row in self.rows.items() if row.delay is self.sender()), "")
        before = self.alignment.shifts({key: 0 if self.alignment.automatic else row.previous_delay
                                       for key, row in self.rows.items()})
        for row in self.rows.values():
            row.previous_delay = row.delay.value()
        if not self.alignment.automatic and not self.alignment.manual_locked:
            self.alignment.lags = {self.alignment.reference: 0}
        self.alignment.manual_locked = True
        self.automatic.setChecked(False)
        self.alignment.candidates.clear()
        self.locked_clock = None
        self.sync_waiting = False
        self.offset_repositioning = True
        reference = self.alignment.reference
        shifts = self.shifts()
        ranges = [(bounds[0] - shifts[key], bounds[1] - shifts[key])
                  for key, row in self.rows.items() if row.decoder is not None and not row.paused
                  if (bounds := row.decoder.history.bounds())]
        if key != reference and (not ranges or max(start for start, _ in ranges) > min(end for _, end in ranges) - .25):
            self.audio.correction += before.get(reference, 0) - shifts.get(reference, 0)
        for row in self.rows.values():
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
        if selected != self.alignment.reference:
            self.prefer_highest = True
            self.alignment.select_reference(selected)
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
                self._stop_recording()
                self.canvas.set_frame(None)
                tile.set_room({"room_id": row.room_id, "uname": row.label(), "live": True,
                               "quality": row.quality})
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

    def _automatic_changed(self, *_args):
        self.alignment.automatic = self.automatic.isChecked()
        if self.alignment.automatic:
            for row in self.rows.values():
                row.delay.blockSignals(True)
                row.delay.setValue(0)
                row.delay.blockSignals(False)
                row.previous_delay = 0
            self.compare.setChecked(False)
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
        self.changed()

    def remove_room(self, room_id):
        row = self.rows.pop(room_id)
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

    def shifts(self):
        return self.alignment.shifts({key: 0 if self.alignment.automatic else row.delay.value()
                                      for key, row in self.rows.items()})

    def toggle_running(self):
        if self.running:
            self.stop()
            return
        if not self.rows:
            self.notice.setText("请先添加直播间")
            return
        self.running = True
        self.generation += 1
        if not self.alignment.manual_locked:
            self.alignment.lags = {self.alignment.reference: 0}
        self.locked_clock = None
        self.sync_waiting = False
        self.alignment.candidates.clear()
        self.panel.set_status("多房间弹幕")
        for row in self.rows.values():
            self._start_row(row)
        self.sync_picture()
        self._sync_sidebar_marks()
        self.audio.start()
        self.render_timer.start()
        self.match_timer.start()

    def _start_row(self, row):
        row.paused = False
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
            if not self.alignment.manual_locked:
                self.alignment.lags = {self.alignment.reference: 0}
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
        ranges = []
        active = sum(row.decoder is not None and not row.paused for row in self.rows.values())
        for key, row in self.rows.items():
            decoder = row.decoder
            if (decoder is None or row.paused or
                    (not self.alignment.manual_locked and
                     now - getattr(decoder, "last_frame_received", 0) > 3)):
                continue
            bounds = decoder.history.bounds()
            if bounds:
                ranges.append((bounds[0] - shifts[key], bounds[1] - shifts[key]))
        if self.alignment.manual_locked and active:
            lower = max((start for start, _end in ranges), default=clock)
            upper = min((end for _start, end in ranges), default=clock)
            available = len(ranges) == active and lower <= upper - .25
            if self.offset_repositioning:
                self.sync_waiting = False
                if available:
                    recovered = min(max(clock, lower + .1), upper - .25)
                    self.offset_repositioning = False
                    self.audio.correction += recovered - clock
                    self.locked_clock = recovered
                    return recovered
                return clock
            waiting = (not available or clock > upper - .1 or
                       (self.sync_waiting and self.locked_clock is not None and
                        upper < self.locked_clock + .25))
            fresh = all(now - getattr(row.decoder, "last_frame_received", 0) <= 3
                        for row in self.rows.values() if row.decoder is not None and not row.paused)
            if (available and fresh and (self.locked_clock is None or clock > upper + 1)
                    and (self.locked_clock is None or upper >= self.locked_clock + .25)):
                recovered = min(max(clock, lower + .1), upper - .25)
                waiting = False
            elif waiting:
                recovered = (self.locked_clock if self.locked_clock is not None else
                             min(clock, upper - .25) if available else clock)
            else:
                recovered = lower + .1 if clock < lower else clock
            self.sync_waiting = waiting
            self.locked_clock = recovered
            self.audio.correction += recovered - clock
            return recovered
        if ranges:
            lower = max(start for start, _end in ranges)
            upper = min(end for _start, end in ranges)
            if clock > upper + 1 and lower <= upper - .25:
                recovered = upper - .25
                self.audio.correction += recovered - clock
                return recovered
            if clock < lower and len(ranges) == active and lower <= upper - .25:
                # Reuse available history after an offset change or reconnect.
                recovered = lower + .1
                self.audio.correction += recovered - clock
                return recovered
        return clock

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
        shifts = self.shifts()
        clock = self._recover_clock(clock, shifts)
        row = self.rows.get(self.alignment.reference)
        if row is not None and row.decoder is not None and not row.paused:
            frame = self.canvas.show_at(row.decoder, clock + shifts[row.room_id])
            self._show_buffering(frame is None or self.sync_waiting)
            if self.sync_waiting:
                self.notice.setText("手动时间已锁定，等待各路播放缓存恢复；相对偏移保持不变")
            elif frame is None:
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
        if self.compare.isChecked():
            self.comparison_panel.render(clock, shifts)
        eligible = []
        chat_budget = min(80, max(1, 200 // max(1, len(self.rows))))
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

    def analyse(self):
        if not self.running or not self.alignment.automatic or self.matching or self.compare.isChecked():
            return
        row = self.rows.get(self.alignment.reference)
        if row is None or row.decoder is None:
            return
        reference = row.decoder.history.snapshots()
        others = {key: value.decoder.history.snapshots() for key, value in self.rows.items()
                  if key != row.room_id and value.decoder is not None}
        details = {}
        for key, value in self.rows.items():
            if value.decoder is not None:
                with value.decoder.history.lock:
                    details[key] = (list(getattr(value.decoder.history, "details", ()))
                                    if value.decoder.history.origin is not None else [])
        known = dict(self.alignment.lags)
        reference_id = row.room_id
        clock, shifts = self.audio.clock(), self.shifts()
        positions = {key: clock + shifts[key] for key in details}
        has_picture = self.canvas.frame_key is not None
        if has_picture:
            positions[reference_id] = self.canvas.frame_key
        epoch, bridge = self.generation, self.results
        self.matching = True

        def run():
            results = {}
            for key, samples in others.items():
                if details.get(reference_id) and details.get(key):
                    candidate = (refine_match(Match(known[key], .9, "跟踪已确认偏移"), details[reference_id], details[key])
                                 if key in known else Match(None, 0, "首次匹配"))
                    if candidate.lag is None:
                        candidate = match_scenes(details[reference_id][::4], details[key][::4])
                else:
                    candidate = match_scenes(reference, samples)
                if details.get(reference_id) and details.get(key):
                    if candidate.lag is None and not candidate.candidates and key in known:
                        candidate = Match(known[key], .9, "复核已确认偏移")
                    if not candidate.refined:
                        candidate = refine_match(candidate, details[reference_id], details[key])
                    if candidate.lag is not None and key in known and has_picture:
                        shown_reference = [s for s in details[reference_id] if s.time <= positions[reference_id]]
                        shown_other = [s for s in details[key] if s.time <= positions[key]]
                        verified = refine_match(Match(known[key], .9, "播放进度复核"), shown_reference, shown_other)
                        if verified.lag is not None:
                            candidate = replace(candidate, playback_error=verified.lag - (positions[key] - positions[reference_id]))
                results[key] = candidate
            bridge.matched.emit(epoch, results)
        threading.Thread(target=run, name="match-sync-analysis", daemon=True).start()

    def _matched(self, epoch, results):
        self.matching = False
        if (not self.running or epoch != self.generation or not self.alignment.automatic
                or self.compare.isChecked()):
            return
        for room_id, match in results.items():
            row = self.rows.get(room_id)
            if row is None:
                continue
            applied = self.alignment.accept(room_id, match)
            if match.lag is None:
                row.match_text = match.reason
            elif match.confidence < .65:
                row.match_text = "匹配置信度不足；保持已确认偏移，继续收集画面"
            else:
                if match.refined:
                    verified = match.playback_error is not None and abs(match.playback_error) <= .15
                    status = "播放进度已复核" if applied and verified else "已应用精校正，待复核" if applied else "正在确认精校正"
                    error = f"，剩余误差约 {abs(match.playback_error):.2f} 秒" if match.playback_error is not None else ""
                    row.match_text = f"{status}：相对主画面 {match.lag:+.2f} 秒{error}"
                else:
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
                frozen = (row.decoder.history, frame)
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
        hint = QLabel("两路请框选相同内容；计时器需连续变化，包含数字周围的少量背景。"
                      "匹配失败时可用「对照微调」查看同一播放进度，不会自动读取计时器数字。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(canvas, 1)
        layout.addWidget(reset)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted and canvas.crop.width() > 0.02 and canvas.crop.height() > 0.02:
            rect = canvas.crop
            row.crop = (rect.x(), rect.y(), rect.width(), rect.height())
            row.decoder.set_crop(row.crop)
            self.alignment.candidates.clear()
            self.generation += 1
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
        row.pending.clear()
        row.video_text = "已停止"
        row.chat_text = "弹幕已停止"
        row.match_text = "等待画面"
        row.buffer_text = ""
        row.refresh_status()

    def stop(self):
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
