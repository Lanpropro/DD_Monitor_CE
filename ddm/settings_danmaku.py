"""Danmaku settings presentation; the page owns controls, previews and saved values."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QSpinBox, QVBoxLayout, QWidget
from . import theme
from .super_chat import SuperChatPlacementPreview
from .ui import (FontSelectControl, ScaleCurveControl, SegmentedControl, SettingsSlider,
                 SettingsValueLabel, StepperControl, ToggleSwitch, page_header)
from .settings_layout import SettingsColumns, SettingsSection


def _hint(text):
    label = QLabel(text)
    label.setObjectName('SettingsHint')
    label.setWordWrap(True)
    return label


class DanmakuSettingsPage(QWidget):
    """Shared fonts/filtering plus independent video/panel SC placement."""
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QScrollArea
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addLayout(page_header('弹幕', '设置字体、屏蔽词、画面缩放及醒目留言的位置与显示。'))
        self.sections = SettingsColumns(content)
        layout.addWidget(self.sections)

        font = SettingsSection('字体与屏蔽')
        font.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        grid = font.grid
        self.font_box = FontSelectControl()
        self.font_box.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH)
        self.font_box.setAccessibleName('弹幕字体')
        self.font_box.setCurrentFont(QFont(str(settings.get('danmaku_font') or theme.danmaku_font_family())))
        grid.addWidget(QLabel('弹幕字体'), 0, 0)
        grid.addWidget(self.font_box, 0, 1, Qt.AlignRight)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 32)
        self.size_spin.setSuffix(' px')
        self.size_spin.setValue(int(settings.get('danmaku_font_size', 13)))
        self.size_spin.setAccessibleName('弹幕格字号')
        self.size_stepper = StepperControl(self.size_spin)
        grid.addWidget(QLabel('弹幕格字号'), 1, 0)
        grid.addWidget(self.size_stepper, 1, 1, Qt.AlignRight)
        self.keep_spin = QSpinBox()
        self.keep_spin.setRange(50, 10000)
        self.keep_spin.setSingleStep(50)
        self.keep_spin.setSuffix(' 条')
        self.keep_spin.setValue(int(settings.get('danmaku_max_blocks', 3000)))
        self.keep_spin.setAccessibleName('最多保留弹幕')
        self.keep_stepper = StepperControl(self.keep_spin)
        grid.addWidget(QLabel('最多保留'), 2, 0)
        grid.addWidget(self.keep_stepper, 2, 1, Qt.AlignRight)
        grid.addWidget(_hint('字体与屏蔽词共用于弹幕格和画面弹幕；这里的字号仅控制弹幕格，也可在弹幕格底部调整。超过保留上限后移除最早的内容。'), 3, 0, 1, 2)
        grid.addWidget(QLabel('屏蔽词（每行一个）'), 4, 0, 1, 2)
        self.block_edit = QPlainTextEdit()
        self.block_edit.setObjectName('BlockWords')
        self.block_edit.setAccessibleName('弹幕屏蔽词，每行一个')
        self.block_edit.setPlaceholderText('每行输入一个屏蔽词')
        self.block_edit.setPlainText('\n'.join(settings.get('danmaku_block_words') or []))
        self.block_edit.setFixedHeight(110)
        grid.addWidget(self.block_edit, 5, 0, 1, 2)
        self.sections.add_section('font_filter', font)

        display = SettingsSection('醒目留言（SC）')
        display.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        grid = display.grid
        self.super_chat_enabled = ToggleSwitch('显示醒目留言')
        self.super_chat_enabled.setChecked(bool(settings.get('super_chat_enabled', True)))
        label = QLabel('显示醒目留言')
        label.setBuddy(self.super_chat_enabled)
        grid.addWidget(label, 0, 0)
        grid.addWidget(self.super_chat_enabled, 0, 1, Qt.AlignRight)
        self.super_chat_opacity = SettingsSlider()
        self.super_chat_opacity.setRange(10, 100)
        self.super_chat_opacity.setValue(int(settings.get('super_chat_opacity', 80)))
        self.super_chat_opacity.setAccessibleName('SC 不透明度')
        value = SettingsValueLabel(f'{self.super_chat_opacity.value()}%')
        self.super_chat_opacity.valueChanged.connect(lambda amount: value.setText(f'{amount}%'))
        opacity = QHBoxLayout()
        opacity.addStretch(1)
        opacity.addWidget(self.super_chat_opacity)
        opacity.addWidget(value)
        grid.addWidget(QLabel('不透明度'), 1, 0)
        grid.addLayout(opacity, 1, 1, Qt.AlignRight)
        self.super_chat_collapse_delay = QSpinBox()
        self.super_chat_collapse_delay.setRange(1, 60)
        self.super_chat_collapse_delay.setSuffix(' 秒')
        self.super_chat_collapse_delay.setAccessibleName('SC 自动折叠时间')
        self.super_chat_collapse_delay.setValue(int(settings.get('super_chat_collapse_delay', 7)))
        self.super_chat_collapse_stepper = StepperControl(self.super_chat_collapse_delay)
        grid.addWidget(QLabel('自动折叠'), 2, 0)
        grid.addWidget(self.super_chat_collapse_stepper, 2, 1, Qt.AlignRight)
        grid.addWidget(_hint('醒目留言在画面与弹幕栏中共用显示开关和不透明度；展开后经过设定时间自动折叠。位置和缩放在下方调整。'), 3, 0, 1, 2)
        self.sections.add_section('sc_display', display)

        placement = SettingsSection('SC 位置与大小')
        self.sc_columns = SettingsColumns(respect_preference=False)
        self.sc_parameters, self.sc_preview = QWidget(), QWidget()
        parameters, preview = QVBoxLayout(self.sc_parameters), QVBoxLayout(self.sc_preview)
        for box in (parameters, preview):
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
        row = QHBoxLayout()
        scale_label = QLabel('大小（画面与弹幕栏共用）')
        scale_label.setWordWrap(True)
        row.addWidget(scale_label, 1)
        self.super_chat_scale = SettingsSlider()
        self.super_chat_scale.setRange(75, 200)
        self.super_chat_scale.setValue(int(settings.get('super_chat_scale', 100)))
        self.super_chat_scale.setAccessibleName('SC 共用大小')
        scale_value = SettingsValueLabel(f'{self.super_chat_scale.value()}%')
        self.super_chat_scale.valueChanged.connect(lambda amount: scale_value.setText(f'{amount}%'))
        row.addWidget(self.super_chat_scale)
        row.addWidget(scale_value)
        parameters.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('SC 随画面缩放'), 1)
        self.super_chat_scale_with_video = ToggleSwitch('SC 随画面缩放')
        self.super_chat_scale_with_video.setChecked(bool(settings.get('super_chat_scale_with_video', False)))
        row.addWidget(self.super_chat_scale_with_video)
        parameters.addLayout(row)
        parameters.addWidget(_hint('以 720 px 高的画面为基准，卡片、文字与头像一起缩放；弹幕栏保持上方设置的共用大小。'))
        self.super_chat_scale_curve = ScaleCurveControl(settings.get('super_chat_scale_curve'),
                                                       strength=int(settings.get('super_chat_scale_strength', 35)))
        self.super_chat_scale_curve.setEnabled(self.super_chat_scale_with_video.isChecked())
        self.super_chat_scale_with_video.toggled.connect(self.super_chat_scale_curve.setEnabled)
        parameters.addWidget(self.super_chat_scale_curve)
        parameters.addStretch(1)
        self.super_chat_layout_control = SegmentedControl((('video', '画面布局'), ('panel', '弹幕栏布局')))
        self.super_chat_layout_control.setFixedWidth(260)
        self.super_chat_preview_layout = self.super_chat_layout_control.group
        for index, button in enumerate(self.super_chat_layout_control.buttons.values()):
            self.super_chat_preview_layout.setId(button, index)
        preview.addWidget(self.super_chat_layout_control, 0, Qt.AlignRight)
        self.super_chat_placement = SuperChatPlacementPreview()
        self.super_chat_placement.apply_settings(settings)
        self.super_chat_placement.scale_curve = self.super_chat_scale_curve.curve()
        self.super_chat_layout_control.valueChanged.connect(
            lambda mode: self.super_chat_placement.set_layout_mode(1 if mode == 'panel' else 0))
        self.super_chat_opacity.valueChanged.connect(self.super_chat_placement.set_opacity)
        self.super_chat_placement.changed.connect(self._sc_placement_changed)
        self.super_chat_scale.valueChanged.connect(self._sc_scale_changed)
        self.super_chat_scale_with_video.toggled.connect(self._sc_video_scale_changed)
        self.super_chat_scale_curve.curveChanged.connect(self._sc_curve_changed)
        preview.addWidget(self.super_chat_placement)
        row = QHBoxLayout()
        label = QLabel('同步画面与弹幕栏的 SC 位置')
        label.setWordWrap(True)
        row.addWidget(label, 1)
        self.super_chat_position_sync = ToggleSwitch('同步画面与弹幕栏的 SC 位置')
        self.super_chat_position_sync.setChecked(self.super_chat_placement.position_sync)
        self.super_chat_position_sync.setToolTip('开启时以当前选中的布局位置为准；关闭后可分别调整')
        self.super_chat_position_sync.toggled.connect(self.super_chat_placement.set_position_sync)
        row.addWidget(self.super_chat_position_sync)
        preview.addLayout(row)
        preview.addWidget(_hint('拖动卡片调整位置，拖动右下角调整大小；双击恢复当前布局的位置和共用大小。'))
        preview.addStretch(1)
        self.sc_columns.add_section('parameters', self.sc_parameters)
        self.sc_columns.add_section('preview', self.sc_preview)
        placement.grid.addWidget(self.sc_columns, 0, 0, 1, 2)
        self.sections.add_section('sc_placement', placement, wide=True)

        video = SettingsSection('画面弹幕缩放')
        self.video_columns = SettingsColumns(respect_preference=False)
        self.video_parameters, self.video_preview = QWidget(), QWidget()
        parameters, preview = QVBoxLayout(self.video_parameters), QVBoxLayout(self.video_preview)
        for box in (parameters, preview):
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
        row = QHBoxLayout()
        row.addWidget(QLabel('弹幕随画面缩放'), 1)
        self.video_danmaku_scale = ToggleSwitch('弹幕随画面缩放')
        self.video_danmaku_scale.setChecked(bool(settings.get('video_danmaku_scale', True)))
        row.addWidget(self.video_danmaku_scale)
        parameters.addLayout(row)
        parameters.addWidget(_hint('根据画面高度调整画面弹幕大小，弹幕格不受影响。关闭后保留曲线，重新开启时继续使用。'))
        parameters.addStretch(1)
        self.video_danmaku_scale_curve = ScaleCurveControl(settings.get('video_danmaku_scale_curve'),
                                                          strength=int(settings.get('video_danmaku_scale_strength', 35)))
        self.video_danmaku_scale_curve.setEnabled(self.video_danmaku_scale.isChecked())
        self.video_danmaku_scale.toggled.connect(self.video_danmaku_scale_curve.setEnabled)
        preview.addWidget(self.video_danmaku_scale_curve)
        self.video_columns.add_section('parameters', self.video_parameters)
        self.video_columns.add_section('curve', self.video_preview)
        video.grid.addWidget(self.video_columns, 0, 0, 1, 2)
        self.sections.add_section('danmaku_curve', video, wide=True)
        layout.addStretch(1)

    def _sc_placement_changed(self, values):
        self.super_chat_scale.setValue(values['super_chat_scale'])
        self.super_chat_position_sync.setChecked(values['super_chat_position_sync'])

    def _sc_scale_changed(self, value):
        self.super_chat_placement.scale = value
        self.super_chat_placement.update()

    def _sc_video_scale_changed(self, checked):
        self.super_chat_placement.scale_with_video = checked
        self.super_chat_placement.update()

    def _sc_curve_changed(self, points):
        self.super_chat_placement.scale_curve = points
        self.super_chat_placement.update()

    def reset(self) -> None:
        from . import config as config_module

        self.font_box.setCurrentFont(QFont(theme.danmaku_font_family()))
        self.size_spin.setValue(int(config_module.DEFAULT_SETTINGS["danmaku_font_size"]))
        self.keep_spin.setValue(int(config_module.DEFAULT_SETTINGS["danmaku_max_blocks"]))
        self.super_chat_enabled.setChecked(config_module.DEFAULT_SETTINGS['super_chat_enabled'])
        self.super_chat_opacity.setValue(config_module.DEFAULT_SETTINGS['super_chat_opacity'])
        self.super_chat_collapse_delay.setValue(config_module.DEFAULT_SETTINGS['super_chat_collapse_delay'])
        self.super_chat_scale.setValue(config_module.DEFAULT_SETTINGS['super_chat_scale'])
        self.super_chat_scale_with_video.setChecked(config_module.DEFAULT_SETTINGS['super_chat_scale_with_video'])
        self.super_chat_scale_curve.reset()
        self.video_danmaku_scale.setChecked(config_module.DEFAULT_SETTINGS['video_danmaku_scale'])
        self.video_danmaku_scale_curve.reset()
        self.super_chat_placement.apply_settings(config_module.DEFAULT_SETTINGS)
        self.super_chat_placement.scale_curve = self.super_chat_scale_curve.curve()
        self.super_chat_position_sync.setChecked(config_module.DEFAULT_SETTINGS['super_chat_position_sync'])
        self.block_edit.setPlainText("")

    def values(self) -> dict:
        family = self.font_box.currentFont().family()
        if family == theme.danmaku_font_family():
            family = ""                     # 空值使用内置默认弹幕字体
        words = [line.strip() for line in self.block_edit.toPlainText().splitlines()]
        return {
            "danmaku_font": family,
            "danmaku_font_size": int(self.size_spin.value()),
            "danmaku_max_blocks": int(self.keep_spin.value()),
            "danmaku_block_words": [word for word in words if word],
            "super_chat_enabled": self.super_chat_enabled.isChecked(),
            "super_chat_opacity": self.super_chat_opacity.value(),
            "super_chat_collapse_delay": self.super_chat_collapse_delay.value(),
            "video_danmaku_scale": self.video_danmaku_scale.isChecked(),
            "video_danmaku_scale_curve": self.video_danmaku_scale_curve.curve(),
            **self.super_chat_placement.values(),
            "super_chat_scale_curve": self.super_chat_scale_curve.curve(),
        }
