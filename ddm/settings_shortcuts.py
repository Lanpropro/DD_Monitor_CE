"""Shortcut settings page with grouped, card-based controls."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget
)

from .shortcut_actions import SHORTCUT_ACTIONS
from .settings_layout import SettingsColumns, SettingsSection
from .search import matches_query
from .ui import ToggleSwitch, page_header as _page_head


_SHORTCUT_TITLES = {
    'focus': '全屏查看', 'restore': '退出全屏', 'close_tile': '关闭直播格',
    'danmaku_input': '弹幕输入', 'mute': '静音', 'audio_cycle': '声音轮询',
    'toggle_folders': '全部关注文件夹',
    'record': '录制', 'video_danmaku': '画面弹幕', 'solo': '单路声音',
    'volume_up': '滚轮增大音量', 'volume_down': '滚轮减小音量',
    'pip_volume_up': '画中画增大音量', 'pip_volume_down': '画中画减小音量',
}


class ShortcutSettingsPage(QWidget):
    """Grouped shortcut editors; filtering never changes the saved bindings."""

    def __init__(self, shortcuts: dict, parent=None):
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
            ('home', '首页快捷键', ('focus', 'restore', 'close_tile', 'danmaku_input', 'toggle_folders')),
            ('general', '常规快捷键', ('mute', 'audio_cycle', 'record', 'video_danmaku', 'solo')),
            ('wheel', '滚轮快捷键', ('volume_up', 'volume_down')),
            ('pip', '画中画快捷键', ('pip_volume_up', 'pip_volume_down')),
        )
        actions_by_key = {key: item for item in SHORTCUT_ACTIONS for key in (item[0],)}
        for key, title, keys in groups:
            self._group_keys[key] = keys
            self.sections.add_section(key, self._build_group(
                title, [actions_by_key[name] for name in keys], shortcuts))
        layout.addWidget(self.sections)
        layout.addStretch(1)
        self._all_sections = list(self.sections.entries)
        self.search.textChanged.connect(self._filter)

    def _build_group(self, title, actions, shortcuts):
        card = SettingsSection(title)
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
            special_mouse = default.startswith('Shift+Wheel')
            edit = QLineEdit(shortcuts.get(key, default)) if special_mouse else QKeySequenceEdit(QKeySequence(shortcuts.get(key, default)))
            edit.setObjectName('ShortcutEdit')
            if special_mouse:
                edit.setProperty('mouseShortcut', True)
            if isinstance(edit, QKeySequenceEdit):
                edit.setClearButtonEnabled(True)
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
        reset = QPushButton('恢复本组')
        reset.setObjectName('ShortcutAction')
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(lambda checked=False, actions=actions: self._reset_group(actions))
        card.grid.addWidget(reset, len(actions), 0, 1, 2, Qt.AlignRight)
        return card

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
        for entry in self._all_sections:
            key, card, _wide = entry
            match = any(name in visible for name in self._group_keys[key])
            card.setVisible(match)
            if match:
                self.sections.entries.append(entry)
        self.sections._arrange()
        self.empty.setVisible(not visible)

    def _reset_one(self, key):
        self._row_toggles[key].setChecked(True)
        edit = self._edits[key]
        if isinstance(edit, QLineEdit):
            edit.setText(self._defaults[key])
        else:
            edit.setKeySequence(QKeySequence(self._defaults[key]))

    def _reset_group(self, actions):
        for key, _label, _default in actions:
            self._reset_one(key)

    def reset(self) -> None:
        for key in self._edits:
            self._reset_one(key)

    def values(self) -> dict:
        result = {}
        for key, _label, default in SHORTCUT_ACTIONS:
            edit = self._edits[key]
            text = edit.text() if isinstance(edit, QLineEdit) else edit.keySequence().toString()
            result[key] = (text or default) if self._row_toggles[key].isChecked() else ''
        return result
