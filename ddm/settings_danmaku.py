"""Danmaku settings presentation; the page owns controls, previews and saved values."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QSpinBox, QVBoxLayout, QWidget
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

        font = SettingsSection('弹幕字体与记录')
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
        grid.addWidget(_hint('字体共用于弹幕格和画面弹幕；这里的字号仅控制弹幕格，也可在弹幕格底部调整。超过保留上限后移除最早的内容。'), 3, 0, 1, 2)
        self.sections.add_section('font_filter', font)
        blocking = SettingsSection('屏蔽管理')
        self.blocking_columns = SettingsColumns(respect_preference=False)
        word_panel, user_panel = QWidget(), QWidget()
        word_layout, user_layout = QVBoxLayout(word_panel), QVBoxLayout(user_panel)
        for box in (word_layout, user_layout):
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
        word_layout.addWidget(QLabel('屏蔽词（每行一个）'))
        self.block_edit = QPlainTextEdit()
        self.block_edit.setObjectName('BlockWords')
        self.block_edit.setAccessibleName('弹幕屏蔽词，每行一个')
        self.block_edit.setPlaceholderText('每行输入一个屏蔽词')
        self.block_edit.setPlainText('\n'.join(settings.get('danmaku_block_words') or []))
        self.block_edit.setFixedHeight(150)
        word_layout.addWidget(self.block_edit)
        word_layout.addWidget(_hint('各平台共用，包含屏蔽词的普通弹幕不显示，匹配时忽略大小写；可在弹幕左键菜单中快速添加。'))
        word_layout.addStretch(1)
        user_layout.addWidget(QLabel('屏蔽用户'))
        from .settings_danmaku_blocking import BlockedUsersEditor
        self.blocked_users = BlockedUsersEditor(settings.get('danmaku_blocked_users'))
        user_layout.addWidget(self.blocked_users)
        user_layout.addWidget(_hint('按平台与用户 ID 屏蔽，在该平台所有房间生效；无 ID 的记录按昵称匹配，同名用户也会被屏蔽。移除后恢复接收。'))
        user_layout.addStretch(1)
        self.blocking_columns.add_section('words', word_panel)
        self.blocking_columns.add_section('users', user_panel)
        blocking.grid.addWidget(self.blocking_columns, 0, 0, 1, 2)

        display = QWidget()
        display.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        grid = QGridLayout(display)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)
        self.super_chat_enabled = ToggleSwitch('显示醒目留言')
        self.super_chat_enabled.setChecked(bool(settings.get('super_chat_enabled', True)))
        label = QLabel('显示醒目留言')
        label.setBuddy(self.super_chat_enabled)
        grid.addWidget(label, 0, 0)
        grid.addWidget(self.super_chat_enabled, 0, 1, Qt.AlignRight)
        self.super_chat_opacity = SettingsSlider()
        self.super_chat_opacity.setRange(10, 100)
        self.super_chat_opacity.setValue(int(settings.get('super_chat_opacity', 80)))
        self.super_chat_opacity.setAccessibleName('SC 当前布局不透明度')
        value = self._sc_opacity_value = SettingsValueLabel(f'{self.super_chat_opacity.value()}%')
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
        grid.addWidget(_hint('显示开关和自动折叠共用于画面与弹幕栏；位置、大小和不透明度可按当前布局分别调整。'), 3, 0, 1, 2)

        placement = SettingsSection('醒目留言（SC）')
        self.sc_columns = SettingsColumns(respect_preference=False)
        self.sc_parameters, self.sc_preview = QWidget(), QWidget()
        parameters, preview = QVBoxLayout(self.sc_parameters), QVBoxLayout(self.sc_preview)
        for box in (parameters, preview):
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(12)
        parameters.addWidget(display)
        row = QHBoxLayout()
        scale_label = QLabel('大小（当前布局）')
        scale_label.setWordWrap(True)
        row.addWidget(scale_label, 1)
        self.super_chat_scale = SettingsSlider()
        self.super_chat_scale.setRange(75, 200)
        self.super_chat_scale.setValue(int(settings.get('super_chat_scale', 100)))
        self.super_chat_scale.setAccessibleName('SC 当前布局大小')
        scale_value = self._sc_scale_value = SettingsValueLabel(f'{self.super_chat_scale.value()}%')
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
        parameters.addWidget(_hint('以 720 px 高的画面为基准，卡片、文字与头像一起缩放；此项只影响画面布局。'))
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
        self.super_chat_layout_control.valueChanged.connect(self._sc_layout_changed)
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
        preview.addWidget(_hint('拖动卡片调整位置，拖动右下角调整当前布局大小；双击恢复当前布局的位置和大小。'))
        preview.addStretch(1)
        self.sc_columns.add_section('parameters', self.sc_parameters)
        self.sc_columns.add_section('preview', self.sc_preview)
        placement.grid.addWidget(self.sc_columns, 0, 0, 1, 2)

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
        self.sections.add_section('danmaku_curve', video)
        self.sections.add_section('blocking', blocking, wide=True)
        self.sections.add_section('sc_placement', placement, wide=True)
        layout.addStretch(1)

    def sync_blocking(self, values):
        if 'danmaku_block_words' in values:
            self.block_edit.setPlainText('\n'.join(values['danmaku_block_words'] or []))
        if 'danmaku_blocked_users' in values:
            self.blocked_users.set_users(values['danmaku_blocked_users'])

    def _sc_placement_changed(self, values):
        self._sync_sc_controls()
        self.super_chat_position_sync.setChecked(values['super_chat_position_sync'])

    def _sc_layout_changed(self, mode):
        self.super_chat_placement.set_layout_mode(1 if mode == 'panel' else 0)
        self._sync_sc_controls()

    def _sync_sc_controls(self):
        self.super_chat_scale.blockSignals(True)
        self.super_chat_opacity.blockSignals(True)
        self.super_chat_scale.setValue(self.super_chat_placement.scale)
        self.super_chat_opacity.setValue(self.super_chat_placement.opacity)
        self._sc_scale_value.setText(f'{self.super_chat_placement.scale}%')
        self._sc_opacity_value.setText(f'{self.super_chat_placement.opacity}%')
        self.super_chat_scale.blockSignals(False)
        self.super_chat_opacity.blockSignals(False)

    def _sc_scale_changed(self, value):
        self.super_chat_placement.set_scale(value)
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
        self._sync_sc_controls()
        self.block_edit.setPlainText("")
        self.blocked_users.set_users([])
        self.blocked_users.changed.emit()

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
            "danmaku_blocked_users": self.blocked_users.users(),
            "super_chat_enabled": self.super_chat_enabled.isChecked(),
            "super_chat_opacity": self.super_chat_opacity.value(),
            "super_chat_video_opacity": self.super_chat_placement.values()['super_chat_video_opacity'],
            "super_chat_panel_opacity": self.super_chat_placement.values()['super_chat_panel_opacity'],
            "super_chat_collapse_delay": self.super_chat_collapse_delay.value(),
            "video_danmaku_scale": self.video_danmaku_scale.isChecked(),
            "video_danmaku_scale_curve": self.video_danmaku_scale_curve.curve(),
            **self.super_chat_placement.values(),
            "super_chat_scale_curve": self.super_chat_scale_curve.curve(),
            "super_chat_video_scale": self.super_chat_placement.values()['super_chat_video_scale'],
            "super_chat_panel_scale": self.super_chat_placement.values()['super_chat_panel_scale'],
        }
