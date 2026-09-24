"""对话框：设置（常规 / 快捷键）、添加直播间、从关注导入。"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QPalette, QPixmap
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QFileDialog, QFontComboBox,
    QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QKeySequenceEdit, QPlainTextEdit, QPushButton,
    QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from . import theme

# 快捷键动作：键名 -> (显示名, 默认按键)
# 按下的键用 QKeySequence 的字符串表示，组合键写成 "Alt+M" / "Ctrl+Shift+F"。
SHORTCUT_ACTIONS = [
    ("focus", "把鼠标所在那一路放到主画面", "F"),
    ("restore", "还原上一个布局", "Esc"),
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
    """常规：轮询、画质策略、重连、画面卡死检测、新房间默认音量。"""

    ITEMS = [
        ("auto_quality", "主画面自动用原画，其余自动 720P"),
        ("auto_reconnect", "断流后自动重连"),
        ("freeze_watch", "画面卡死检测（静止画面可能误报，可关掉）"),
        ("hw_decode", "硬件解码（画面卡住/崩溃时关掉试试：改用软解，CPU 会高一些）"),
        ("default_muted", "新加入画面墙的直播间默认静音"),
        ("sidebar_card_mode", "关注列表使用大封面卡片（关闭后为头像＋文字列表）"),
        ("sidebar_auto_compact", "关注较多时自动切换为紧凑列表"),
        ("preview_on_hover", "鼠标停在关注列表的直播上 1 秒，缩略图里直接播放静音预览"),
        ("live_alert", "关注的主播开播时，列表上播一滴粉色水滴 + 「开播了」气泡"),
    ]

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._checks: dict[str, QCheckBox] = {}

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
        grid.addWidget(QLabel("新房间默认音量"), row, 0)
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

        self.poll_spin.setValue(config_module.DEFAULT_SETTINGS["poll_minutes"])
        for key, _label in self.ITEMS:
            self._checks[key].setChecked(bool(config_module.DEFAULT_SETTINGS[key]))
        self.compact_threshold_spin.setValue(
            config_module.DEFAULT_SETTINGS["sidebar_compact_threshold"])
        self.volume_slider.setValue(config_module.DEFAULT_SETTINGS["default_volume"])

    def values(self) -> dict:
        result = {
            "poll_minutes": int(self.poll_spin.value()),
            "default_volume": int(self.volume_slider.value()),
            "sidebar_compact_threshold": int(self.compact_threshold_spin.value()),
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
    """弹幕：字体、字号、最多保留多少条、屏蔽词。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(_page_head("弹幕", "只影响弹幕格；屏蔽词按内容匹配，命中的弹幕直接不显示"))

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

        grid.addWidget(QLabel("字号"), 1, 0)
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
        self.keep_spin.setRange(50, 2000)
        self.keep_spin.setSingleStep(50)
        self.keep_spin.setAlignment(Qt.AlignCenter)
        self.keep_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.keep_spin.setFixedWidth(100)
        self.keep_spin.setSuffix(" 条")
        self.keep_spin.setValue(int(settings.get("danmaku_max_blocks", 300)))
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
        self.block_edit.setPlaceholderText("例如：\n晚安\n打卡\n广告")
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
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        directory_row.addWidget(browse)
        grid.addLayout(directory_row, 0, 1)
        self.format = QComboBox()
        self.format.addItem("MP4（剪辑软件兼容性优先）", "mp4")
        self.format.addItem("MKV（抗意外中断）", "mkv")
        self.format.addItem("MOV（剪辑软件常用）", "mov")
        self.format.addItem("TS（流媒体常用）", "ts")
        self.codec = QComboBox()
        self.codec.addItem("直接保存原始流（画质不变、负载低）", "copy")
        self.codec.addItem("H.264 + AAC 重编码（可调码率/帧率）", "h264")
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
        self.replay_scope.addItem("所有播放中的格子（随时都能回放）", "all")
        self.replay_scope.addItem("只跟着录制走（不录制的格子不开缓存）", "recorded")
        self.replay_scope.setToolTip(
            "「保存最近 N 分钟」这个即时回放功能，给哪些格子开缓存。\n"
            "它跟着直播自动开启，不用手动点；缓存是临时的，没点保存就会在停播时清掉。\n"
            "只跟着录制走（默认）：录制中的格子本来就在写分段，零额外开销。\n"
            "所有播放中的格子：每格常驻一个 FFmpeg 缓存进程，随时能回放，\n"
            "但每格都是再拉一路同样的流 —— 8 格就是 16 路同时下载、1.2 GB 内存，\n"
            "打网游时会明显抢带宽，所以还要用下面的上限封顶。")
        self.replay_max = QSpinBox()
        self.replay_max.setRange(0, 99)
        self.replay_max.setSpecialValueText("不限制")
        self.replay_max.setToolTip(
            "「所有播放中的格子」时，最多给几格开缓存；0 = 不限制。\n"
            "每开一格 = 再拉一路同样的流（带宽翻倍）+ 一个 FFmpeg 进程（约 155 MB 内存）。\n"
            "选「只跟着录制走」时这一项不起作用。")
        self.min_free = QSpinBox()
        self.min_free.setRange(256, 100000)
        self.lock_quality = QCheckBox("录制时锁定原画，结束后恢复原画前的画质")
        for row, (label, widget, unit) in enumerate((
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
        grid.addWidget(self.lock_quality, 10, 0, 1, 2)
        self.codec.currentIndexChanged.connect(self._update_codec)
        self.replay_scope.currentIndexChanged.connect(self._update_scope)
        self.replay_enabled.toggled.connect(self._update_scope)
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
        self.replay_enabled.setChecked(bool(settings.get("recording_replay_enabled", True)))
        self.replay_max.setValue(int(settings.get("recording_replay_max_tiles", 3)))
        self.min_free.setValue(int(settings.get("recording_min_free_mb", 2048)))
        self.lock_quality.setChecked(bool(settings.get("recording_lock_quality", True)))
        self._update_codec()
        self._update_scope()

    def _update_codec(self) -> None:
        hint = ("当前为原始流直存；改动码率或帧率会自动切换为 H.264 重编码"
                if self.codec.currentData() == "copy" else
                "当前使用 H.264 重编码，码率和帧率均会生效")
        self.bitrate.setToolTip(hint)
        self.fps.setToolTip(hint)

    def _update_scope(self) -> None:
        """不起作用的项置灰，免得用户改了以为没生效。

        总开关关掉时，下面三项（范围 / 上限 / 时长）全都不生效；
        范围选「只跟着录制走」时，上限也没有意义。
        """
        enabled = self.replay_enabled.isChecked()
        self.replay_scope.setEnabled(enabled)
        self.replay_minutes.setEnabled(enabled)
        self.replay_max.setEnabled(enabled and self.replay_scope.currentData() == "all")

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


class SettingsDialog(QDialog):
    """设置总窗口：左边选类别，右边改内容，不再弹二级菜单。"""

    PAGES = [("general", "常规"), ("danmaku", "弹幕"),
             ("recording", "录制"), ("shortcuts", "快捷键")]

    def __init__(self, settings: dict, shortcuts: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(720, 500)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(180)
        self.nav.setFocusPolicy(Qt.NoFocus)
        for key, label in self.PAGES:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self.nav.addItem(item)
        root.addWidget(self.nav)

        right = QVBoxLayout()
        right.setContentsMargins(20, 18, 20, 16)
        right.setSpacing(14)
        self.stack = QStackedWidget()
        self.stack.setObjectName("SettingsStack")
        self.general_page = GeneralSettingsPage(settings)
        self.danmaku_page = DanmakuSettingsPage(settings)
        self.recording_page = RecordingSettingsPage(settings)
        self.shortcut_page = ShortcutSettingsPage(shortcuts)
        self.stack.addWidget(self.general_page)
        self.stack.addWidget(self.danmaku_page)
        self.stack.addWidget(self.recording_page)
        self.stack.addWidget(self.shortcut_page)
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
        confirm = QPushButton("保存")
        confirm.setObjectName("PrimaryButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        right.addLayout(buttons)
        root.addLayout(right, 1)

        self.nav.currentRowChanged.connect(self._on_page_changed)
        self.nav.setCurrentRow(0)

    def _on_page_changed(self, index: int) -> None:
        if index >= 0:
            self.stack.setCurrentIndex(index)
            self.reset_button.setText("恢复本页默认")

    def _reset_current(self) -> None:
        page = self.stack.currentWidget()
        if hasattr(page, "reset"):
            page.reset()

    def settings(self) -> dict:
        values = self.general_page.values()
        values.update(self.danmaku_page.values())
        values.update(self.recording_page.values())
        return values

    def shortcuts(self) -> dict:
        return self.shortcut_page.values()


class AddRoomDialog(QDialog):
    """输入房间号或直播间链接。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加直播间")
        self.resize(400, 170)
        self.room_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("房间号或直播间链接"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("例如 1001 或 https://live.bilibili.com/1001")
        self.edit.returnPressed.connect(self.accept)
        layout.addWidget(self.edit)

        self.hint = QLabel("支持直接粘贴直播间地址")
        self.hint.setObjectName("AppSubtitle")
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

    def accept(self) -> None:
        text = self.edit.text().strip()
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

    整行点击即可切换勾选；已在关注列表里的会标注但仍可勾选（重复导入不会重复添加）。
    """

    INDICATOR_WIDTH = 30      # 勾选方块占据的左侧宽度

    def __init__(self, rooms: list[dict], existing: set[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入关注")
        self.resize(520, 620)
        self.rooms = rooms
        self.existing = {str(item) for item in existing}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        live_count = sum(1 for room in rooms if room["live"])
        self.header = QLabel(f"共 {len(rooms)} 个直播间（{live_count} 个直播中）")
        self.header.setObjectName("AppSubtitle")
        layout.addWidget(self.header)

        # 快捷筛选
        filters = QHBoxLayout()
        filters.setSpacing(6)
        for text, handler in (("全选", lambda: self._check_all(True)),
                              ("全不选", lambda: self._check_all(False)),
                              ("只选直播中", self._check_live)):
            button = QPushButton(text)
            button.setObjectName("IconButton")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(handler)
            filters.addWidget(button)
        filters.addStretch(1)
        layout.addLayout(filters)

        self.list = QListWidget()
        self.list.setObjectName("FollowList")
        self.list.itemClicked.connect(self._on_item_clicked)
        for room in rooms:
            room_id = str(room["room_id"])
            flags = [f"{room['uname']}"]
            flags.append("直播中" if room["live"] else "未开播")
            if room["title"]:
                flags.append(room["title"][:18])
            if room_id in self.existing:
                flags.append("已在列表")
            item = QListWidgetItem("　".join(flags))
            item.setData(Qt.UserRole, room)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("IconButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("导入")
        confirm.setObjectName("PrimaryButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

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
            self.list.item(index).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._update_header()

    def _check_live(self) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setCheckState(Qt.Checked if item.data(Qt.UserRole)["live"] else Qt.Unchecked)
        self._update_header()

    def _update_header(self) -> None:
        selected = len(self.selected())
        self.header.setText(f"共 {len(self.rooms)} 个直播间，已勾选 {selected} 个")

    # ---- 结果 ----
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
            if str(room.get("room_id")) == str(room_id):
                item.setIcon(QIcon(icon_pixmap))
                return
