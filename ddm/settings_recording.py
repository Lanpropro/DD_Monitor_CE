"""Settings recording; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy,
    QSpinBox, QVBoxLayout, QWidget
)
from . import theme
from .ui import ActionButton, SelectControl, StepperControl, ToggleSwitch, page_header as _page_head
from .settings_layout import SettingsColumns, SettingsSection
from .encoders import ENCODER_CHOICES


class RecordingSettingsPage(QWidget):
    """录像参数；修改码率/帧率时自动切到重编码。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("录制与即时回放", "每个格子独立录制直播流；画面墙控件和弹幕不会进入文件。"))
        self.recording_mode_layout = QVBoxLayout()
        layout.addLayout(self.recording_mode_layout)
        self.sections = SettingsColumns(content)
        layout.addWidget(self.sections)
        storage = SettingsSection('格子录制与保存位置')
        recording = SettingsSection('本体录制与编码')
        replay = SettingsSection('本体即时回放缓存')
        for key, card, wide in (('storage', storage, True), ('recording', recording, False),
                                ('replay', replay, False)):
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            self.sections.add_section(key, card, wide=wide)
        self.directory = QLineEdit()
        self.directory.setAccessibleName('保存目录')
        self.directory.setPlaceholderText('选择录制文件的保存位置')
        directory_row = QHBoxLayout()
        directory_row.addWidget(self.directory, 1)
        self.browse = ActionButton("浏览…")
        self.browse.clicked.connect(self._browse)
        directory_row.addWidget(self.browse)
        directory_label = QLabel('保存目录')
        directory_label.setBuddy(self.directory)
        storage.grid.addWidget(directory_label, 0, 0)
        storage.grid.addLayout(directory_row, 0, 1, 1, 2)
        self.recording_enabled = ToggleSwitch("启用录制功能")
        self.recording_enabled.setToolTip(
            "录制功能的总开关。关掉之后：\n"
            "  1) 每格底栏不再有「● 录制」按钮，右键菜单里也没有开始/停止录制；\n"
            "  2) 正在录制的会话会正常收尾并导出（已经录到的部分不丢）；\n"
            "  3) 本体录制参数一起置灰。即时回放是另一个开关，不受影响。")
        self.lock_quality = ToggleSwitch('录制时锁定可用最高分辨率')
        self.lock_quality.setToolTip('录制时锁定可用最高分辨率；实际可用档位由直播源、平台和账号权限决定，结束后恢复录制前的画质。')
        self._field(storage.grid, 1, '格子录制按钮', self.recording_enabled)
        self._field(storage.grid, 2, '录制时锁定可用最高分辨率', self.lock_quality)
        self.min_free = QSpinBox()
        self.min_free.setRange(256, 100000)
        self.min_free.setAccessibleName('磁盘剩余空间警戒线')
        self.min_free_stepper = StepperControl(self.min_free)
        self._field(storage.grid, 3, '磁盘空间警戒线', self.min_free_stepper, 'MB')
        self.format = SelectControl()
        for label, value, hint in (
                ('MP4', 'mp4', 'MP4：剪辑软件兼容性优先。'),
                ('MKV', 'mkv', 'MKV：适合较长录制，抗意外中断。'),
                ('MOV', 'mov', 'MOV：剪辑软件常用容器。'),
                ('TS', 'ts', 'TS：流媒体常用容器。')):
            self.format.addItem(label, value)
            self.format.setItemData(self.format.count() - 1, hint, Qt.ToolTipRole)
        self.codec = SelectControl()
        for label, value, hint in (
                ('原始流直存', 'copy', '直接保存原始流，画质不变、负载低；改动码率或帧率会自动切换为 H.264 重编码。'),
                ('H.264 重编码', 'h264', '重新编码为 H.264 视频和 AAC 音频；下方码率、帧率与编码器设置生效。')):
            self.codec.addItem(label, value)
            self.codec.setItemData(self.codec.count() - 1, hint, Qt.ToolTipRole)
        self.encoder = SelectControl()
        short_encoders = {'auto': '自动', 'cpu': 'CPU', 'nvenc': 'NVIDIA NVENC',
                          'qsv': 'Intel QSV', 'amf': 'AMD AMF'}
        for value, label in ENCODER_CHOICES:
            self.encoder.addItem(short_encoders.get(value, label), value)
            self.encoder.setItemData(self.encoder.count() - 1, label + '\n'
                '重编码时自动模式优先显卡编码，不可用或失败时回退 CPU。硬件方案要求显卡、驱动和 FFmpeg 支持；'
                '后台会编码一帧进行探测。H.264 重编码统一使用 8-bit YUV420 输出。', Qt.ToolTipRole)
        self.bitrate = QSpinBox()
        self.bitrate.setRange(500, 50000)
        self.bitrate.setAccessibleName('视频码率')
        self.bitrate_stepper = StepperControl(self.bitrate)
        self.fps = SelectControl()
        for fps in (24, 25, 30, 50, 60):
            self.fps.addItem(str(fps), fps)
        self.segment_minutes = QSpinBox()
        self.segment_minutes.setRange(1, 1440)
        self.segment_minutes.setAccessibleName('自动分段时长')
        self.segment_minutes.setToolTip('达到设定时长后保存当前文件，并继续录制下一个文件。')
        self.segment_stepper = StepperControl(self.segment_minutes)
        for row, (title, control, unit) in enumerate((
                ('输出格式', self.format, ''), ('编码方式', self.codec, ''),
                ('编码器', self.encoder, ''), ('视频码率', self.bitrate_stepper, 'kbps'),
                ('帧率', self.fps, 'fps'), ('自动分段', self.segment_stepper, '分钟'))):
            self._field(recording.grid, row, title, control, unit)
        self.replay_enabled = ToggleSwitch('启用即时回放')
        self.replay_enabled.setToolTip(
            '关闭后不再创建即时回放缓存，已有纯缓存会停止，结束录制时也不再额外保存回放。'
            '录制本身不受影响，仍保存完整文件。')
        self.replay_scope = SelectControl()
        for label, value, hint in (
                ('所有播放格子', 'all', '为所有播放中的格子创建即时回放缓存；每格额外拉取一路直播流，并启动一个 FFmpeg 缓存进程。'),
                ('手动 / 录制时开启', 'recorded', '默认手动开启：右键直播格子启动回放缓存；录制时自动提供回放。缓存未保存时会在停播后清理。')):
            self.replay_scope.addItem(label, value)
            self.replay_scope.setItemData(self.replay_scope.count() - 1, hint, Qt.ToolTipRole)
        self.replay_max = QSpinBox()
        self.replay_max.setRange(0, 99)
        self.replay_max.setSpecialValueText('不限制')
        self.replay_max.setAccessibleName('缓存格子数上限')
        self.replay_max.setToolTip('所有播放格子模式下最多创建几个缓存；0 表示不限制。每格额外拉取一路直播流，手动开启模式不使用此上限。')
        self.replay_max_stepper = StepperControl(self.replay_max)
        self.replay_minutes = QSpinBox()
        self.replay_minutes.setRange(1, 60)
        self.replay_minutes.setAccessibleName('回放缓存时长')
        self.replay_minutes_stepper = StepperControl(self.replay_minutes)
        for row, (title, control, unit) in enumerate((
                ('启用即时回放', self.replay_enabled, ''), ('缓存范围', self.replay_scope, ''),
                ('缓存格子上限', self.replay_max_stepper, ''),
                ('保留最近', self.replay_minutes_stepper, '分钟'))):
            self._field(replay.grid, row, title, control, unit)
        self.codec.currentIndexChanged.connect(self._update_codec)
        self.replay_scope.currentIndexChanged.connect(self._update_enabled)
        self.replay_enabled.toggled.connect(self._update_enabled)
        self.recording_enabled.toggled.connect(self._update_enabled)
        for combo in (self.format, self.codec, self.encoder, self.replay_scope):
            combo.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH)
            combo.currentTextChanged.connect(self._update_choice_hints)
        self.fps.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH)
        self._load(settings)
        self._update_choice_hints()
        self.bitrate.valueChanged.connect(self._enable_transcode)
        self.fps.currentIndexChanged.connect(self._enable_transcode)
        layout.addStretch(1)

    @staticmethod
    def _field(grid, row, title, control, unit=''):
        label = QLabel(title)
        label.setWordWrap(True)
        label.setBuddy(control)
        control.setAccessibleName(title)
        grid.addWidget(label, row, 0)
        if isinstance(control, ToggleSwitch):
            grid.addWidget(control, row, 1, 1, 2, Qt.AlignRight)
        else:
            grid.addWidget(control, row, 1, Qt.AlignRight)
        if unit:
            unit_label = QLabel(unit)
            unit_label.setObjectName('SettingsHint')
            grid.addWidget(unit_label, row, 2)

    def _update_choice_hints(self, *_args):
        for combo in (self.format, self.codec, self.encoder, self.replay_scope):
            combo.setToolTip(combo.currentData(Qt.ToolTipRole) or '')

    def add_recording_mode(self, widget):
        """Place plugin-owned capture routing above the native settings."""
        self.recording_mode_layout.addWidget(widget)

    def _browse(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "选择录制保存目录",
                                                 self.directory.text())
        if value:
            self.directory.setText(value)

    def _load(self, settings: dict) -> None:
        self.directory.setText(str(settings.get("recording_dir") or ""))
        self.format.setCurrentIndex(max(0, self.format.findData(settings.get("recording_format", "mp4"))))
        self.codec.setCurrentIndex(max(0, self.codec.findData(settings.get("recording_codec", "copy"))))
        self.encoder.setCurrentIndex(max(0, self.encoder.findData(
            settings.get("recording_encoder", "auto"))))
        self.bitrate.setValue(int(settings.get("recording_bitrate", 6000)))
        fps_index = self.fps.findData(int(settings.get("recording_fps", 30)))
        self.fps.setCurrentIndex(fps_index if fps_index >= 0 else self.fps.findData(30))
        self.segment_minutes.setValue(int(settings.get("recording_segment_minutes", 60)))
        self.replay_minutes.setValue(int(settings.get("recording_replay_minutes", 3)))
        scope = self.replay_scope.findData(
            str(settings.get("recording_replay_scope", "recorded")))
        self.replay_scope.setCurrentIndex(scope if scope >= 0 else 0)
        self.recording_enabled.setChecked(bool(settings.get("recording_enabled", True)))
        self.replay_enabled.setChecked(bool(settings.get("recording_replay_enabled", True)))
        self.replay_max.setValue(int(settings.get("recording_replay_max_tiles", 3)))
        self.min_free.setValue(int(settings.get("recording_min_free_mb", 2048)))
        self.lock_quality.setChecked(bool(settings.get("recording_lock_quality", True)))
        self._update_codec()
        self._update_enabled()

    def _update_codec(self) -> None:
        hint = ("当前为原始流直存；改动码率或帧率会自动切换为 H.264 重编码"
                if self.codec.currentData() == "copy" else
                "当前使用 H.264 重编码，码率和帧率均会生效")
        self.bitrate.setToolTip(hint)
        self.fps.setToolTip(hint)
        # 编码器只影响重编码；直存原始流时它没有意义，一并跟着录制总开关置灰。
        self.encoder.setEnabled(self.recording_enabled.isChecked()
                                and self.codec.currentData() != "copy")

    def _update_enabled(self) -> None:
        """按两个总开关把不起作用的项置灰，免得用户改了以为没生效。

        录制总开关管「录制参数」那一组；即时回放总开关管「即时回放」那一组，
        其中范围选「只跟着录制走」时，上限也没有意义。
        """
        recording = self.recording_enabled.isChecked()
        for widget in (self.directory, self.browse, self.format, self.codec,
                       self.bitrate_stepper, self.fps, self.segment_stepper, self.min_free_stepper,
                       self.lock_quality):
            widget.setEnabled(recording)
        self._update_codec()
        replay = self.replay_enabled.isChecked()
        self.replay_scope.setEnabled(replay)
        self.replay_minutes_stepper.setEnabled(replay)
        self.replay_max_stepper.setEnabled(replay and self.replay_scope.currentData() == "all")

    def _enable_transcode(self) -> None:
        if self.codec.currentData() == "copy":
            self.codec.setCurrentIndex(self.codec.findData("h264"))

    def reset(self) -> None:
        from .config import DEFAULT_SETTINGS
        self.bitrate.blockSignals(True)
        self.fps.blockSignals(True)
        self._load(DEFAULT_SETTINGS)
        self.bitrate.blockSignals(False)
        self.fps.blockSignals(False)

    def values(self) -> dict:
        return {
            "recording_enabled": self.recording_enabled.isChecked(),
            "recording_dir": self.directory.text().strip(),
            "recording_format": self.format.currentData(),
            "recording_codec": self.codec.currentData(),
            "recording_encoder": self.encoder.currentData(),
            "recording_bitrate": self.bitrate.value(),
            "recording_fps": self.fps.currentData(),
            "recording_segment_minutes": self.segment_minutes.value(),
            "recording_replay_minutes": self.replay_minutes.value(),
            "recording_replay_scope": self.replay_scope.currentData(),
            "recording_replay_enabled": self.replay_enabled.isChecked(),
            "recording_replay_max_tiles": self.replay_max.value(),
            "recording_min_free_mb": self.min_free.value(),
            "recording_lock_quality": self.lock_quality.isChecked(),
        }
