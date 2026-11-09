"""Inline global codec choices; the owning settings page saves the draft."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QLabel, QRadioButton, QVBoxLayout, QWidget

from .config import DECODE_HINTS, DECODE_MODES, codec_settings
from .bili import BILI_CODECS
from .ui import SegmentedControl


class InlineCodecEditor(QWidget):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 6, 0, 6)
        box.setSpacing(10)
        box.addWidget(QLabel('直播源格式'))
        self.source_control = SegmentedControl((('avc', 'H.264'), ('hevc', 'HEVC'), ('av1', 'AV1')), parent=self)
        self.source_control.setAccessibleName('直播源格式')
        self.source_group = self.source_control.group
        self.source_buttons = self.source_control.buttons
        for value, label, _code in BILI_CODECS:
            button = self.source_buttons[value]
            button.setAccessibleName(label)
            button.setToolTip(label)
        box.addWidget(self.source_control)
        self.source_hint = QLabel()
        self.source_hint.setObjectName('SettingsHint')
        self.source_hint.setWordWrap(True)
        box.addWidget(self.source_hint)
        box.addWidget(QLabel('本机解码方式'))
        self.decode_group = QButtonGroup(self)
        self.decode_buttons = {}
        for label, value in DECODE_MODES:
            button = QRadioButton(label)
            self.decode_group.addButton(button)
            self.decode_buttons[value] = button
            box.addWidget(button)
            hint = QLabel(DECODE_HINTS[value])
            hint.setObjectName('SettingsHint')
            hint.setWordWrap(True)
            hint.setContentsMargins(24, 0, 0, 6)
            box.addWidget(hint)
        note = QLabel('作为所有窗口的默认值，保存后生效。\n'
                      'B站未提供所选格式或原画、或探测失败时，保留当前格式。其他平台 AV1 依次尝试 HEVC、H.264；'
                      'HEVC 不可用时回退 H.264。解码异常时回退 CPU。')
        note.setObjectName('SettingsHint')
        note.setWordWrap(True)
        box.addWidget(note)
        self.set_values(codec_settings(settings))
        self.source_group.buttonClicked.connect(self._changed)
        self.decode_group.buttonClicked.connect(self._changed)

    def _update_hint(self):
        value = self.values()['bili_codec']
        self.source_hint.setText(next(label for key, label, _code in BILI_CODECS if key == value))

    def _changed(self, _button):
        self._update_hint()
        self.changed.emit()

    def set_values(self, values):
        self.source_control.setValue(values['bili_codec'])
        self.decode_buttons[values['decode_mode']].setChecked(True)
        self._update_hint()

    def values(self):
        return {key: next(value for value, button in buttons.items() if button.isChecked())
                for key, buttons in (('bili_codec', self.source_buttons), ('decode_mode', self.decode_buttons))}
