"""Inline global codec choices; the owning settings page saves the draft."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from .config import DECODE_HINTS, DECODE_MODES, codec_settings
from .bili import BILI_CODECS
from .ui import SegmentedControl, SelectControl


class InlineCodecEditor(QWidget):
    changed = Signal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        box = QGridLayout(self)
        box.setContentsMargins(0, 6, 0, 6)
        box.setSpacing(10)
        box.setColumnStretch(1, 1)
        box.addWidget(QLabel('直播源格式'), 0, 0)
        self.source_control = SegmentedControl((('avc', 'H.264'), ('hevc', 'HEVC'), ('av1', 'AV1')), parent=self)
        self.source_control.setAccessibleName('直播源格式')
        self.source_group = self.source_control.group
        self.source_buttons = self.source_control.buttons
        for value, label, _code in BILI_CODECS:
            button = self.source_buttons[value]
            button.setAccessibleName(label)
            button.setToolTip(label)
        box.addWidget(self.source_control, 0, 1, Qt.AlignRight)
        self.source_hint = QLabel()
        self.source_hint.setObjectName('SettingsHint')
        self.source_hint.setWordWrap(True)
        box.addWidget(self.source_hint, 1, 0, 1, 2)
        box.addWidget(QLabel('本机解码方式'), 2, 0)
        self.decode_control = SelectControl(self)
        self.decode_control.setAccessibleName('本机解码方式')
        for label, value in DECODE_MODES:
            self.decode_control.addItem(label, value)
        box.addWidget(self.decode_control, 2, 1, Qt.AlignRight)
        self.decode_hint = QLabel()
        self.decode_hint.setObjectName('SettingsHint')
        self.decode_hint.setWordWrap(True)
        box.addWidget(self.decode_hint, 3, 0, 1, 2)
        note = QLabel('作为所有窗口的默认值，修改后自动保存并应用。\n'
                      'B站未提供所选格式或原画、或探测失败时，保留当前格式。其他平台 AV1 依次尝试 HEVC、H.264；'
                      'HEVC 不可用时回退 H.264。解码异常时回退 CPU。')
        note.setObjectName('SettingsHint')
        note.setWordWrap(True)
        box.addWidget(note, 4, 0, 1, 2)
        self.set_values(codec_settings(settings))
        self.source_group.buttonClicked.connect(self._changed)
        self.decode_control.currentIndexChanged.connect(self._changed)

    def _update_hint(self):
        value = self.values()['bili_codec']
        self.source_hint.setText(next(label for key, label, _code in BILI_CODECS if key == value))
        self.decode_hint.setText(DECODE_HINTS[self.decode_control.currentData()])

    def _changed(self, _button):
        self._update_hint()
        self.changed.emit()

    def set_values(self, values):
        self.source_control.setValue(values['bili_codec'])
        self.decode_control.setCurrentIndex(self.decode_control.findData(values['decode_mode']))
        self._update_hint()

    def values(self):
        return {'bili_codec': self.source_control.value(), 'decode_mode': self.decode_control.currentData()}
