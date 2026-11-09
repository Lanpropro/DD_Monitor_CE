"""Settings general; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget
)
from .config import DEFAULT_VOLUME, DECODE_HINTS, DECODE_MODES, codec_settings
from .motion import AnimatedDialog
from .ui import page_header as _page_head, step_button as _step_button
from .settings_layout import SettingsSection, section_grid
from .bili import BILI_CODECS


class CodecSettingsPanel(QWidget):
    changed = Signal(dict)

    def __init__(self, values: dict, parent=None, *, defaults=None, bili_enabled=True):
        super().__init__(parent)
        self._inherit = defaults is not None
        self._defaults = defaults
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        self.bili_codec = QComboBox()
        self.decode_mode = QComboBox()
        choices = (("bili_codec", "直播源格式", self.bili_codec,
                    self._source_choices()),
                   ("decode_mode", "本机解码方式", self.decode_mode, DECODE_MODES))
        for row, (key, title, combo, options) in enumerate(choices):
            label = QLabel(title)
            label.setBuddy(combo)
            combo.setAccessibleName(title)
            grid.addWidget(label, row, 0)
            if defaults is not None:
                name = next((label for label, value in options if value == defaults[key]), "")
                combo.addItem(f"跟随全局（{name}）", "")
            for label, value in options:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(0, combo.findData(values.get(key, ""))))
            grid.addWidget(combo, row, 1)
        layout.addLayout(grid)
        self.decode_hint = QLabel()
        self.decode_hint.setWordWrap(True)
        self.decode_hint.setObjectName("SettingsHint")
        layout.addWidget(self.decode_hint)
        self._update_decode_hint()
        self.decode_mode.currentIndexChanged.connect(self._update_decode_hint)
        self.hint = QLabel(
            "直播源格式决定接收的视频编码；本机解码方式决定用显卡还是 CPU 播放。\n"
            "B站切换前先探测直播源；未提供所选格式、未提供原画或探测失败时，保留当前格式。\n"
            "AV1 仅B站；其他平台选择 AV1 时依次尝试 HEVC、H.264；HEVC 不可用时回退 H.264。\n"
            "本机解码故障只影响当前窗口，自动回退 CPU；兼容硬解可手动选择。"
            if bili_enabled else
            "直播源格式由平台或插件提供。AV1 仅B站；此窗口选择 AV1 时依次尝试 HEVC、H.264。\n"
            "HEVC 不可用时回退 H.264；旧版插件使用兼容取流，实际编码以解码读数为准。\n"
            "本机解码方式可独立调整；解码故障只影响当前窗口，自动回退 CPU。")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("SettingsHint")
        layout.addWidget(self.hint)
        for combo in (self.bili_codec, self.decode_mode):
            combo.currentIndexChanged.connect(lambda _index: self.changed.emit(self.values()))

    @staticmethod
    def _source_choices():
        return [(label, value) for value, label, _ in BILI_CODECS]

    def _update_decode_hint(self):
        mode = self.decode_mode.currentData()
        if not mode and self._defaults is not None:
            mode = self._defaults["decode_mode"]
        self.decode_hint.setText(DECODE_HINTS.get(mode, ""))

    def values(self) -> dict:
        return {key: combo.currentData() for key, combo in
                (("bili_codec", self.bili_codec), ("decode_mode", self.decode_mode))
                if not self._inherit or combo.currentData()}

    def set_defaults(self, defaults: dict) -> None:
        self._defaults = defaults
        for key, combo, options in (
                ("bili_codec", self.bili_codec, self._source_choices()),
                ("decode_mode", self.decode_mode, DECODE_MODES)):
            label = next(label for label, value in options if value == defaults[key])
            combo.setItemText(0, f"跟随全局（{label}）")
        self._update_decode_hint()

    def set_values(self, values: dict) -> None:
        for key, combo in (("bili_codec", self.bili_codec), ("decode_mode", self.decode_mode)):
            blocked = combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(values.get(key, ""))))
            combo.blockSignals(blocked)
        self._update_decode_hint()


class CodecSettingsDialog(AnimatedDialog):
    def __init__(self, values: dict, parent=None, *, defaults=None, bili_enabled=True,
                 status=None):
        super().__init__(parent)
        self.setWindowTitle("当前窗口编解码设置" if defaults is not None else "编解码设置")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addLayout(_page_head(self.windowTitle(),
            "修改后立即应用到此窗口，关闭后保留；切换时会重新连接直播。"
            if defaults is not None else "作为所有窗口的默认值，在外层设置中保存后生效。"))
        self.controls = CodecSettingsPanel(values, self, defaults=defaults,
                                            bili_enabled=bili_enabled)
        layout.addWidget(self.controls)
        if status is not None:
            self.status_label = QLabel()
            self.status_label.setWordWrap(True)
            self.status_label.setTextFormat(Qt.TextFormat.PlainText)
            self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(self.status_label)
            self._status_timer = QTimer(self)
            self._status_timer.setInterval(500)
            self._status_timer.timeout.connect(lambda: self.status_label.setText(status()))
            self.finished.connect(self._status_timer.stop)
            self.status_label.setText(status())
            self._status_timer.start()
        buttons = QHBoxLayout()
        if defaults is not None:
            reset = QPushButton("恢复跟随全局")
            reset.setObjectName("IconButton")
            reset.clicked.connect(self._reset_inheritance)
            buttons.addWidget(reset)
        else:
            cancel = QPushButton("取消")
            cancel.setObjectName("IconButton")
            cancel.clicked.connect(self.reject)
            buttons.addWidget(cancel)
        buttons.addStretch()
        close = QPushButton("关闭" if defaults is not None else "确定")
        close.setObjectName("PrimaryButton")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _reset_inheritance(self):
        for combo in (self.controls.bili_codec, self.controls.decode_mode):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.controls.changed.emit(self.controls.values())
        self.controls._update_decode_hint()


class GeneralSettingsPage(QWidget):
    """常规：关注列表、直播预览、解码与新格子初始声音。"""

    ITEMS = [
        ("default_muted", "新建格子初始静音"),
        ("fullscreen_solo_audio", "全屏只播放该路声音"),
        ("volume_normalization", "音量均衡（减小直播间音量差异）"),
        ("fullscreen_auto_hide_controls", "全屏时自动收起底部控制条"),
        ("sidebar_auto_compact", "自动切换紧凑列表"),
        ("sidebar_compact_background", "紧凑关注卡片显示背景图（Banner／封面）"),
        ("preview_on_hover", "关注栏直播预览"),
        ("sidebar_platform_logos", "显示关注栏平台 Logo"),
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
        layout.addLayout(_page_head("常规", "这里设置全局默认；单窗画质、声音和编解码可在窗口右键菜单中调整"))

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
        step_box.insertStretch(0, 1)
        grid.addLayout(step_box, row, 1)
        row += 1
        for key, label in self.ITEMS:
            if key in ('volume_normalization', 'sidebar_platform_logos'):
                box = QCheckBox(label)
                grid.addWidget(box, row, 0, 1, 2)
            else:
                from .ui import ToggleSwitch
                box = ToggleSwitch(label)
                title = QLabel(label)
                title.setWordWrap(True)
                title.setBuddy(box)
                toggle_row = QHBoxLayout()
                toggle_row.setContentsMargins(0, 6, 0, 6)
                toggle_row.addWidget(title, 1)
                toggle_row.addWidget(box)
                grid.addLayout(toggle_row, row, 0, 1, 2)
            box.setChecked(bool(settings.get(key, key != "volume_normalization")))
            if key == "volume_normalization":
                box.setToolTip("自动调整偏轻或偏响的声音；保存后应用于所有播放格子，仍可独立调节音量。")
            self._checks[key] = box
            if key == "sidebar_platform_logos":
                # Retain the saved master value and insertion anchor for plugin controls.
                box.hide()
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
                threshold_box.insertStretch(0, 1)
                grid.addLayout(threshold_box, row, 1)
                box.toggled.connect(self.compact_threshold_spin.setEnabled)
                self.compact_threshold_spin.setEnabled(box.isChecked())
                row += 1
        from .settings_codec_editor import InlineCodecEditor
        self.codec_editor = InlineCodecEditor(settings)
        self.codec_editor.hide()
        self.codec_button = QPushButton()
        self.codec_button.setObjectName("IconButton")
        self.codec_button.setAccessibleName("编解码设置")
        self.codec_button.setCheckable(True)
        self.codec_button.setAutoDefault(False)
        self.codec_button.toggled.connect(self._set_codecs_expanded)
        self.codec_button.toggled.connect(self._update_codec_summary)
        self.codec_editor.changed.connect(self._update_codec_summary)
        self._update_codec_summary()
        grid.addWidget(self.codec_button, row, 0, 1, 2)
        row += 1
        grid.addWidget(QLabel("新建格子的初始音量"), row, 0)
        volume_box = QHBoxLayout()
        volume_box.setSpacing(10)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setMinimumWidth(100)
        self.volume_slider.setMaximumWidth(240)
        self.volume_slider.setValue(int(settings.get("default_volume", DEFAULT_VOLUME)))
        self.volume_label = QLabel(str(self.volume_slider.value()))
        self.volume_label.setObjectName("NavSub")
        self.volume_label.setFixedWidth(28)
        # 直接连接接收控件，避免回调持有父页面并在退出时触发析构重入。
        self.volume_slider.valueChanged.connect(self.volume_label.setNum)
        volume_box.addWidget(self.volume_slider)
        volume_box.addWidget(self.volume_label)
        self.volume_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid.addLayout(volume_box, row, 1)
        row += 1
        grid.addWidget(self.codec_editor, row, 0, 1, 2)
        row += 1
        from .audio_normalization_ui import AudioNormalizationEditor
        self.normalization_editor = AudioNormalizationEditor(settings.get('volume_normalization_curve'))
        self.normalization_editor.setEnabled(self._checks['volume_normalization'].isChecked())
        self._checks['volume_normalization'].toggled.connect(self.normalization_editor.setEnabled)
        grid.addWidget(self.normalization_editor, row, 0, 1, 2)
        self.sections = section_grid(grid, (
            ('playback', '播放与声音', (1, 11, 2, 4, 10, 12), False),
            ('following', '关注与预览', (0, 5, 6, 7, 8), False),
            ('normalization', '音量均衡', (3, row), True),
        ), anchor=self._checks['sidebar_platform_logos'])
        for key in ('playback', 'following'):
            self.sections.section(key).setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        self.sections._arrange()
        layout.addLayout(grid)
        layout.addStretch(1)

    def _update_codec_summary(self):
        values = self.codec_editor.values()
        codec = {"avc": "H.264", "hevc": "HEVC", "av1": "AV1"}.get(
            values["bili_codec"], "H.264")
        mode = {'auto': '自动解码', 'd3d11va-copy': '兼容硬解', 'none': 'CPU 解码',
                'd3d11va': 'D3D11VA', 'dxva2': 'DXVA2'}[values['decode_mode']]
        action = '收起' if self.codec_button.isChecked() else '展开'
        self.codec_button.setText(f"编解码　{codec} · {mode}　{action}")
        self.codec_button.setToolTip('收起编解码选项' if self.codec_button.isChecked() else '展开编解码选项')

    def _edit_codecs(self):
        self.codec_button.toggle()

    def _set_codecs_expanded(self, expanded):
        self.codec_editor.setVisible(expanded)
        card = self.sections.section('playback')
        card.layout().activate()
        card.updateGeometry()
        self.sections._arrange()

    def reset(self) -> None:
        from . import config as config_module
        from .audio_normalization import normalize_curve
        self.normalization_editor.set_curve(normalize_curve())

        for key in self._hidden_values:
            self._hidden_values[key] = config_module.DEFAULT_SETTINGS[key]
        self.poll_spin.setValue(config_module.DEFAULT_SETTINGS["poll_minutes"])
        for key, _label in self.ITEMS:
            self._checks[key].setChecked(bool(config_module.DEFAULT_SETTINGS[key]))
        self.compact_threshold_spin.setValue(
            config_module.DEFAULT_SETTINGS["sidebar_compact_threshold"])
        self.codec_editor.set_values(codec_settings(config_module.DEFAULT_SETTINGS))
        self._update_codec_summary()
        self.volume_slider.setValue(config_module.DEFAULT_SETTINGS["default_volume"])

    def values(self) -> dict:
        result = {
            **self._hidden_values,
            "poll_minutes": int(self.poll_spin.value()),
            "default_volume": int(self.volume_slider.value()),
            "volume_normalization_curve": self.normalization_editor.values(),
            "sidebar_compact_threshold": int(self.compact_threshold_spin.value()),
            **self.codec_editor.values(),
        }
        for key, _label in self.ITEMS:
            result[key] = bool(self._checks[key].isChecked())
        return result


class TraySettingsPage(QWidget):
    def __init__(self, settings, parent=None):
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
        layout.addLayout(_page_head("托盘行为", "设置关闭窗口的方式及隐藏到系统托盘后的行为"))
        behavior = SettingsSection('关闭与托盘')
        layout.addWidget(behavior)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(QLabel("关闭窗口时"))
        self.close_behavior_combo = QComboBox()
        self.close_behavior_combo.setAccessibleName("关闭窗口时")
        for label, value in (("每次询问", "ask"), ("隐藏到托盘", "tray"), ("退出程序", "exit")):
            self.close_behavior_combo.addItem(label, value)
        self.close_behavior_combo.setCurrentIndex(max(
            0, self.close_behavior_combo.findData(settings.get("close_behavior", "ask"))))
        self.close_behavior_combo.setMinimumWidth(180)
        row.addWidget(self.close_behavior_combo)
        row.addStretch(1)
        behavior.grid.addLayout(row, 0, 0, 1, 2)
        self.pause_playback = QCheckBox("进入托盘后暂停播放")
        self.pause_playback.setChecked(bool(settings.get("tray_pause_playback", True)))
        behavior.grid.addWidget(self.pause_playback, 1, 0, 1, 2)
        hint = QLabel("暂停时停止观看取流；恢复主窗口后重新连接直播。原本手动暂停的格子保持暂停，录制继续运行。\n普通最小化或切换到其他软件不受影响。")
        hint.setObjectName("SettingsHint")
        hint.setWordWrap(True)
        behavior.grid.addWidget(hint, 2, 0, 1, 2)
        menu = SettingsSection('画面右键菜单')
        layout.addWidget(menu)
        from .tile_menu import TileMenuEditor
        self.tile_menu = TileMenuEditor(settings.get('tile_context_menu'))
        menu.grid.addWidget(self.tile_menu, 0, 0, 1, 2)
        layout.addStretch(1)

    def values(self):
        return {"close_behavior": self.close_behavior_combo.currentData(),
                "tray_pause_playback": self.pause_playback.isChecked(),
                "tile_context_menu": self.tile_menu.values()}

    def reset(self):
        from .config import DEFAULT_SETTINGS
        self.pause_playback.setChecked(DEFAULT_SETTINGS["tray_pause_playback"])
        self.tile_menu.set_choices(DEFAULT_SETTINGS['tile_context_menu'])
        self.close_behavior_combo.setCurrentIndex(
            self.close_behavior_combo.findData(DEFAULT_SETTINGS["close_behavior"]))
