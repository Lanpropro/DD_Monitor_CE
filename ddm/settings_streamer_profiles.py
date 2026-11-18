"""Expandable streamer cards and overlapped, independently selectable avatars."""
from PySide6.QtCore import QRectF, QSignalBlocker, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .room_artwork import platform_icon, room_platform
from .streamer_defaults import QUALITY_LABELS
from .ui import Avatar, ElidedLabel, SelectControl, StepperControl


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
        painter.setPen(QPen(theme.qcolor(theme.TEXT2), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if self.field == 'recording':
            painter.setBrush(theme.qcolor(theme.TEXT2))
            painter.drawEllipse(QRectF(4.2, 4.2, 7.6, 7.6))
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
        layout.addWidget(self.summary)

        self.details = QWidget()
        layout.addWidget(self.details)
        form = QFormLayout(self.details)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.playback, self.recording = SelectControl(), SelectControl()
        for key, label, control in (('playback', '默认播放画质', self.playback),
                                    ('recording', '录制画质', self.recording)):
            control.setAccessibleName(label)
            control.setMaximumWidth(285)
            control.currentIndexChanged.connect(
                lambda _index, field=key, widget=control: self.page.edit(self.room_id, field, widget.currentData()))
            form.addRow(label, control)
        self.volume = QSpinBox()
        self.volume.setAccessibleName('默认音量')
        self.volume.setRange(-1, 100)
        self.volume.setSpecialValueText('继承')
        self.volume.setSuffix('%')
        volume_stepper = StepperControl(self.volume)
        self.volume.valueChanged.connect(self._edit_volume)
        form.addRow('默认音量', volume_stepper)
        actions = QHBoxLayout()
        self.status = QLabel(objectName='SettingsHint')
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        self.refresh_button = QPushButton('刷新画质', objectName='IconButton')
        self.refresh_button.setAutoDefault(False)
        self.refresh_button.clicked.connect(lambda: page.request_quality(self.room_id, refresh=True))
        actions.addWidget(self.refresh_button)
        self.remove_button = QPushButton('移除设置', objectName='IconButton')
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(lambda: page.remove(self.room_id))
        actions.addWidget(self.remove_button)
        form.addRow(actions)
        self._loading = False
        self.load()

    def _edit_volume(self, value):
        if not self._loading:
            self.page.edit(self.room_id, 'volume', None if value < 0 else value)

    def _toggle(self):
        self.page.set_expanded(self.room_id, not self.details.isVisibleTo(self))
        self.sync_expanded()

    def select(self, room_id):
        self.room_id = room_id
        self.page.set_expanded(room_id, True)
        self.load()

    def load(self):
        for key, avatar in self.avatars.items():
            avatar.setChecked(key == self.room_id)
            if key == self.room_id:
                avatar.raise_()
        room = self.page.rooms[self.room_id]
        name = ' · '.join(part for part in (room['name'], room.get('platform')) if part)
        self.name.setText(name + (f'  ·  {len(self.members)} 位' if len(self.members) > 1 else ''))
        self.name.setToolTip(name)
        self._loading = True
        self.volume.setValue(self.page.entries[self.room_id].get('volume', -1))
        self._loading = False
        self.update_summary()
        self.sync_expanded()

    def sync_expanded(self):
        expanded = self.room_id in self.page.expanded
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.toggle.setAccessibleName('收起主播设置' if expanded else '展开主播设置')
        self.details.setVisible(expanded)
        self.summary.setVisible(not expanded)
        if expanded:
            self.page.request_quality(self.room_id)
        self.update_quality()

    def update_summary(self):
        values = self.page.entries[self.room_id]
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
        options, error = self.page.qualities.get(self.room_id, ([], ''))
        pending = self.room_id in self.page.requests
        self.status.setText('正在读取平台画质…' if pending else
                            error or ('' if options else '暂无可用画质，直播开始后可刷新'))
        self.refresh_button.setEnabled(not pending)
        for key, control in (('playback', self.playback), ('recording', self.recording)):
            selected = self.page.entries[self.room_id].get(key)
            with QSignalBlocker(control):
                control.clear()
                control.addItem('继承', None)
                index = 0
                for choice in options:
                    if key == 'recording' and choice['qn'] == -1:
                        continue
                    control.addItem(choice['label'], choice)
                    if isinstance(selected, dict) and selected['qn'] == choice['qn']:
                        index = control.count() - 1
                if selected is not None and index == 0:
                    control.addItem(f'{quality_label(selected)}（已保存）', selected)
                    index = control.count() - 1
                control.setCurrentIndex(index)
                control.setEnabled(not pending and control.count() > 1)
