"""Shortcut settings page with grouped, card-based controls."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QKeySequenceEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget
)

from .shortcut_actions import SHORTCUT_ACTIONS
from .settings_layout import SettingsColumns
from .ui import SettingsSurface, ToggleSwitch, page_header as _page_head


_SHORTCUT_TITLES = {
    'focus': '全屏查看', 'restore': '退出全屏', 'close_tile': '关闭直播格',
    'danmaku_input': '弹幕输入', 'mute': '静音', 'audio_cycle': '声音轮询',
    'record': '录制', 'video_danmaku': '画面弹幕', 'solo': '单路声音',
}


class ShortcutSettingsPage(QWidget):
    """按 BewlyCat 风格分组展示快捷键，值仍由原快捷键字典持有。"""

    def __init__(self, shortcuts: dict, parent=None):
        super().__init__(parent)
        self.setObjectName('SettingsPage')
        self._edits: dict[str, QKeySequenceEdit] = {}
        self._row_toggles: dict[str, ToggleSwitch] = {}
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

        self._build_overview(layout)
        self.sections = SettingsColumns()
        groups = (
            ('home', '首页快捷键', SHORTCUT_ACTIONS[:4]),
            ('general', '常规快捷键', SHORTCUT_ACTIONS[4:]),
        )
        for key, title, actions in groups:
            self.sections.add_section(key, self._build_group(title, actions, shortcuts))
        layout.addWidget(self.sections)
        layout.addStretch(1)

        self._enabled.toggled.connect(self._update_enabled)
        self._update_enabled(self._enabled.isChecked())

    def _build_overview(self, layout):
        card = SettingsSurface()
        card.setObjectName('ShortcutOverview')
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(8)
        row = QHBoxLayout()
        text = QVBoxLayout()
        title = QLabel('启用键盘快捷键')
        title.setObjectName('ShortcutRowTitle')
        text.addWidget(title)
        hint = QLabel('启用或禁用所有键盘快捷键功能')
        hint.setObjectName('SettingsHint')
        text.addWidget(hint)
        row.addLayout(text, 1)
        self._enabled = ToggleSwitch('启用键盘快捷键')
        self._enabled.setChecked(True)
        row.addWidget(self._enabled, 0, Qt.AlignVCenter)
        box.addLayout(row)
        divider = QFrame()
        divider.setObjectName('ShortcutDivider')
        divider.setFixedHeight(1)
        box.addWidget(divider)
        reset = QPushButton('重置所有快捷键')
        reset.setObjectName('ShortcutAction')
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self.reset)
        box.addWidget(reset, 0, Qt.AlignRight)
        layout.addWidget(card)

    def _build_group(self, title, actions, shortcuts):
        card = SettingsSurface()
        card.setObjectName('ShortcutGroup')
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(0)
        heading = QLabel('⌄  ' + title)
        heading.setObjectName('ShortcutGroupTitle')
        box.addWidget(heading)
        for index, (key, description, default) in enumerate(actions):
            if index:
                divider = QFrame()
                divider.setObjectName('ShortcutDivider')
                divider.setFixedHeight(1)
                box.addWidget(divider)
            row = QHBoxLayout()
            row.setContentsMargins(0, 10, 0, 10)
            row.setSpacing(8)
            text = QVBoxLayout()
            text.setSpacing(3)
            label = QLabel(_SHORTCUT_TITLES.get(key, key))
            label.setObjectName('ShortcutRowTitle')
            text.addWidget(label)
            hint = QLabel(description)
            hint.setObjectName('SettingsHint')
            hint.setWordWrap(True)
            text.addWidget(hint)
            row.addLayout(text, 1)
            edit = QKeySequenceEdit(QKeySequence(shortcuts.get(key, default)))
            edit.setObjectName('ShortcutEdit')
            edit.setClearButtonEnabled(True)
            edit.setFixedWidth(150)
            edit.setToolTip('点击后按下新的按键组合')
            self._edits[key] = edit
            row.addWidget(edit, 0, Qt.AlignVCenter)
            edit_button = QPushButton('✎')
            edit_button.setObjectName('ShortcutIconButton')
            edit_button.setFixedSize(30, 30)
            edit_button.setToolTip('编辑快捷键')
            edit_button.setCursor(Qt.PointingHandCursor)
            edit_button.clicked.connect(edit.setFocus)
            row.addWidget(edit_button)
            reset_button = QPushButton('↻')
            reset_button.setObjectName('ShortcutIconButton')
            reset_button.setFixedSize(30, 30)
            reset_button.setToolTip('恢复默认快捷键')
            reset_button.setCursor(Qt.PointingHandCursor)
            reset_button.clicked.connect(lambda checked=False, key=key: self._reset_one(key))
            row.addWidget(reset_button)
            enabled = ToggleSwitch('启用 ' + label.text())
            enabled.setChecked(True)
            self._row_toggles[key] = enabled
            row.addWidget(enabled, 0, Qt.AlignVCenter)
            box.addLayout(row)
        return card

    def _reset_one(self, key):
        self._edits[key].setKeySequence(QKeySequence(self._defaults[key]))

    def _update_enabled(self, enabled):
        for key, edit in self._edits.items():
            active = bool(enabled and self._row_toggles[key].isChecked())
            edit.setEnabled(active)

    def reset(self) -> None:
        for key in self._edits:
            self._reset_one(key)

    def values(self) -> dict:
        result = {}
        for key, _label, default in SHORTCUT_ACTIONS:
            text = self._edits[key].keySequence().toString()
            result[key] = text or default
        return result
