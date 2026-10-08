"""对话框：设置（常规 / 快捷键）、添加直播间、从关注导入。"""
import re
import zipfile

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFontComboBox,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QLineEdit, QListWidget, QListWidgetItem, QKeySequenceEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from . import theme
from .motion import AnimatedDialog, SettingsStack, SlidingTabs
from .player import DECODE_MODES

# 快捷键动作：键名 -> (显示名, 默认按键)
# 按下的键用 QKeySequence 的字符串表示，组合键写成 "Alt+M" / "Ctrl+Shift+F"。
SHORTCUT_ACTIONS = [
    ("focus", "全屏查看鼠标所在的格子", "F"),
    ("restore", "退出全屏", "Esc"),
    ("mute", "静音鼠标所在那一路（再按一次取消）", "M"),
    ("solo", "只保留鼠标所在那一路的声音", "Alt+M"),
]


def _page_head(title: str, hint: str) -> QVBoxLayout:
    """一页设置的开头：标题 + 说明。"""
    box = QVBoxLayout()
    box.setSpacing(4)
    heading = QLabel(title)
    heading.setObjectName("SettingsTitle")
    box.addWidget(heading)
    if hint:
        note = QLabel(hint)
        note.setObjectName("SettingsHint")
        note.setWordWrap(True)
        box.addWidget(note)
    return box


def _step_button(text: str, tooltip: str, slot) -> QPushButton:
    """加减小按钮（系统自带的箭头在深色下看不见，自己画一个）。"""
    button = QPushButton(text)
    button.setObjectName("StepButton")
    button.setFixedSize(28, 28)
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tooltip)
    button.clicked.connect(slot)
    return button


