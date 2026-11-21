"""Expandable streamer cards and overlapped, independently selectable avatars."""
from PySide6.QtCore import QRectF, QSignalBlocker, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .room_artwork import platform_icon, room_platform
from .settings_layout import SettingsColumns
from .settings_navigation import _icon as paint_settings_icon
from .streamer_defaults import QUALITY_LABELS
from .ui import Avatar, ElidedLabel, NavigationButton, SelectControl, StepperControl, ToggleSwitch

RECORDING_MODES = (('沿用全局', None), ('普通录制', 'normal'), ('DDCut 切片录制', 'clip'))
RECORDING_MODE_SUMMARY = {None: '全局', 'normal': '普通', 'clip': '切片'}


def quality_label(value):
    if isinstance(value, dict):
        return value['label']
    return QUALITY_LABELS.get(value, '继承')


class _SummaryIcon(QWidget):
    def __init__(self, field, parent):
        super().__init__(parent)
        self.field = field
        self.setFixedSize(16, 16)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.field in ('auto_record', 'windows_notice'):
            color = theme.qcolor(theme.ACCENT if self.isEnabled() else theme.TEXT3)
            paint_settings_icon(painter, 'recording' if self.field == 'auto_record' else 'notifications',
                                QRectF(self.rect()), color)
            return
        color = theme.qcolor(theme.TEXT2)
        painter.setPen(QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.field == 'recording':
            painter.setBrush(color)
            painter.drawEllipse(QRectF(4.2, 4.2, 7.6, 7.6))
            return
        if self.field == 'recording_mode':
            painter.drawRoundedRect(QRectF(3, 5, 10, 8), 1.5, 1.5)
            painter.drawLine(5, 2, 11, 2)
            return
        path = QPainterPath()
        if self.field == 'playback':
            path.moveTo(5, 3)
            path.lineTo(12, 8)
            path.lineTo(5, 13)
            path.closeSubpath()
        else:
            path.moveTo(2.5, 6)
            path.lineTo(5, 6)
            path.lineTo(8, 3.5)
            path.lineTo(8, 12.5)
            path.lineTo(5, 10)
            path.lineTo(2.5, 10)
            path.closeSubpath()
            path.moveTo(10.5, 5)
            path.quadTo(13.5, 8, 10.5, 11)
        painter.drawPath(path)


class StreamerProfileCard(QFrame):
    def __init__(self, page, members, room_id):
        super().__init__()
        self.page, self.members, self.room_id = page, members, room_id
        self.setObjectName('PluginCard')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(8)
        header = QHBoxLayout()
        layout.addLayout(header)
        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.clicked.connect(self._toggle)
        header.addWidget(self.toggle)

        self.avatars = {}
        stack = QWidget()
        size, stride = 34, 23
        width = size + stride * (len(members) - 1)
        stack.setFixedSize(width, size)
        for index, key in enumerate(members):
            room = page.rooms[key]
            button = QPushButton(stack, objectName='StreamerStackAvatar')
            button.setAutoDefault(False)
            button.setCheckable(True)
            button.setFixedSize(size, size)
            button.setStyleSheet('QPushButton {border: 1px solid palette(mid); border-radius: 17px;'
                                 'background: palette(window);} QPushButton:checked, QPushButton:focus '
                                 '{border: 2px solid palette(highlight);}')
            description = ' · '.join(part for part in (room['name'], room.get('platform'), key) if part)
            button.setAccessibleName(description)
            button.setToolTip(description)
            avatar = Avatar(room['name'], index, size=26, parent=button)
            avatar.move(4, 4)
            if room.get('avatar'):
                avatar.set_pixmap_image(QPixmap(room['avatar']))
            if room.get('platform'):
                logo = QLabel(button, objectName='StreamerAvatarPlatform')
                logo.setAttribute(Qt.WA_TransparentForMouseEvents)
                logo.setFixedSize(14, 14)
                logo.setAlignment(Qt.AlignCenter)
                logo.setStyleSheet('background: palette(window); border-radius: 7px;')
                logo.setPixmap(platform_icon(room_platform({'room_id': key})).pixmap(12, 12))
                logo.move(20, 20)
            button.move(stride * index, 0)
            button.clicked.connect(lambda _checked=False, selected=key: self.select(selected))
            self.avatars[key] = button
        if width > 126:
            scroll = QScrollArea()
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFixedSize(126, 46)
            scroll.setWidget(stack)
            header.addWidget(scroll)
        else:
            header.addWidget(stack)
        self.name = ElidedLabel('', self)
        self.name.setTextFormat(Qt.PlainText)
        header.addWidget(self.name, 1)
        self.remove_button = NavigationButton('移除设置', 'clear', self)
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(lambda: page.remove(self.editing_rooms))
        header.addWidget(self.remove_button)
        self.summary = QWidget()
        summary = QHBoxLayout(self.summary)
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(14)
        self.summary_values = {}
        for key, label in (('playback', '播放画质'), ('recording', '录制画质'), ('volume', '音量')):
            metric = QHBoxLayout()
            metric.setSpacing(5)
            metric.addWidget(_SummaryIcon(key, self.summary))
            value = ElidedLabel('', self.summary)
            value.setTextFormat(Qt.PlainText)
            value.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            value.setProperty('summaryLabel', label)
            metric.addWidget(value, 1)
            summary.addLayout(metric, 1)
            self.summary_values[key] = value
        indicators = QHBoxLayout()
        indicators.setSpacing(5)
        self.auto_record_summary = _SummaryIcon('auto_record', self.summary)
        self.windows_notice_summary = _SummaryIcon('windows_notice', self.summary)
        self.mode_summary_icon = _SummaryIcon('recording_mode', self.summary)
        self.mode_summary_value = QLabel(objectName='SettingsHint')
        for indicator in (self.auto_record_summary, self.windows_notice_summary,
                          self.mode_summary_icon, self.mode_summary_value):
            indicators.addWidget(indicator)
        summary.addLayout(indicators)
        layout.addWidget(self.summary)

        self.details = SettingsColumns(self)
        layout.addWidget(self.details)
        playback_options, capture_options = QWidget(), QWidget()
        playback_form, capture_form = QFormLayout(playback_options), QFormLayout(capture_options)
        for form in (playback_form, capture_form):
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(8)
            form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.details.add_section('playback', playback_options)
        self.details.add_section('capture', capture_options)
        self.playback, self.recording = SelectControl(), SelectControl()
        for key, label, control in (('playback', '默认播放画质', self.playback),
                                    ('recording', '录制画质', self.recording)):
            control.setAccessibleName(label)
            control.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH)
            control.currentIndexChanged.connect(
                lambda _index, field=key, widget=control: self._edit_quality(field, widget.currentData()))
            playback_form.addRow(label, control)
        self.volume = QSpinBox()
        self.volume.setAccessibleName('默认音量')
        self.volume.setRange(-1, 100)
        self.volume.setSpecialValueText('继承')
        self.volume.setSuffix('%')
        volume_stepper = StepperControl(self.volume)
        self.volume.valueChanged.connect(self._edit_volume)
        playback_form.addRow('默认音量', volume_stepper)
        self.status = QLabel(objectName='SettingsHint')
        self.status.setWordWrap(True)
        playback_form.addRow(self.status)

        self.auto_record = ToggleSwitch('开播时自动录制')
        self.auto_record.setToolTip('自动录制须开启「设置 → 录制」中的录制功能。')
        self.auto_record.toggled.connect(lambda enabled: page.edit(
            'auto_record', dict.fromkeys(self.editing_rooms, True if enabled else None)))
        capture_form.addRow('开播时自动录制', self.auto_record)
        self.auto_record_mode = None
        if page.clip_recording_available:
            self.auto_record_mode = SelectControl()
            self.auto_record_mode.setAccessibleName('自动录制方式')
            self.auto_record_mode.setAccessibleDescription('普通录制保存到本体录制目录，切片录制使用 DDCut 切片设置。')
            for label, mode in RECORDING_MODES:
                self.auto_record_mode.addItem(label, mode)
            self.auto_record_mode.currentIndexChanged.connect(lambda _index: page.edit(
                'auto_record_mode', dict.fromkeys(self.editing_rooms, self.auto_record_mode.currentData())))
            capture_form.addRow('自动录制方式', self.auto_record_mode)
        self.windows_notice = ToggleSwitch('使用 Windows 通知')
        self.windows_notice.toggled.connect(lambda enabled: page.edit(
            'windows_recording_notice', dict.fromkeys(self.editing_rooms, True if enabled else None)))
        capture_form.addRow('使用 Windows 通知', self.windows_notice)
        self.windows_notice_hint = QLabel('请先在「设置 → 通知」开启 Windows 通知。', objectName='SettingsHint')
        self.windows_notice_hint.setWordWrap(True)
        capture_form.addRow(self.windows_notice_hint)
        self._loading = False
        self.load()

    @property
    def editing_rooms(self):
        return self.members if self.room_id is None else (self.room_id,)

    def _edit_volume(self, value):
        if not self._loading:
            self.page.edit('volume', dict.fromkeys(self.editing_rooms, None if value < 0 else value))

    def _edit_quality(self, field, values):
        self.page.edit(field, values if values is not None else dict.fromkeys(self.editing_rooms))

    def _request_quality(self):
        for room_id in self.editing_rooms:
            self.page.request_quality(room_id)

    def _toggle(self):
        self.page.set_expanded(self.editing_rooms, self.details.isHidden())
        self.sync_expanded()

    def select(self, room_id):
        if len(self.members) > 1 and self.room_id == room_id:
            room_id = None
        self.room_id = room_id
        self.page.set_expanded(self.editing_rooms, True)
        self.load()

    def load(self):
        for key, avatar in self.avatars.items():
            avatar.setChecked(key == self.room_id)
            if key == self.room_id:
                avatar.raise_()
        if self.room_id is None:
            name = f'编辑整组 · {len(self.members)} 位主播'
        else:
            room = self.page.rooms[self.room_id]
            name = ' · '.join(part for part in (room['name'], room.get('platform')) if part)
        self.name.setText(name)
        self.name.setToolTip(name)
        self.remove_button.setToolTip('移除合并卡片中所有主播的设置' if self.room_id is None else '移除该主播的独立设置')
        self._loading = True
        self.volume.setValue(self.page.entries[self.editing_rooms[0]].get('volume', -1))
        self._loading = False
        self.update_summary()
        self.sync_expanded()

    def sync_expanded(self):
        expanded = any(room_id in self.page.expanded for room_id in self.editing_rooms)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setAccessibleName('收起主播设置' if expanded else '展开主播设置')
        self.details.setVisible(expanded)
        self.summary.setVisible(not expanded)
        if expanded:
            self._request_quality()
        self.update_quality()

    def update_summary(self):
        values = self.page.entries[self.editing_rooms[0]]
        auto_record = bool(values.get('auto_record'))
        windows_notice = bool(values.get('windows_recording_notice'))
        windows_available = self.page.windows_notice_available
        mode = values.get('auto_record_mode')
        with QSignalBlocker(self.auto_record):
            self.auto_record.setChecked(auto_record)
        with QSignalBlocker(self.windows_notice):
            self.windows_notice.setChecked(windows_notice)
        self.windows_notice.setEnabled(windows_available)
        self.windows_notice.setAccessibleDescription('提示自动开录和下播收尾。' if windows_available
                                                     else self.windows_notice_hint.text())
        self.windows_notice_hint.setVisible(not windows_available)
        if self.auto_record_mode is not None:
            with QSignalBlocker(self.auto_record_mode):
                self.auto_record_mode.setCurrentIndex(0 if mode is None else self.auto_record_mode.findData(mode))
        self.auto_record_summary.setVisible(auto_record)
        self.windows_notice_summary.setVisible(windows_notice)
        self.windows_notice_summary.setEnabled(windows_available)
        show_mode = self.auto_record_mode is not None or mode is not None
        self.mode_summary_icon.setVisible(show_mode)
        self.mode_summary_value.setVisible(show_mode)
        self.mode_summary_value.setText(RECORDING_MODE_SUMMARY[mode])
        mode_hint = next(label for label, value in RECORDING_MODES if value == mode)
        for indicator, hint in (
                (self.auto_record_summary, '已开启自动录制'),
                (self.windows_notice_summary, '已开启该主播的 Windows 通知' if windows_available
                 else 'Windows 通知暂停 · 通知页总开关已关闭'),
                (self.mode_summary_icon, f'自动录制方式 · {mode_hint}'),
                (self.mode_summary_value, f'自动录制方式 · {mode_hint}')):
            indicator.setAccessibleName(hint)
            indicator.setToolTip(hint)
        for key, view in self.summary_values.items():
            if key == 'volume':
                value = f"{values['volume']}%" if 'volume' in values else '继承'
            else:
                value = quality_label(values.get(key))
            hint = f"{view.property('summaryLabel')} · {value}"
            view.setText(value)
            view.setAccessibleName(hint)
            view.setToolTip(hint)

    def update_quality(self):
        rooms = self.editing_rooms
        pending = any(room_id in self.page.requests for room_id in rooms)
        catalogs = {room_id: self.page.qualities.get(room_id, ([], '')) for room_id in rooms}
        available = False
        highest = QUALITY_LABELS[0]
        for key, control in (('playback', self.playback), ('recording', self.recording)):
            selected = {room_id: self.page.entries[room_id].get(key) for room_id in rooms}
            saved = selected[rooms[0]]
            with QSignalBlocker(control):
                control.clear()
                control.addItem('继承', None)
                control.addItem(highest, dict.fromkeys(rooms, 0))
                index = 1 if all(value == 0 for value in selected.values()) else 0
                for label, choices in self._quality_choices(key, catalogs):
                    available = True
                    control.addItem(f'{label}（平台）' if label == highest else label, choices)
                    if all(isinstance(selected[room_id], dict)
                           and selected[room_id]['qn'] == choice['qn'] for room_id, choice in choices.items()):
                        index = control.count() - 1
                if saved is not None and index == 0:
                    control.addItem(f'{quality_label(saved)}（已保存）', selected)
                    index = control.count() - 1
                control.setCurrentIndex(index)
        error = next((error for _choices, error in catalogs.values() if error), '')
        empty = '暂无共同平台档位，可点击头像查看各主播画质。' if self.room_id is None else '暂无平台档位。'
        message = '正在读取平台画质…' if pending else error or ('' if available else empty)
        self.status.setText(message)
        self.status.setVisible(bool(message))

    def _quality_choices(self, field, catalogs):
        options = {room_id: [choice for choice in choices if field != 'recording' or choice['qn'] != -1]
                   for room_id, (choices, _) in catalogs.items()}
        first = self.editing_rooms[0]
        if self.room_id is not None:
            return [(choice['label'], {first: choice}) for choice in options[first]]
        by_label = {}
        for room_id, choices in options.items():
            labels = by_label[room_id] = {}
            for choice in choices:
                labels.setdefault(choice['label'].strip().casefold(), choice)
        return [(choice['label'], {room_id: labels[key] for room_id, labels in by_label.items()})
                for key, choice in by_label[first].items()
                if all(key in labels for labels in by_label.values())]
