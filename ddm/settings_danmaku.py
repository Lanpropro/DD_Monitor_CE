"""Settings danmaku; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QFontComboBox, QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget
)
from . import theme
from .super_chat_preview import SuperChatPlacementPreview
from .ui import SettingsSlider, SettingsValueLabel, ScaleCurveControl, page_header as _page_head, step_button as _step_button
from .settings_layout import section_grid


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
        default_font = theme.danmaku_font_family()
        self.font_box = QFontComboBox()
        self.font_box.setFixedWidth(220)
        current = str(settings.get("danmaku_font") or "")
        self.font_box.setCurrentFont(QFont(current or default_font))
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

        self.super_chat_enabled = QCheckBox('显示醒目留言（SC）')
        self.super_chat_enabled.setChecked(bool(settings.get('super_chat_enabled', True)))
        grid.addWidget(self.super_chat_enabled, 3, 0, 1, 2)
        grid.addWidget(QLabel('SC 不透明度'), 4, 0)
        self.super_chat_opacity = SettingsSlider()
        self.super_chat_opacity.setRange(10, 100)
        self.super_chat_opacity.setValue(int(settings.get('super_chat_opacity', 80)))
        sc_value = SettingsValueLabel(f'{self.super_chat_opacity.value()}%')
        self.super_chat_opacity.valueChanged.connect(lambda value: sc_value.setText(f'{value}%'))
        sc_row = QHBoxLayout()
        sc_row.addWidget(self.super_chat_opacity, 1)
        sc_row.addWidget(sc_value)
        sc_row.addStretch(1)
        grid.addLayout(sc_row, 4, 1)

        self.super_chat_collapse_delay = QSpinBox()
        self.super_chat_collapse_delay.setRange(1, 60)
        self.super_chat_collapse_delay.setMaximumWidth(160)
        self.super_chat_collapse_delay.setValue(int(settings.get('super_chat_collapse_delay', 7)))
        grid.addWidget(QLabel('SC 自动折叠'), 5, 0)
        delay_row = QHBoxLayout()
        delay_row.setSpacing(8)
        delay_row.addWidget(self.super_chat_collapse_delay)
        self.super_chat_collapse_unit = QLabel('秒')
        delay_row.addWidget(self.super_chat_collapse_unit)
        delay_row.addStretch(1)
        grid.addLayout(delay_row, 5, 1)
        self.super_chat_scale = SettingsSlider()
        self.super_chat_scale.setRange(75, 200)
        self.super_chat_scale.setValue(int(settings.get('super_chat_scale', 100)))
        scale_value = SettingsValueLabel(f'{self.super_chat_scale.value()}%')
        self.super_chat_scale.valueChanged.connect(lambda value: scale_value.setText(f'{value}%'))
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.super_chat_scale, 1)
        scale_row.addWidget(scale_value)
        scale_row.addStretch(1)
        grid.addWidget(QLabel('SC 大小（共用）'), 6, 0)
        grid.addLayout(scale_row, 6, 1)
        self.super_chat_scale_with_video = QCheckBox('SC 随画面缩放')
        self.super_chat_scale_with_video.setToolTip('以 720 像素高的画面为基准，卡片、文字和头像一起缩放；曲线可调整，弹幕栏保持手动大小')
        self.super_chat_scale_with_video.setChecked(bool(settings.get('super_chat_scale_with_video', False)))
        self.super_chat_placement = SuperChatPlacementPreview()
        self.super_chat_placement.setFixedHeight(220)
        self.super_chat_placement.apply_settings(settings)
        self.super_chat_opacity.valueChanged.connect(self.super_chat_placement.set_opacity)
        self.super_chat_placement.changed.connect(self._sc_placement_changed)
        self.super_chat_scale.valueChanged.connect(self._sc_scale_changed)
        self.super_chat_scale_with_video.toggled.connect(self._sc_video_scale_changed)
        grid.addWidget(self.super_chat_scale_with_video, 7, 0, 1, 2)
        grid.addWidget(QLabel('SC 位置（画面与弹幕栏分别设置）'), 8, 0, 1, 2)
        self.super_chat_preview_layout = QButtonGroup(self)
        preview_buttons = QHBoxLayout()
        preview_buttons.setSpacing(8)
        for index, text in enumerate(('画面布局', '弹幕栏布局')):
            button = QPushButton(text)
            button.setObjectName('AppearanceChoice')
            button.setCheckable(True)
            button.setMinimumHeight(36)
            button.setCursor(Qt.PointingHandCursor)
            self.super_chat_preview_layout.addButton(button, index)
            preview_buttons.addWidget(button)
        self.super_chat_preview_layout.button(0).setChecked(True)
        self.super_chat_preview_layout.idClicked.connect(self.super_chat_placement.set_layout_mode)
        grid.addLayout(preview_buttons, 9, 0, 1, 2)
        grid.addWidget(self.super_chat_placement, 10, 0, 1, 2)
        self.super_chat_position_sync = QCheckBox('同步画面与弹幕栏的 SC 位置')
        self.super_chat_position_sync.setToolTip('开启时以当前选中的布局位置为准；关闭后可分别调整')
        self.super_chat_position_sync.setChecked(self.super_chat_placement.position_sync)
        self.super_chat_position_sync.toggled.connect(self.super_chat_placement.set_position_sync)
        grid.addWidget(self.super_chat_position_sync, 11, 0, 1, 2)
        self.super_chat_scale_curve = ScaleCurveControl(settings.get('super_chat_scale_curve'),
                                                       strength=int(settings.get('super_chat_scale_strength', 35)))
        self.super_chat_placement.scale_curve = self.super_chat_scale_curve.curve()
        self.super_chat_scale_curve.setEnabled(self.super_chat_scale_with_video.isChecked())
        self.super_chat_scale_with_video.toggled.connect(self.super_chat_scale_curve.setEnabled)
        self.super_chat_scale_curve.curveChanged.connect(self._sc_curve_changed)
        grid.addWidget(QLabel('SC 缩放曲线'), 12, 0)
        grid.addWidget(self.super_chat_scale_curve, 12, 1)
        self.video_danmaku_scale = QCheckBox('弹幕随画面缩放')
        self.video_danmaku_scale.setChecked(bool(settings.get('video_danmaku_scale', True)))
        self.video_danmaku_scale_curve = ScaleCurveControl(settings.get('video_danmaku_scale_curve'),
                                                          strength=int(settings.get('video_danmaku_scale_strength', 35)))
        self.video_danmaku_scale_curve.setEnabled(self.video_danmaku_scale.isChecked())
        self.video_danmaku_scale.toggled.connect(self.video_danmaku_scale_curve.setEnabled)
        grid.addWidget(self.video_danmaku_scale, 13, 0, 1, 2)
        grid.addWidget(QLabel('弹幕缩放曲线'), 14, 0)
        grid.addWidget(self.video_danmaku_scale_curve, 14, 1)

        layout.addLayout(grid)

        tip = QLabel("字号也可以在弹幕格底部那条滑块上实时拖，不用每次进设置")
        tip.setObjectName("SettingsHint")
        layout.addWidget(tip)

        keep_tip = QLabel("超过「最多保留」就从最早的一条开始丢，弹幕格不会越滚越长")
        keep_tip.setObjectName("SettingsHint")
        layout.addWidget(keep_tip)

        block_title = QLabel("屏蔽词（每行一个）")
        layout.addWidget(block_title)
        self.block_edit = QPlainTextEdit()
        self.block_edit.setObjectName("BlockWords")
        self.block_edit.setPlaceholderText("例如：\n文静\n自研文静")
        palette = self.block_edit.palette()          # 占位文字要能在深色底上看清
        palette.setColor(QPalette.PlaceholderText, QColor("#8a8f98"))
        self.block_edit.setPalette(palette)
        self.block_edit.setPlainText("\n".join(settings.get("danmaku_block_words") or []))
        self.block_edit.setFixedHeight(110)
        layout.addWidget(self.block_edit)
        self.sections = section_grid(grid, (
            ('sc_curve', 'SC 缩放曲线', (7, 12), False),
            ('sc_placement', '位置与大小', (6, 8, 9, 10, 11), False),
            ('sc_display', '醒目留言显示与折叠', (3, 4, 5), True),
            ('danmaku_curve', '画面弹幕缩放', (13, 14), False),
            ('font_filter', '字体与屏蔽', (0, 1, 2), False),
        ), full_width_rows=(12, 14))
        font_grid = self.sections.section('font_filter').grid
        for row, widget in enumerate((tip, keep_tip, block_title, self.block_edit), start=3):
            layout.removeWidget(widget)
            if isinstance(widget, QLabel):
                widget.setWordWrap(True)
            font_grid.addWidget(widget, row, 0, 1, 2)
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
