"""Settings shortcuts; owned page implementations with legacy exports in dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QKeySequenceEdit, QScrollArea, QVBoxLayout, QWidget
)
from .ui import page_header as _page_head
from .settings_layout import section_grid
from .shortcut_actions import SHORTCUT_ACTIONS


class ShortcutSettingsPage(QWidget):
    """快捷键：把鼠标所在那一路放大、还原布局、静音 / 单路声音。"""

    def __init__(self, shortcuts: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsPage")
        self._edits: dict[str, QKeySequenceEdit] = {}

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
        self.sections = section_grid(grid, (
            ('view', '画面与导航', (0, 1, 2, 3), False),
            ('interaction', '播放与互动', (4, 5, 6, 7, 8), False),
        ))
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