class GeneralSettingsPage(QWidget):
    """常规：关注列表、直播预览、解码与新格子初始声音。"""

    ITEMS = [
        ("default_muted", "新建格子初始静音"),
        ("fullscreen_solo_audio", "全屏只播放该路声音"),
        ("sidebar_auto_compact", "自动切换紧凑列表"),
        ("preview_on_hover", "关注栏直播预览"),
        ("live_alert", "开播气泡提醒"),
    ]

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._checks: dict[str, QCheckBox] = {}
        self._hidden_values = {
            "auto_quality": bool(settings.get("auto_quality", True)),
            "sidebar_card_mode": bool(settings.get("sidebar_card_mode", True)),
            "freeze_watch": True,
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("常规", "这些设置对所有直播间生效，单路的画质/音量仍在各个格子里调"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        row = 0
        grid.addWidget(QLabel("关注列表刷新间隔"), row, 0)
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(1, 30)
        self.poll_spin.setSuffix(" 分钟")
        self.poll_spin.setAlignment(Qt.AlignCenter)
        # 系统样式的上下箭头在深色下看不见，改用自己画的加减按钮
        self.poll_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.poll_spin.setFixedWidth(90)
        self.poll_spin.setValue(int(settings.get("poll_minutes", 1)))
        step_box = QHBoxLayout()
        step_box.setSpacing(6)
        minus = _step_button("−", "调小", self.poll_spin.stepDown)
        plus = _step_button("+", "调大", self.poll_spin.stepUp)
        step_box.addWidget(minus)
        step_box.addWidget(self.poll_spin)
        step_box.addWidget(plus)
        step_box.addStretch(1)
        grid.addLayout(step_box, row, 1)
        row += 1
        for key, label in self.ITEMS:
            box = QCheckBox(label)
            box.setChecked(bool(settings.get(key, True)))
            grid.addWidget(box, row, 0, 1, 2)
            self._checks[key] = box
            row += 1
            if key == "sidebar_auto_compact":
                grid.addWidget(QLabel("自动切换数量"), row, 0)
                self.compact_threshold_spin = QSpinBox()
                self.compact_threshold_spin.setRange(2, 200)
                self.compact_threshold_spin.setSuffix(" 个关注")
                self.compact_threshold_spin.setAlignment(Qt.AlignCenter)
                self.compact_threshold_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
                self.compact_threshold_spin.setFixedWidth(112)
                self.compact_threshold_spin.setValue(
                    int(settings.get("sidebar_compact_threshold", 18)))
                threshold_box = QHBoxLayout()
                threshold_box.setSpacing(6)
                threshold_box.addWidget(_step_button(
                    "−", "调小", self.compact_threshold_spin.stepDown))
                threshold_box.addWidget(self.compact_threshold_spin)
                threshold_box.addWidget(_step_button(
                    "+", "调大", self.compact_threshold_spin.stepUp))
                threshold_box.addStretch(1)
                grid.addLayout(threshold_box, row, 1)
                box.toggled.connect(self.compact_threshold_spin.setEnabled)
                self.compact_threshold_spin.setEnabled(box.isChecked())
                row += 1
        grid.addWidget(QLabel("视频解码方式"), row, 0)
        self.decode_mode = QComboBox()
        for label, value in DECODE_MODES:
            self.decode_mode.addItem(label, value)
        mode = settings.get("decode_mode") or (
            "auto" if settings.get("hw_decode", True) else "none")
        self.decode_mode.setCurrentIndex(max(0, self.decode_mode.findData(mode)))
        self.decode_mode.setToolTip("自动优先使用可用的硬件解码；软件解码占用更多 CPU。切换后正在播放的直播会重新取流。")
        grid.addWidget(self.decode_mode, row, 1)
        row += 1
        grid.addWidget(QLabel("新建格子的初始音量"), row, 0)
        volume_box = QHBoxLayout()
        volume_box.setSpacing(10)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedWidth(240)
        self.volume_slider.setValue(int(settings.get("default_volume", 42)))
        self.volume_label = QLabel(str(self.volume_slider.value()))
        self.volume_label.setObjectName("NavSub")
        self.volume_label.setFixedWidth(28)
        self.volume_slider.valueChanged.connect(
            lambda value: self.volume_label.setText(str(value)))
        volume_box.addWidget(self.volume_slider)
        volume_box.addWidget(self.volume_label)
        volume_box.addStretch(1)
        grid.addLayout(volume_box, row, 1)
        layout.addLayout(grid)
        layout.addStretch(1)

    def reset(self) -> None:
        from . import config as config_module

        for key in self._hidden_values:
            self._hidden_values[key] = config_module.DEFAULT_SETTINGS[key]
        self.poll_spin.setValue(config_module.DEFAULT_SETTINGS["poll_minutes"])
        for key, _label in self.ITEMS:
            self._checks[key].setChecked(bool(config_module.DEFAULT_SETTINGS[key]))
        self.compact_threshold_spin.setValue(
            config_module.DEFAULT_SETTINGS["sidebar_compact_threshold"])
        self.decode_mode.setCurrentIndex(0)
        self.volume_slider.setValue(config_module.DEFAULT_SETTINGS["default_volume"])

    def values(self) -> dict:
        result = {
            **self._hidden_values,
            "poll_minutes": int(self.poll_spin.value()),
            "default_volume": int(self.volume_slider.value()),
            "sidebar_compact_threshold": int(self.compact_threshold_spin.value()),
            "decode_mode": self.decode_mode.currentData(),
        }
        for key, _label in self.ITEMS:
            result[key] = bool(self._checks[key].isChecked())
        return result


class ShortcutSettingsPage(QWidget):
    """快捷键：把鼠标所在那一路放大、还原布局、静音 / 单路声音。"""

    def __init__(self, shortcuts: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._edits: dict[str, QKeySequenceEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("快捷键", "点输入框后直接按下想要的按键组合（Esc 需要单独按一次）"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        for row, (key, label, default) in enumerate(SHORTCUT_ACTIONS):
            grid.addWidget(QLabel(label), row, 0)
            edit = QKeySequenceEdit(QKeySequence(shortcuts.get(key, default)))
            edit.setObjectName("ShortcutEdit")
            edit.setClearButtonEnabled(True)
            edit.setFixedWidth(160)
            grid.addWidget(edit, row, 1, Qt.AlignLeft)
            self._edits[key] = edit
        layout.addLayout(grid)
        layout.addStretch(1)

    def reset(self) -> None:
        for key, _label, default in SHORTCUT_ACTIONS:
            self._edits[key].setKeySequence(QKeySequence(default))

    def values(self) -> dict:
        result = {}
        for key, _label, default in SHORTCUT_ACTIONS:
            text = self._edits[key].keySequence().toString()
            result[key] = text or default
        return result


class DanmakuSettingsPage(QWidget):
    """弹幕格参数，以及与画面弹幕共享的字体和屏蔽词。"""

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
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("弹幕", "字体与屏蔽词同时用于弹幕格和画面弹幕"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        grid.addWidget(QLabel("字体"), 0, 0)
        self.font_box = QFontComboBox()
        self.font_box.setFixedWidth(220)
        current = str(settings.get("danmaku_font") or "")
        if current:
            self.font_box.setCurrentFont(QFont(current))
        grid.addWidget(self.font_box, 0, 1, Qt.AlignLeft)

        grid.addWidget(QLabel("弹幕格字号"), 1, 0)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 32)
        self.size_spin.setAlignment(Qt.AlignCenter)
        self.size_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.size_spin.setFixedWidth(90)
        self.size_spin.setValue(int(settings.get("danmaku_font_size", 13)))
        size_box = QHBoxLayout()
        size_box.setSpacing(6)
        size_box.addWidget(_step_button("−", "调小", self.size_spin.stepDown))
        size_box.addWidget(self.size_spin)
        size_box.addWidget(_step_button("+", "调大", self.size_spin.stepUp))
        size_box.addStretch(1)
        grid.addLayout(size_box, 1, 1)

        grid.addWidget(QLabel("最多保留"), 2, 0)
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(50, 10000)
        self.keep_spin.setSingleStep(50)
        self.keep_spin.setAlignment(Qt.AlignCenter)
        self.keep_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.keep_spin.setFixedWidth(100)
        self.keep_spin.setSuffix(" 条")
        self.keep_spin.setValue(int(settings.get("danmaku_max_blocks", 3000)))
        keep_box = QHBoxLayout()
        keep_box.setSpacing(6)
        keep_box.addWidget(_step_button("−", "少留一些", self.keep_spin.stepDown))
        keep_box.addWidget(self.keep_spin)
        keep_box.addWidget(_step_button("+", "多留一些", self.keep_spin.stepUp))
        keep_box.addStretch(1)
        grid.addLayout(keep_box, 2, 1)

        layout.addLayout(grid)

        tip = QLabel("字号也可以在弹幕格底部那条滑块上实时拖，不用每次进设置")
        tip.setObjectName("SettingsHint")
        layout.addWidget(tip)

        keep_tip = QLabel("超过「最多保留」就从最早的一条开始丢，弹幕格不会越滚越长")
        keep_tip.setObjectName("SettingsHint")
        layout.addWidget(keep_tip)

        layout.addWidget(QLabel("屏蔽词（每行一个）"))
        self.block_edit = QPlainTextEdit()
        self.block_edit.setObjectName("BlockWords")
        self.block_edit.setPlaceholderText("例如：\n文静\n自研文静")
        palette = self.block_edit.palette()          # 占位文字要能在深色底上看清
        palette.setColor(QPalette.PlaceholderText, QColor("#8a8f98"))
        self.block_edit.setPalette(palette)
        self.block_edit.setPlainText("\n".join(settings.get("danmaku_block_words") or []))
        self.block_edit.setFixedHeight(110)
        layout.addWidget(self.block_edit)
        layout.addStretch(1)

    def reset(self) -> None:
        from . import config as config_module

        self.font_box.setCurrentIndex(0)
        self.size_spin.setValue(int(config_module.DEFAULT_SETTINGS["danmaku_font_size"]))
        self.keep_spin.setValue(int(config_module.DEFAULT_SETTINGS["danmaku_max_blocks"]))
        self.block_edit.setPlainText("")

    def values(self) -> dict:
        family = self.font_box.currentFont().family()
        if family == theme.FONT_DEFAULT:
            family = ""                     # 跟主题走，别把默认字体名写进配置
        words = [line.strip() for line in self.block_edit.toPlainText().splitlines()]
        return {
            "danmaku_font": family,
            "danmaku_font_size": int(self.size_spin.value()),
            "danmaku_max_blocks": int(self.keep_spin.value()),
            "danmaku_block_words": [word for word in words if word],
        }


class RecordingSettingsPage(QWidget):
    """录像参数；修改码率/帧率时自动切到重编码。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        layout = QVBoxLayout(self)
        layout.addLayout(_page_head("录制与即时回放", "每个格子独立录制直播流；画面墙控件和弹幕不会进入文件。"))
        grid = QGridLayout()
        layout.addLayout(grid)
        self.directory = QLineEdit()
        grid.addWidget(QLabel("保存目录"), 0, 0)
        directory_row = QHBoxLayout()
        directory_row.addWidget(self.directory, 1)
        self.browse = QPushButton("浏览…")
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
        self.bitrate = QSpinBox()
        self.bitrate.setRange(500, 50000)
        self.fps = QComboBox()
        for fps in (24, 25, 30, 50, 60):
            self.fps.addItem(str(fps), fps)
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
            ("视频码率", self.bitrate, "kbps"), ("帧率", self.fps, "fps"),
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
        grid.addWidget(self.lock_quality, 11, 0, 1, 2)
        self.codec.currentIndexChanged.connect(self._update_codec)
        self.replay_scope.currentIndexChanged.connect(self._update_enabled)
        self.replay_enabled.toggled.connect(self._update_enabled)
        self.recording_enabled.toggled.connect(self._update_enabled)
        self._load(settings)
        self.bitrate.valueChanged.connect(self._enable_transcode)
        self.fps.currentIndexChanged.connect(self._enable_transcode)
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
        self.bitrate.setValue(int(settings.get("recording_bitrate", 6000)))
        fps_index = self.fps.findData(int(settings.get("recording_fps", 30)))
        self.fps.setCurrentIndex(fps_index if fps_index >= 0 else self.fps.findData(30))
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

    def _update_enabled(self) -> None:
        """按两个总开关把不起作用的项置灰，免得用户改了以为没生效。

        录制总开关管「录制参数」那一组；即时回放总开关管「即时回放」那一组，
        其中范围选「只跟着录制走」时，上限也没有意义。
        """
        recording = self.recording_enabled.isChecked()
        for widget in (self.directory, self.browse, self.format, self.codec,
                       self.bitrate, self.fps, self.min_free, self.lock_quality):
            widget.setEnabled(recording)
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
            "recording_bitrate": self.bitrate.value(),
            "recording_fps": self.fps.currentData(),
            "recording_replay_minutes": self.replay_minutes.value(),
            "recording_replay_scope": self.replay_scope.currentData(),
            "recording_replay_enabled": self.replay_enabled.isChecked(),
            "recording_replay_max_tiles": self.replay_max.value(),
            "recording_min_free_mb": self.min_free.value(),
            "recording_lock_quality": self.lock_quality.isChecked(),
        }


class PluginSettingsPage(QWidget):
    """按现有插件接口展示元数据和下次启动的启用选择。"""

    changed = Signal()

    def __init__(self, manager=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setAcceptDrops(True)
        self.setObjectName("SettingsPage")
        self.checks = {}
        self.card_details = {}
        self.update_buttons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("插件", "拖入 ZIP 插件包或含插件 ZIP 的 EXE；安装和启用更改在重启后生效"))
        self.install_button = QPushButton("装载插件…")
        self.install_button.setObjectName("IconButton")
        self.install_button.clicked.connect(self._install)
        actions = QHBoxLayout()
        actions.addWidget(self.install_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        scroll = QScrollArea()
        scroll.setObjectName("PluginScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        installed_layout = QVBoxLayout(content)
        installed_layout.setContentsMargins(0, 0, 4, 0)
        hint_space = QLabel(" ")
        hint_space.setObjectName("SettingsHint")
        installed_layout.addWidget(hint_space)
        self.cards = QVBoxLayout()
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(10)
        installed_layout.addLayout(self.cards)
        entries = manager.catalog() if manager else []
        self._initial_enabled = {entry["id"]: entry["enabled"] for entry in entries}
        self._files_changed = any(entry["status"] == "待重启" for entry in entries) or bool(
            getattr(manager, "_removed", None))
        from .plugin_updates import pending_versions
        self._files_changed = self._files_changed or bool(manager and pending_versions(manager))
        self.empty = None
        if not entries:
            self.empty = QLabel("未发现插件。可装载 ZIP 插件包")
            self.empty.setObjectName("SettingsHint")
            self.empty.setWordWrap(True)
            self.cards.addWidget(self.empty)
        self.cards.addStretch(1)
        for entry in entries:
            self._add_card(entry)
        scroll.setWidget(content)
        from .online_ui import PluginStorePage
        self.store_page = PluginStorePage(manager)
        store_scroll = QScrollArea()
        store_scroll.setObjectName("PluginScroll")
        store_scroll.setWidgetResizable(True)
        store_scroll.setFrameShape(QFrame.NoFrame)
        store_scroll.setWidget(self.store_page)
        self.tabs = SlidingTabs()
        self.tabs.setObjectName("PluginTabs")
        self.tabs.addTab(scroll, "已安装")
        self.tabs.addTab(store_scroll, "插件商店")
        self.tabs.setCornerWidget(self.store_page.refresh, Qt.TopRightCorner)
        self.store_page.refresh.hide()
        self.tabs.currentChanged.connect(self._store_tab_changed)
        self.store_page.installed.connect(self._store_installed)
        self.store_page.offersChanged.connect(self._show_update_notes)
        self.store_page.controlsChanged.connect(self._sync_update_buttons)
        self._show_update_notes(self.store_page.offers)
        layout.addWidget(self.tabs, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.store_page.open_catalog()

    def _store_tab_changed(self, index):
        self.store_page.refresh.setVisible(index == 1)
        if index == 1:
            self.store_page.open_catalog()

    def _store_installed(self, plugin_id):
        previous = {key: check.isChecked() for key, check in self.checks.items()}
        self.checks = {}
        self.card_details = {}
        self.update_buttons = {}
        self.empty = None
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        from .plugin_updates import pending_versions
        pending = pending_versions(self.manager)
        for entry in self.manager.catalog():
            entry["enabled"] = previous.get(entry["id"], entry["enabled"])
            if entry["id"] in pending:
                entry["status"] = "更新至 " + pending[entry["id"]] + " · 待重启"
            self._add_card(entry)
        self._files_changed = True
        self.changed.emit()

    def _show_update_notes(self, offers):
        from .online_ui import plugin_update_notes
        updates = plugin_update_notes(self.manager, offers)
        for plugin_id, (description, status, text) in self.card_details.items():
            description.setText(updates.get(plugin_id, text))
            status.setVisible(plugin_id not in updates)
        self._sync_update_buttons()

    def _sync_update_buttons(self):
        from .online_ui import plugin_update_offers
        from .plugin_updates import pending_versions
        offers = {offer['id']: offer for offer in
                  plugin_update_offers(self.manager, self.store_page.offers)}
        pending = pending_versions(self.manager) if self.manager else {}
        running = {task.key: task for task in self.store_page.jobs}
        for plugin_id, button in self.update_buttons.items():
            task = running.get(plugin_id)
            button.setVisible(plugin_id in offers or plugin_id in pending)
            button.setEnabled(plugin_id in offers and None not in running and task is None)
            button.setText(('校验/解压中' if task.percent >= 100 else f'下载 {task.percent}%')
                           if task else ('待重启' if plugin_id in pending else '更新'))

    def _update_plugin(self, plugin_id):
        offer = next((offer for offer in self.store_page.offers if offer['id'] == plugin_id), None)
        if offer:
            self.store_page.install_offer(offer)

    def _add_card(self, entry):
        card = QFrame()
        card.setObjectName("PluginCard")
        body = QVBoxLayout(card)
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(6)
        top = QHBoxLayout()
        title = QLabel(entry["name"] + ("  v" + entry["version"] if entry["version"] else ""))
        title.setObjectName("PluginName")
        top.addWidget(title)
        top.addStretch(1)
        check = QCheckBox("启用")
        check.setChecked(entry["enabled"])
        self.checks[entry["id"]] = check
        check.toggled.connect(lambda _checked: self.changed.emit())
        top.addWidget(check)
        update = QPushButton("更新")
        update.setObjectName("IconButton")
        update.hide()
        update.clicked.connect(lambda: self._update_plugin(entry["id"]))
        self.update_buttons[entry["id"]] = update
        top.addWidget(update)
        remove = QPushButton("删除")
        remove.setObjectName("IconButton")
        remove.clicked.connect(lambda: self._remove(entry["id"], card))
        top.addWidget(remove)
        body.addLayout(top)
        description = QLabel(entry["description"] or "暂无说明")
        description.setTextFormat(Qt.PlainText)
        description.setWordWrap(True)
        body.addWidget(description)
        status = QLabel(entry["id"] + "  ·  " + entry["status"] +
                        ("：" + entry["reason"] if entry["status"] == "加载失败" else ""))
        status.setObjectName("SettingsHint")
        status.setWordWrap(True)
        body.addWidget(status)
        self.card_details[entry["id"]] = (description, status, description.text())
        self.cards.insertWidget(self.cards.count() - 1, card)

    def _remove(self, plugin_id, card):
        if self.manager is None:
            return
        choice = QMessageBox.question(
            self, "删除插件", f"确定删除插件 {plugin_id} 及其文件吗？\n已加载的插件将在重启后停止运行。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if choice != QMessageBox.Yes:
            return
        try:
            self.manager.remove_plugin(plugin_id)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "删除插件失败", str(error))
            return
        del self.checks[plugin_id]
        self.card_details.pop(plugin_id, None)
        self.update_buttons.pop(plugin_id, None)
        self.cards.removeWidget(card)
        card.deleteLater()
        self.store_page.show_offers(self.store_page.offers)
        self.store_page.offersChanged.emit(self.store_page.offers)
        self._files_changed = True
        self.changed.emit()
        if not self.checks:
            self.empty = QLabel("未发现插件。可装载 ZIP 插件包")
            self.empty.setObjectName("SettingsHint")
            self.cards.insertWidget(0, self.empty)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if (self.manager is not None and urls and all(
                url.isLocalFile() and url.toLocalFile().lower().endswith((".zip", ".exe"))
                for url in urls)):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        self.dragEnterEvent(event)
        if not event.isAccepted():
            return
        for url in event.mimeData().urls():
            self._install_archive(url.toLocalFile())

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def _install(self):
        archive, _ = QFileDialog.getOpenFileName(self, "装载插件", "", "插件包 (*.zip *.exe)")
        self._install_archive(archive)

    def _install_archive(self, archive):
        if not archive or self.manager is None:
            return
        if not zipfile.is_zipfile(archive):
            QMessageBox.warning(self, "装载插件失败",
                                "此文件不是兼容插件包。需要 ZIP，或内含 ZIP 的 EXE，且包含 plugin.json 和 plugin.py。")
            return
        try:
            plugin_id = self.manager.install_zip(archive)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            QMessageBox.warning(self, "装载插件失败", str(error))
            return
        if self.empty is not None:
            self.empty.deleteLater()
            self.empty = None
        entry = next(item for item in self.manager.catalog() if item["id"] == plugin_id)
        self._add_card(entry)
        self._files_changed = True
        self.changed.emit()
        from .online_ui import show_result
        show_result(self.window(), "插件已安装，保存并重启后生效")

    def needs_restart(self):
        return self._files_changed or {
            key: check.isChecked() for key, check in self.checks.items()
        } != self._initial_enabled

    def enabled_plugins(self):
        return None if all(check.isChecked() for check in self.checks.values()) else [
            name for name, check in self.checks.items() if check.isChecked()]


class SettingsDialog(AnimatedDialog):
    updatesViewed = Signal(object)
    """设置总窗口：左边选类别，右边改内容，不再弹二级菜单。"""

    PAGES = [("general", "常规"), ("danmaku", "弹幕"),
             ("recording", "录制"), ("shortcuts", "快捷键"), ("plugins", "插件"), ("updates", "软件更新")]

    def __init__(self, settings: dict, shortcuts: dict, parent=None, plugin_manager=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.restart_requested = False
        self.seen_versions = dict(settings.get('seen_update_versions') or {})
        self.resize(720, 500)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(180)
        self.nav.setFocusPolicy(Qt.NoFocus)
        from .online_ui import UpdateNavDelegate, UpdateDot
        self.nav.setItemDelegate(UpdateNavDelegate(self.nav))
        for key, label in self.PAGES:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.nav.addItem(item)
        root.addWidget(self.nav)

        right = QVBoxLayout()
        right.setContentsMargins(20, 18, 20, 16)
        right.setSpacing(14)
        self.stack = SettingsStack()
        self.stack.setObjectName("SettingsStack")
        self.general_page = GeneralSettingsPage(settings)
        self.danmaku_page = DanmakuSettingsPage(settings)
        self.recording_page = RecordingSettingsPage(settings)
        self.shortcut_page = ShortcutSettingsPage(shortcuts)
        self.plugin_page = PluginSettingsPage(plugin_manager)
        self.plugin_page.store_page.seen_versions = self.seen_versions
        self._plugin_update_dot = UpdateDot()
        from PySide6.QtWidgets import QTabBar
        self.plugin_page.tabs.tabBar().setTabButton(1, QTabBar.RightSide, self._plugin_update_dot)
        from .online_ui import AppUpdatePage
        self.update_page = AppUpdatePage(settings)
        self.stack.addWidget(self.general_page)
        self.stack.addWidget(self.danmaku_page)
        self.stack.addWidget(self.recording_page)
        self.stack.addWidget(self.shortcut_page)
        self.stack.addWidget(self.plugin_page)
        self.stack.addWidget(self.update_page)
        right.addWidget(self.stack, 1)

        buttons = QHBoxLayout()
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.setObjectName("IconButton")
        self.reset_button.clicked.connect(self._reset_current)
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton("保存")
        self.confirm_button.setObjectName("PrimaryButton")
        self.confirm_button.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        right.addLayout(buttons)
        root.addLayout(right, 1)

        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(0)
        self.plugin_page.changed.connect(self._update_save_button)
        self.plugin_page.store_page.busyChanged.connect(self._update_save_button)
        self.update_page.busyChanged.connect(self._update_save_button)
        self.plugin_page.store_page.offersChanged.connect(self._mark_plugin_updates)
        self.update_page.releaseChecked.connect(self._mark_app_update)
        self._mark_plugin_updates(self.plugin_page.store_page.offers)
        self._update_save_button()

    def _mark_update_page(self, key, active):
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            if item.data(Qt.UserRole) == key:
                item.setData(Qt.UserRole + 1, active)

    def _remember_versions(self, versions):
        if any(self.seen_versions.get(key) != value for key, value in versions.items()):
            self.seen_versions.update(versions)
            self.updatesViewed.emit(dict(self.seen_versions))

    def _mark_app_update(self, offer):
        if offer and self.nav.currentRow() == 5:
            self._remember_versions({'app': offer['version']})
        active = bool(offer and self.seen_versions.get('app') != offer['version'])
        self._mark_update_page('updates', active)

    def _mark_plugin_updates(self, offers):
        from .online_ui import plugin_update_offers
        updates = plugin_update_offers(self.plugin_page.store_page.manager, offers)
        if self.nav.currentRow() == 4:
            self._remember_versions({offer['id']: offer['version'] for offer in updates})
        active = any(self.seen_versions.get(offer['id']) != offer['version'] for offer in updates)
        self._mark_update_page('plugins', active)
        self._plugin_update_dot.setVisible(active)
        self.plugin_page.store_page.update_dots()

    def _update_save_button(self, *_args) -> None:
        self.confirm_button.setText("保存并重启" if self.plugin_page.needs_restart() else "保存")
        self.confirm_button.setEnabled(not self.plugin_page.store_page.jobs and not self.update_page.jobs)

    def _save(self) -> None:
        self.restart_requested = self.plugin_page.needs_restart()
        self.accept()

    def done(self, result):
        self.stack.finish_transition()
        self.plugin_page.store_page.stop()
        self.update_page.stop()
        super().done(result)

    def _on_page_changed(self, index: int) -> None:
        if index >= 0:
            self.stack.show_page(index, animate=bool(QApplication.mouseButtons()))
            self.reset_button.setText("恢复本页默认")
            self.reset_button.setVisible(self.stack.currentWidget() not in (self.plugin_page, self.update_page))
            if index == 4:
                self._mark_plugin_updates(self.plugin_page.store_page.offers)
            elif index == 5:
                self._mark_app_update(self.update_page.offer)

    def _reset_current(self) -> None:
        page = self.stack.currentWidget()
        if hasattr(page, "reset"):
            page.reset()

    def settings(self) -> dict:
        values = self.general_page.values()
        values.update(self.danmaku_page.values())
        values.update(self.recording_page.values())
        values.update(self.update_page.values())
        values['seen_update_versions'] = dict(self.seen_versions)
        return values

    def shortcuts(self) -> dict:
        return self.shortcut_page.values()

    def enabled_plugins(self):
        return self.plugin_page.enabled_plugins()


class AddRoomDialog(AnimatedDialog):
    """输入房间号或直播间链接。"""

    def __init__(self, parent=None, *, room_id_resolver=None, folders=None):
        super().__init__(parent)
        self.setWindowTitle("添加直播间")
        self.resize(400, 170)
        self.room_id = ""
        self.folder_id = ""
        self.room_id_resolver = room_id_resolver

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("房间号或直播间链接"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("输入房间号或链接")
        self.edit.returnPressed.connect(self.accept)
        layout.addWidget(self.edit)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("添加到文件夹"))
        self.folder_button = QPushButton("未分类")
        self.folder_button.setObjectName("IconButton")
        self.folder_button.setToolTip("选择普通文件夹；智能文件夹会按规则自动归类")
        folder_menu = QMenu(self.folder_button)
        options = [("", "未分类")] + [(folder["id"], folder["name"]) for folder in folders or []
                                       if folder.get("type", "normal") == "normal"]
        for folder_id, name in options:
            action = folder_menu.addAction(name)
            action.setData(folder_id)
            action.setCheckable(True)
            action.setChecked(not folder_id)
            action.triggered.connect(lambda _checked=False, selected=action: self._select_folder(selected))
        self.folder_button.setMenu(folder_menu)
        folder_row.addWidget(self.folder_button, 1)
        layout.addLayout(folder_row)

        self.hint = QLabel("支持 B 站房间号")
        self.hint.setObjectName("AppSubtitle")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("添加")
        confirm.setObjectName("PrimaryButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

    def _select_folder(self, action) -> None:
        self.folder_id = action.data()
        self.folder_button.setText(action.text())
        for option in self.folder_button.menu().actions():
            option.setChecked(option is action)

    def accept(self) -> None:
        text = self.edit.text().strip()
        if self.room_id_resolver is not None:
            try:
                room_id = self.room_id_resolver(text)
            except ValueError as error:
                self.hint.setText(str(error))
                self.hint.setStyleSheet(f"color: {theme.ERROR}")
                return
            if room_id:
                self.room_id = room_id
                super().accept()
                return
        # 优先从直播间链接里取房间号（链接后面常带一堆参数，不能取最后一个数字）
        match = re.search(r"live\.bilibili\.com/(?:blanc/)?(\d+)", text)
        room_id = match.group(1) if match else ""
        if not room_id:
            digits = re.findall(r"\d+", text)
            room_id = digits[0] if len(digits) == 1 else ""
        if not room_id:
            self.hint.setText("没识别到房间号，请检查输入")
            self.hint.setStyleSheet(f"color: {theme.ERROR}")
            return
        self.room_id = room_id
        super().accept()


class FollowImportDialog(QDialog):
    """从关注列表里挑要加入监控室的直播间。

    整行点击即可切换勾选；已在关注列表里的默认勾选（重复导入不会重复添加）。
    """

    INDICATOR_WIDTH = 30      # 勾选方块占据的左侧宽度

    def __init__(self, rooms: list[dict], existing: set[str], parent=None, *, folders=None):
        super().__init__(parent)
        self.setWindowTitle("导入关注")
        self.resize(520, 620)
        self.rooms = rooms
        self.existing = {str(item) for item in existing}
        self.folder_id = ""
        self.folder_changed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        live_count = sum(1 for room in rooms if room["live"])
        self.header = QLabel(f"共 {len(rooms)} 个直播间（{live_count} 个直播中）")
        self.header.setObjectName("AppSubtitle")
        layout.addWidget(self.header)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索主播名称")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_rooms)
        layout.addWidget(self.search_edit)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("放入文件夹"))
        self.folder_button = QPushButton("未分类")
        self.folder_button.setObjectName("IconButton")
        self.folder_button.setAutoDefault(False)
        self.folder_button.setToolTip("选择后调整所有勾选主播的归属；未调整时保留已导入主播的归属")
        folder_menu = QMenu(self.folder_button)
        options = [("", "未分类")] + [(folder["id"], folder["name"]) for folder in folders or []
                                  if folder.get("type", "normal") == "normal"]
        for folder_id, name in options:
            action = folder_menu.addAction(name)
            action.setData(folder_id)
            action.setCheckable(True)
            action.setChecked(not folder_id)
            action.triggered.connect(lambda _checked=False, selected=action: self._select_folder(selected))
        self.folder_button.setMenu(folder_menu)
        folder_row.addWidget(self.folder_button, 1)
        layout.addLayout(folder_row)

        hint = QLabel("取消勾选并点击导入，会从本地关注栏移除对应主播；选择文件夹会调整已勾选主播的归属。")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 快捷筛选
        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.filter_buttons = []
        for text, handler in (("全选", lambda: self._check_all(True)),
                              ("全不选", lambda: self._check_all(False)),
                              ("只选直播中", self._check_live)):
            button = QPushButton(text)
            button.setObjectName("IconButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setToolTip("只操作当前搜索结果")
            button.clicked.connect(handler)
            filters.addWidget(button)
            self.filter_buttons.append(button)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.list = QListWidget()
        self.list.setObjectName("FollowList")
        self.list.itemClicked.connect(self._on_item_clicked)
        for room in rooms:
            room_id = str(room["room_id"])
            item = QListWidgetItem(self._room_text(room))
            item.setData(Qt.UserRole, room)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if room_id in self.existing or room.get("pending_import") else Qt.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("导入")
        self.import_button = confirm
        confirm.setObjectName("PrimaryButton")
        confirm.setAutoDefault(False)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

        self._update_header()

    def _select_folder(self, action) -> None:
        self.folder_id = action.data()
        self.folder_changed = True
        self.folder_button.setText(action.text())
        for option in self.folder_button.menu().actions():
            option.setChecked(option is action)

    def _filter_rooms(self, text: str) -> None:
        # 隐藏条目而不重建列表，保留勾选和异步回填的头像。
        if self.property("loading"):
            return
        query = text.strip().casefold()
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(query not in item.data(Qt.UserRole)["uname"].casefold())
        self._update_header()

    # ---- 勾选交互：整行可点 ----
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        position = self.list.viewport().mapFromGlobal(QCursor.pos())
        rect = self.list.visualItemRect(item)
        if position.x() - rect.x() <= self.INDICATOR_WIDTH:
            self._update_header()      # 点在方块上，Qt 已处理
            return
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)
        self._update_header()

    def _check_all(self, checked: bool) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._update_header()

    def _check_live(self) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(Qt.Checked if item.data(Qt.UserRole)["live"] else Qt.Unchecked)
        self._update_header()

    def _update_header(self) -> None:
        selected = len(self.selected())
        shown = sum(not self.list.item(index).isHidden() for index in range(self.list.count()))
        filtered = f"，当前显示 {shown} 个" if self.search_edit.text().strip() else ""
        pending = sum(not room.get("room_id") for room in self.rooms)
        noun = "关注账号" if any(room.get("anchor_uid") for room in self.rooms) else "直播间"
        detail = f"，{pending} 个直播间待识别" if pending else ""
        self.header.setText(f"共 {len(self.rooms)} 个{noun}{detail}{filtered}，已勾选 {selected} 个")

    @staticmethod
    def _room_text(room):
        status = ("直播间待识别" if not room.get("room_id") else
                  "直播状态待刷新" if room.get("live_known") is False else
                  "直播中" if room["live"] else "未开播")
        return "　".join([room["uname"], status] + ([room["title"][:18]] if room.get("title") else []))

    def update_account(self, account):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.UserRole).get("anchor_uid") == account.get("anchor_uid"):
                self.rooms[index] = dict(account)
                item.setData(Qt.UserRole, dict(account))
                item.setText(self._room_text(account))
                self._update_header()
                return

    # ---- 结果 ----
    def deselected_existing(self) -> list[str]:
        return [str(self.list.item(index).data(Qt.UserRole)["room_id"])
                for index in range(self.list.count())
                if str(self.list.item(index).data(Qt.UserRole)["room_id"]) in self.existing
                and self.list.item(index).checkState() != Qt.Checked]

    def selected(self) -> list[dict]:
        result = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def set_avatar(self, room_id: str, pixmap: QPixmap) -> None:
        """头像下好之后回填（下载是异步的）。"""
        from .widgets import circular_pixmap
        icon_pixmap = circular_pixmap(pixmap, 32)
        for index in range(self.list.count()):
            item = self.list.item(index)
            room = item.data(Qt.UserRole)
            if str(room.get("room_id")) == str(room_id) or "account:" + str(room.get("anchor_uid")) == str(room_id):
                item.setIcon(QIcon(icon_pixmap))
                return
