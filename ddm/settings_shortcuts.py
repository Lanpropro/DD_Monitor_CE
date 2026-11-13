"""Shortcut settings page with grouped, card-based controls."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QKeySequenceEdit, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget
)

from .shortcut_actions import SHORTCUT_ACTIONS
from .settings_layout import SettingsColumns
from .ui import SettingsSurface, ToggleSwitch, page_header as _page_head


_SHORTCUT_TITLES = {
    'focus': '全屏查看', 'restore': '退出全屏', 'close_tile': '关闭直播格',
    'danmaku_input': '弹幕输入', 'mute': '静音', 'audio_cycle': '声音轮询',
    'record': '录制', 'video_danmaku': '画面弹幕', 'solo': '单路声音',
    'volume_up': '滚轮增大音量', 'volume_down': '滚轮减小音量',
    'pip_volume_up': '画中画增大音量', 'pip_volume_down': '画中画减小音量',
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

        self.sections = SettingsColumns()
        groups = (
            ('home', '首页快捷键', ('focus', 'restore', 'close_tile', 'danmaku_input')),
            ('general', '常规快捷键', ('mute', 'audio_cycle', 'record', 'video_danmaku', 'solo')),
            ('wheel', '滚轮快捷键', ('volume_up', 'volume_down')),
            ('pip', '画中画快捷键', ('pip_volume_up', 'pip_volume_down')),
        )
        actions_by_key = {key: item for item in SHORTCUT_ACTIONS for key in (item[0],)}
        for key, title, keys in groups:
            self.sections.add_section(key, self._build_group(
                title, [actions_by_key[name] for name in keys], shortcuts))
        layout.addWidget(self.sections)
        layout.addStretch(1)

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
            special_mouse = default.startswith('Shift+Wheel')
            edit = QLineEdit(shortcuts.get(key, default)) if special_mouse else QKeySequenceEdit(QKeySequence(shortcuts.get(key, default)))
            edit.setObjectName('ShortcutEdit')
            if special_mouse:
                edit.setProperty('mouseShortcut', True)
            if isinstance(edit, QKeySequenceEdit):
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
            enabled.toggled.connect(lambda checked, key=key: self._edits[key].setEnabled(checked))
            row.addWidget(enabled, 0, Qt.AlignVCenter)
            box.addLayout(row)
        reset = QPushButton('重置本板块快捷键')
        reset.setObjectName('ShortcutAction')
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(lambda checked=False, actions=actions: self._reset_group(actions))
        box.addWidget(reset, 0, Qt.AlignRight)
        return card

    def _reset_one(self, key):
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
            result[key] = text or default
        return result
