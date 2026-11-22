"""Shortcut settings page with grouped, card-based controls."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget
)

from .shortcut_actions import (
    DEFAULT_HOVER_WHEEL_VOLUME_STEP, DEFAULT_WHEEL_VOLUME_STEP, FULLSCREEN_VOLUME_SHORTCUTS,
    SHORTCUT_ACTIONS, WHEEL_SHORTCUTS, wheel_volume_step
)
from .settings_layout import SettingsColumns, SettingsSection
from .settings_focus import WHEEL_SPEEDS, normalize_wheel_speed
from .search import matches_query
from .sidebar_navigation import NavigationButton
from .ui import SelectControl, StepperControl, ToggleSwitch, page_header as _page_head


_SHORTCUT_TITLES = {
    'focus': '全屏查看', 'restore': '退出全屏', 'close_tile': '关闭直播格',
    'danmaku_input': '弹幕输入', 'mute': '静音', 'audio_cycle': '声音轮询',
    'toggle_folders': '全部关注文件夹',
    'record': '录制', 'video_danmaku': '画面弹幕', 'solo': '单路声音',
    'volume_up': '滚轮增大音量', 'volume_down': '滚轮减小音量',
    'fullscreen_volume_up': '全屏增大音量', 'fullscreen_volume_down': '全屏减小音量',
    'pip_volume_up': '画中画增大音量', 'pip_volume_down': '画中画减小音量',
    'pip_mute': '画中画静音', 'pip_solo': '画中画单路声音', 'pip_exit': '退出画中画',
}


class ShortcutSettingsPage(QWidget):
    """Grouped shortcut editors; filtering never changes the saved bindings."""

    def __init__(self, shortcuts: dict, parent=None, *, settings=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        self._edits: dict[str, QKeySequenceEdit] = {}
        self._row_toggles: dict[str, ToggleSwitch] = {}
        self._rows = {}
        self._group_keys = {}
        self._search_text = {}
        self._defaults = {key: default for key, _label, default in SHORTCUT_ACTIONS}

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
        layout.addLayout(_page_head('快捷键', '启用、修改或恢复播放器快捷键。'))

        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索功能、按键或拼音')
        self.search.setAccessibleName('搜索快捷键')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.empty = QLabel('没有匹配的快捷键')
        self.empty.setObjectName('SettingsHint')
        self.empty.hide()
        layout.addWidget(self.empty)
        self.sections = SettingsColumns()
        groups = (
            ('home', '主窗口 · 画面与关注', ('focus', 'restore', 'close_tile', 'danmaku_input', 'toggle_folders')),
            ('general', '主窗口 · 播放控制', ('mute', 'audio_cycle', 'record', 'video_danmaku', 'solo')),
            ('fullscreen', '主窗口 · 全屏音量', FULLSCREEN_VOLUME_SHORTCUTS),
            ('wheel', '滚轮设置', WHEEL_SHORTCUTS),
            ('pip', '画中画快捷键', ('pip_volume_up', 'pip_volume_down', 'pip_mute', 'pip_solo', 'pip_exit')),
        )
        actions_by_key = {key: item for item in SHORTCUT_ACTIONS for key in (item[0],)}
        for key, title, keys in groups:
            self._group_keys[key] = keys
            self.sections.add_section(key, self._build_group(
                key, title, [actions_by_key[name] for name in keys], shortcuts, settings or {}))
        layout.addWidget(self.sections)
        layout.addStretch(1)
        self._all_sections = list(self.sections.entries)
        self.search.textChanged.connect(self._filter)

    def _build_group(self, group, title, actions, shortcuts, settings):
        reset = NavigationButton('恢复本组', 'reset')
        reset.setFixedSize(24, 24)
        reset.setToolTip(f'恢复「{title}」的默认设置')
        reset.clicked.connect(lambda _checked=False: self._reset_group(actions, wheel=group == 'wheel'))
        card = SettingsSection(title, heading_action=reset)
        card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        for index, (key, description, default) in enumerate(actions):
            widget = QWidget(card)
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            label = QLabel(_SHORTCUT_TITLES.get(key, key))
            label.setWordWrap(True)
            label.setToolTip(description)
            label.setObjectName('ShortcutRowTitle')
            row.addWidget(label, 1)
            self._rows[key] = widget
            self._search_text[key] = ' '.join((title, label.text(), description, key))
            special_mouse = key in WHEEL_SHORTCUTS
            edit = QLineEdit(shortcuts.get(key, default)) if special_mouse else QKeySequenceEdit(QKeySequence(shortcuts.get(key, default)))
            edit.setObjectName('ShortcutEdit')
            if special_mouse:
                edit.setProperty('mouseShortcut', True)
            if isinstance(edit, QKeySequenceEdit):
                edit.setClearButtonEnabled(True)
                if group == 'pip':
                    edit.setMaximumSequenceLength(1)
            edit.setFixedWidth(150)
            edit.setToolTip(description + ('；输入鼠标组合，如 Shift+WheelUp' if special_mouse else '；点击后按下新的按键组合'))
            edit.setAccessibleName(label.text() + '快捷键')
            edit.setAccessibleDescription(description)
            label.setBuddy(edit)
            (edit.textChanged if special_mouse else edit.keySequenceChanged).connect(self._filter)
            self._edits[key] = edit
            row.addWidget(edit, 0, Qt.AlignVCenter)
            reset_button = QPushButton('恢复')
            reset_button.setObjectName('ShortcutAction')
            reset_button.setToolTip('恢复默认快捷键：' + default)
            reset_button.setAccessibleName('恢复' + label.text() + '默认快捷键')
            reset_button.setCursor(Qt.PointingHandCursor)
            reset_button.clicked.connect(lambda checked=False, key=key: self._reset_one(key))
            enabled = ToggleSwitch('启用 ' + label.text())
            enabled.setChecked(bool(shortcuts.get(key, default)))
            self._row_toggles[key] = enabled
            enabled.toggled.connect(lambda checked, key=key: self._edits[key].setEnabled(checked))
            edit.setEnabled(enabled.isChecked())
            row.addWidget(enabled, 0, Qt.AlignVCenter)
            row.addWidget(reset_button)
            card.grid.addWidget(widget, index, 0, 1, 2)
        if group == 'wheel':
            row = len(actions)
            self._wheel_options = self._build_wheel_options(settings, card)
            card.grid.addWidget(self._wheel_options, row, 0, 1, 2)
            self._wheel_speed_row = QWidget(card)
            speed_row = QHBoxLayout(self._wheel_speed_row)
            speed_row.setContentsMargins(0, 0, 0, 0)
            label = QLabel('设置页滚轮灵敏度')
            label.setWordWrap(True)
            self.wheel_speed = SelectControl()
            self.wheel_speed.setFixedWidth(88)
            self.wheel_speed.setAccessibleName(label.text())
            self.wheel_speed.setAccessibleDescription('调节设置页每格滚轮的移动距离，默认 1×。')
            label.setBuddy(self.wheel_speed)
            for speed in WHEEL_SPEEDS:
                self.wheel_speed.addItem(f'{speed}×', speed)
            self.wheel_speed.setCurrentIndex(self.wheel_speed.findData(
                normalize_wheel_speed(settings.get('settings_wheel_speed'))))
            speed_row.addWidget(label)
            speed_row.addWidget(self.wheel_speed)
            card.grid.addWidget(self._wheel_speed_row, row + 1, 0, 1, 2, Qt.AlignLeft)
            self._layout_shortcut_hints = []
            for offset, (text, aliases) in enumerate((
                ('自定义布局等比缩放 · 悬停直播格，Ctrl＋滚轮', 'Ctrl+滚轮 Ctrl+WheelUp Ctrl+WheelDown 画面格 调整大小'),
                ('竖屏占位 · Alt＋滚轮，上滚 1×3、下滚 1×2', '自定义布局 Alt+滚轮 Alt+WheelUp Alt+WheelDown'),
            ), start=2):
                hint = QLabel(text, card)
                hint.setWordWrap(True)
                hint.setObjectName('SettingsHint')
                card.grid.addWidget(hint, row + offset, 0, 1, 2)
                self._layout_shortcut_hints.append((hint, text + ' ' + aliases))
        return card

    def _build_wheel_options(self, settings, card):
        options = QWidget(card)
        grid = QGridLayout(options)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        self.wheel_step = self._add_wheel_step(
            grid, 0, '组合键滚动每格音量', wheel_volume_step(settings.get('wheel_volume_step')))
        self.wheel_step.setToolTip('适用于上方设置的滚轮组合键，默认使用 Shift')
        hover = QLabel('悬停画面时直接用滚轮调节音量', options)
        hover.setWordWrap(True)
        self.hover_wheel_volume = ToggleSwitch(hover.text(), options)
        self.hover_wheel_volume.setChecked(bool(settings.get('hover_wheel_volume', False)))
        hover.setBuddy(self.hover_wheel_volume)
        grid.addWidget(hover, 1, 0)
        grid.addWidget(self.hover_wheel_volume, 1, 1, Qt.AlignRight)
        self.hover_wheel_step = self._add_wheel_step(
            grid, 2, '直接滚动每格音量',
            wheel_volume_step(settings.get('hover_wheel_volume_step'), DEFAULT_HOVER_WHEEL_VOLUME_STEP))
        return options

    def _add_wheel_step(self, grid, row, title, value):
        step = QLabel(title)
        step.setWordWrap(True)
        spin = QSpinBox()
        spin.setRange(1, 100)
        spin.setSuffix(' 点')
        spin.setAccessibleName(title)
        spin.setValue(value)
        step.setBuddy(spin)
        grid.addWidget(step, row, 0)
        grid.addWidget(StepperControl(spin), row, 1, Qt.AlignRight)
        return spin

    def _filter(self, *_args):
        if not hasattr(self, '_all_sections'):
            return
        query = self.search.text().strip()
        visible = set()
        for key, widget in self._rows.items():
            edit = self._edits[key]
            binding = edit.text() if isinstance(edit, QLineEdit) else ' '.join(
                edit.keySequence().toString(format) for format in
                (QKeySequence.PortableText, QKeySequence.NativeText))
            match = matches_query(self._search_text[key] + ' ' + binding, query)
            widget.setVisible(match)
            if match:
                visible.add(key)
        self.sections.entries = []
        wheel_match = matches_query('主窗口 滚轮音量 悬停画面 调节音量 音量步长 直接滚动 组合键滚动', query)
        speed_match = matches_query('滚轮设置 设置页滚轮灵敏度 页面滚动速度', query)
        self._wheel_options.setVisible(wheel_match)
        self._wheel_speed_row.setVisible(speed_match)
        layout_match = False
        for hint, text in self._layout_shortcut_hints:
            match = matches_query(text, query)
            hint.setVisible(match)
            layout_match |= match
        wheel_matches = wheel_match or speed_match or layout_match
        for entry in self._all_sections:
            key, card, _wide = entry
            match = (key == 'wheel' and wheel_matches
                     or any(name in visible for name in self._group_keys[key]))
            card.setVisible(match)
            if match:
                self.sections.entries.append(entry)
        self.sections._arrange()
        self.empty.setVisible(not visible and not wheel_matches)

    def _reset_one(self, key):
        self._row_toggles[key].setChecked(True)
        edit = self._edits[key]
        if isinstance(edit, QLineEdit):
            edit.setText(self._defaults[key])
        else:
            edit.setKeySequence(QKeySequence(self._defaults[key]))

    def _reset_group(self, actions, *, wheel=False):
        for key, _label, _default in actions:
            self._reset_one(key)
        if wheel:
            self.hover_wheel_volume.setChecked(False)
            self.hover_wheel_step.setValue(DEFAULT_HOVER_WHEEL_VOLUME_STEP)
            self.wheel_step.setValue(DEFAULT_WHEEL_VOLUME_STEP)
            self.wheel_speed.setCurrentIndex(0)

    def reset(self) -> None:
        self._reset_group(SHORTCUT_ACTIONS, wheel=True)

    def settings_values(self) -> dict:
        return {'hover_wheel_volume': self.hover_wheel_volume.isChecked(),
                'hover_wheel_volume_step': self.hover_wheel_step.value(),
                'wheel_volume_step': self.wheel_step.value(),
                'settings_wheel_speed': self.wheel_speed.currentData()}

    def values(self) -> dict:
        result = {}
        for key, _label, default in SHORTCUT_ACTIONS:
            edit = self._edits[key]
            text = edit.text() if isinstance(edit, QLineEdit) else edit.keySequence().toString()
            result[key] = (text or default) if self._row_toggles[key].isChecked() else ''
        return result
