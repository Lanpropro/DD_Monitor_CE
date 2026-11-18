"""Independent settings for rooms explicitly selected by the user."""
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                              QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from .search import matches_text
from .settings_layout import SettingsSection
from .streamer_defaults import QUALITY_LEVELS, room_defaults
from .ui import SelectControl, StepperControl, page_header


class StreamerDefaultsPage(QWidget):
    changed = Signal()

    def __init__(self, settings, rooms):
        super().__init__()
        self.setObjectName('SettingsPage')
        self.rooms = rooms
        saved = settings.get('streamer_defaults')
        self.entries = {}
        if isinstance(saved, dict):
            for room_id, row in saved.items():
                if isinstance(row, dict) and isinstance(room_id, str) and room_id:
                    name = rooms.get(room_id) or row.get('name') or room_id
                    self.entries[room_id] = {'name': str(name), **room_defaults(settings, room_id)}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.addLayout(page_header(
            '主播独立设置', '主播从墙下上墙时，应用该主播的默认画质和音量。在墙上的调整只影响当前观看。'))

        add_section = SettingsSection('添加主播')
        layout.addWidget(add_section)
        self.search = QLineEdit()
        self.search.setObjectName('Search')
        self.search.setPlaceholderText('搜索主播或房间号')
        self.search.setAccessibleName('搜索主播或房间号')
        self.search.setClearButtonEnabled(True)
        add_section.grid.addWidget(self.search, 0, 0, 1, 2)
        self.available = SelectControl()
        self.available.setAccessibleName('选择要添加的主播')
        add_section.grid.addWidget(self.available, 1, 0)
        self.add_button = QPushButton('添加')
        self.add_button.setObjectName('PrimaryButton')
        self.add_button.setAutoDefault(False)
        add_section.grid.addWidget(self.add_button, 1, 1, Qt.AlignRight)
        add_section.grid.setColumnStretch(0, 1)
        add_section.grid.setColumnStretch(1, 0)

        section = SettingsSection('已配置的主播')
        layout.addWidget(section)
        self.configured = SelectControl()
        self.configured.setAccessibleName('已配置的主播')
        self.remove_button = QPushButton('移除设置')
        self.remove_button.setObjectName('IconButton')
        self.remove_button.setAutoDefault(False)
        selected = QHBoxLayout()
        selected.addWidget(self.configured, 1)
        selected.addWidget(self.remove_button, 0, Qt.AlignRight)
        section.grid.addLayout(selected, 0, 0, 1, 2)
        self.playback = SelectControl()
        self.recording = SelectControl()
        self.volume = QSpinBox()
        self.volume.setRange(-1, 100)
        self.volume.setSpecialValueText('继承')
        self.volume.setSuffix('%')
        self.volume.setAccessibleName('默认音量')
        self.volume_stepper = StepperControl(self.volume)
        for control in (self.playback, self.recording):
            control.addItem('继承', None)
            for value, label in QUALITY_LEVELS:
                control.addItem(label, value)
        for row, (label, control) in enumerate(
                (('默认播放画质', self.playback), ('录制画质', self.recording), ('默认音量', self.volume)), 1):
            title = QLabel(label)
            title.setBuddy(control)
            control.setAccessibleName(label)
            section.grid.addWidget(title, row, 0)
            section.grid.addWidget(self.volume_stepper if control is self.volume else control, row, 1)
        self.recording.setToolTip('开始录制时切到指定画质，结束后恢复观看画质。指定档位不可用时提示录制未开始。')
        layout.addStretch(1)

        self.search.textChanged.connect(self._refresh_available)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.configured.currentIndexChanged.connect(self._load)
        self.playback.currentIndexChanged.connect(self._edit)
        self.recording.currentIndexChanged.connect(self._edit)
        self.volume.valueChanged.connect(self._edit)
        self._refresh_configured()

    def _refresh_available(self):
        self.available.clear()
        words = self.search.text().split()
        for room_id, name in self.rooms.items():
            if room_id not in self.entries and all(matches_text(f'{name} {room_id}', word) for word in words):
                self.available.addItem(f'{name}  ·  {room_id}', room_id)
        available = self.available.count() > 0
        self.available.setEnabled(available)
        self.add_button.setEnabled(available)
        if not available:
            self.available.addItem('没有可添加的主播')

    def _refresh_configured(self, room_id=None):
        with QSignalBlocker(self.configured):
            self.configured.clear()
            for key, row in self.entries.items():
                self.configured.addItem(f"{row['name']}  ·  {key}", key)
            if not self.entries:
                self.configured.addItem('尚未配置主播')
            elif room_id in self.entries:
                self.configured.setCurrentIndex(self.configured.findData(room_id))
        self._load()
        self._refresh_available()

    def _load(self):
        row = self.entries.get(self.configured.currentData())
        self.remove_button.setEnabled(row is not None)
        for control, key in ((self.playback, 'playback'), (self.recording, 'recording')):
            with QSignalBlocker(control):
                control.setEnabled(row is not None)
                control.setCurrentIndex(max(0, control.findData((row or {}).get(key))))
        with QSignalBlocker(self):
            self.volume.setValue((row or {}).get('volume', -1))
        self.volume_stepper.setEnabled(row is not None)

    def _add(self):
        room_id = self.available.currentData()
        if room_id is not None:
            self.entries[room_id] = {'name': self.rooms[room_id]}
            self._refresh_configured(room_id)
            self.changed.emit()

    def _remove(self):
        self.entries.pop(self.configured.currentData(), None)
        self._refresh_configured()
        self.changed.emit()

    def _edit(self):
        row = self.entries.get(self.configured.currentData())
        if row is None:
            return
        for key, value in (('playback', self.playback.currentData()),
                           ('recording', self.recording.currentData()),
                           ('volume', self.volume.value() if self.volume.value() >= 0 else None)):
            if value is None:
                row.pop(key, None)
            else:
                row[key] = value
        self.changed.emit()

    def values(self):
        return {'streamer_defaults': {room_id: dict(row) for room_id, row in self.entries.items()}}
