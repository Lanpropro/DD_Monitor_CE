"""Settings recording; owned page implementations with legacy exports in dialogs."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget
)
from .ui import page_header as _page_head
from .settings_layout import section_grid
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
        content = QWidget()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.addLayout(_page_head("录制与即时回放", "每个格子独立录制直播流；画面墙控件和弹幕不会进入文件。"))
        grid = QGridLayout()
        layout.addLayout(grid)
        self.directory = QLineEdit()
        grid.addWidget(QLabel("保存目录"), 0, 0)
        directory_row = QHBoxLayout()
        directory_row.addWidget(self.directory, 1)
        self.browse = QPushButton("浏览…")
        self.browse.setObjectName('IconButton')
        self.browse.clicked.connect(self._browse)
        directory_row.addWidget(self.browse)
        grid.addLayout(directory_row, 0, 1)
        self.recording_enabled = QCheckBox("启用录制功能")
        self.recording_enabled.setToolTip(
            "录制功能的总开关。关掉之后：\n"
            "  1) 每格底栏不再有「● 录制」按钮，右键菜单里也没有开始/停止录制；\n"
            "  2) 正在录制的会话会正常收尾并导出（已经录到的部分不丢）；\n"
            "  3) 上面这些录制参数会一起置灰。\n"
            "即时回放是另一个开关，不受影响。")
        self.format = QComboBox()
        self.format.addItem("MP4（剪辑软件兼容性优先）", "mp4")
        self.format.addItem("MKV（抗意外中断）", "mkv")
        self.format.addItem("MOV（剪辑软件常用）", "mov")
        self.format.addItem("TS（流媒体常用）", "ts")
        self.codec = QComboBox()
        self.codec.addItem("直接保存原始流（画质不变、负载低）", "copy")
        self.codec.addItem("H.264 + AAC 重编码", "h264")
        self.encoder = QComboBox()
        for value, label in ENCODER_CHOICES:
            self.encoder.addItem(label, value)
        self.encoder.setToolTip(
            "重编码时用哪个编码器。\n"
            "自动：优先显卡编码（NVENC / QSV / AMF），不可用就回退 CPU。\n"
            "显卡编码通常能降低 CPU 占用；实际负载和画质取决于显卡与录制参数。\n"
            "但它要求显卡、驱动和随包的 FFmpeg 三者同时支持。\n"
            "程序会在后台实际编码一帧来探测；方案不可用，或实际录制时硬件编码失败，\n"
            "会回退 CPU。H.264 重编码统一使用 8-bit YUV420 输出。")
        self.bitrate = QSpinBox()
        self.bitrate.setRange(500, 50000)
        self.fps = QComboBox()
        for fps in (24, 25, 30, 50, 60):
            self.fps.addItem(str(fps), fps)
        self.segment_minutes = QSpinBox()
        self.segment_minutes.setRange(1, 1440)
        self.segment_minutes.setToolTip("达到设定时长后保存当前文件，并继续录制下一个文件。")
        self.replay_minutes = QSpinBox()
        self.replay_minutes.setRange(1, 60)
        self.replay_enabled = QCheckBox("启用「保存最近 N 分钟」")
        self.replay_enabled.setToolTip(
            "即时回放的总开关。关掉之后：\n"
            "  1) 不给任何格子开回放缓存（已经在跑的纯缓存会停掉）；\n"
            "  2) 右键菜单里不再有「保存最近约 N 分钟」；\n"
            "  3) 结束录制时也不再顺手存一份回放。\n"
            "录制本身不受影响，照常写完整文件。")
        self.replay_scope = QComboBox()
        self.replay_scope.addItem("所有格子启用", "all")
        self.replay_scope.addItem("手动开启，录制时自动开启", "recorded")
        self.replay_scope.setToolTip(
            "「保存最近 N 分钟」这个即时回放功能，给哪些格子开缓存。\n"
            "缓存是临时的，没点保存就会在停播时清掉。\n"
            "手动开启（默认）：右键直播格子开启即时回放缓存；录制时自动提供回放。\n"
            "所有播放中的格子：每格常驻一个 FFmpeg 缓存进程，随时能回放，\n"
            "但每格都是再拉一路同样的流 —— 8 格就是 16 路同时下载、1.2 GB 内存，\n"
            "打网游时会明显抢带宽，所以还要用下面的上限封顶。")
        self.replay_max = QSpinBox()
        self.replay_max.setRange(0, 99)
        self.replay_max.setSpecialValueText("不限制")
        self.replay_max.setToolTip(
            "「所有播放中的格子」时，最多给几格开缓存；0 = 不限制。\n"
            "每开一格 = 再拉一路同样的流（带宽翻倍）+ 一个 FFmpeg 进程（约 155 MB 内存）。\n"
            "选「手动开启」时这一项不起作用。")
        self.min_free = QSpinBox()
        self.min_free.setRange(256, 100000)
        self.lock_quality = QCheckBox("录制时锁定原画，结束后恢复原画前的画质")
        for row, (label, widget, unit) in enumerate((
            ("录制功能", self.recording_enabled, ""),
            ("输出格式", self.format, ""), ("编码方式", self.codec, ""),
            ("编码器", self.encoder, ""),
            ("视频码率", self.bitrate, "kbps"), ("帧率", self.fps, "fps"),
            ("自动分段时长", self.segment_minutes, "分钟"),
            ("即时回放", self.replay_enabled, ""),
            ("即时回放范围", self.replay_scope, ""),
            ("缓存格子数上限", self.replay_max, ""),
            ("回放缓存时长", self.replay_minutes, "分钟"),
            ("磁盘剩余空间警戒线", self.min_free, "MB"),
        ), start=1):
            grid.addWidget(QLabel(label), row, 0)
            if unit:
                field = QHBoxLayout()
                field.addWidget(widget, 1)
                field.addWidget(QLabel(unit))
                grid.addLayout(field, row, 1)
            else:
                grid.addWidget(widget, row, 1)
        grid.addWidget(self.lock_quality, 13, 0, 1, 2)
        self.codec.currentIndexChanged.connect(self._update_codec)
        self.replay_scope.currentIndexChanged.connect(self._update_enabled)
        self.replay_enabled.toggled.connect(self._update_enabled)
        self.recording_enabled.toggled.connect(self._update_enabled)
        self._load(settings)
        self.bitrate.valueChanged.connect(self._enable_transcode)
        self.fps.currentIndexChanged.connect(self._enable_transcode)
        self.sections = section_grid(grid, (
            ('storage', '保存位置与空间', (0, 12), True),
            ('recording', '录制与编码', (1, 2, 3, 4, 5, 6, 7, 13), False),
            ('replay', '即时回放缓存', (8, 9, 10, 11), False),
        ))
        layout.addStretch(1)

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
                       self.bitrate, self.fps, self.segment_minutes, self.min_free,
                       self.lock_quality):
            widget.setEnabled(recording)
        self._update_codec()
        replay = self.replay_enabled.isChecked()
        self.replay_scope.setEnabled(replay)
        self.replay_minutes.setEnabled(replay)
        self.replay_max.setEnabled(replay and self.replay_scope.currentData() == "all")

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
