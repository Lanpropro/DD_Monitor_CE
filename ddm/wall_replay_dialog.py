"""Select replay sources directly on a schematic of the current wall."""

import math

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from . import images, theme
from .corner_geometry import continuous_path
from .pip_placement import fit_placement
from .room_choice import PreviewAvatar
from .settings_window import SettingsTitleBar
from .ui import ActionButton, ElidedLabel, StepperControl, ToggleSwitch, page_header
from .wall_replay_settings import DEFAULT_MINUTES, MAX_MINUTES


FALLBACK_MBPS = 6


def _disk_size(megabytes):
    if megabytes >= 1000:
        return f'{megabytes / 1000:.2f}'.rstrip('0').rstrip('.') + ' GB'
    return f'{megabytes:.1f}'.rstrip('0').rstrip('.') + ' MB'


class ReplayPaneChoice(QPushButton):
    def __init__(self, name, parent, *, available, portrait=None):
        super().__init__(parent, objectName='PipRoomChoice')
        self.setAutoDefault(False)
        self.setCheckable(available)
        self.setEnabled(available)
        if available:
            self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)
        self.setAccessibleName(name)
        self.label = ElidedLabel(name if portrait is None else '', self)
        self.label.setTextFormat(Qt.PlainText)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.avatar = PreviewAvatar(*portrait, self) if portrait is not None else None
        self.badge = QLabel('✓', self, objectName='PipChoiceBadge')
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedSize(16, 16)
        self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.toggled.connect(self._arrange)
        self._arrange()

    def _arrange(self):
        show_badge = self.isChecked() and self.width() >= 42 and self.height() >= 22
        self.badge.setVisible(show_badge)
        self.badge.move(self.width() - 19, 3)
        self.label.setGeometry(self.rect().adjusted(4, 0, -22 if show_badge else -4, 0))
        if self.avatar is not None:
            self.avatar.center_in(self.rect())
            self.badge.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()


class ReplayWallPreview(QFrame):
    def __init__(self, parent):
        super().__init__(parent, objectName='PluginCard')
        self.setFixedHeight(166)
        self.setAccessibleName('当前画面墙布局')
        self.cells = []

    def add_cell(self, text, rect, *, available=False, portrait=None):
        button = ReplayPaneChoice(text, self, available=available, portrait=portrait)
        self.cells.append((button, rect.getRect()))
        return button

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.cells:
            area = self.rect().adjusted(8, 8, -8, -8)
            if area.isValid():
                boxes, _scale = fit_placement([rect for _button, rect in self.cells], area)
                for (button, _rect), box in zip(self.cells, boxes):
                    button.setGeometry(box)


class ReplaySelection(QDialog):
    COMPACT_SIZE = QSize(424, 500)

    def __init__(self, parent, rooms, selected, durations, *, individual, shared_minutes):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowTitle('直播回放')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('customControlSurface', True)
        self.resize(self.COMPACT_SIZE)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        self.titlebar = SettingsTitleBar(self)
        self.titlebar.setMinimumHeight(42)
        row = self.titlebar.row
        row.setContentsMargins(0, 0, 0, 0)
        self.titlebar.breadcrumb.hide()
        row.takeAt(1)
        row.insertLayout(0, page_header('直播回放', '点击布局中的直播格，选择要缓存的直播。'), 1)
        close = self.titlebar.close_button
        close.setAccessibleName('关闭直播回放')
        close.setToolTip('关闭直播回放')
        row.setAlignment(close, Qt.AlignTop)
        outer.addWidget(self.titlebar)

        scroll = QScrollArea(self, widgetResizable=True, objectName='ReplayToolbarViewport')
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumHeight(48)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('#ReplayToolbarViewport { background: transparent; border: none; }')
        scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        outer.addWidget(scroll, 1)

        self.checks = {}
        self.preview = ReplayWallPreview(self)
        faces = {str(item.room.get('room_id')): item.thumb.face_pixmap() for item in parent.sidebar.items()}
        self._add_wall_cells(parent.wall, rooms, selected, faces)
        if self.preview.cells:
            outer.insertWidget(1, self.preview)
        else:
            self.preview.hide()
        if not rooms:
            layout.addWidget(QLabel('当前画面墙没有可缓存的直播', body, objectName='SettingsHint'))
        hidden = rooms.keys() - self.checks.keys()
        if hidden:
            layout.addWidget(QLabel('当前布局外', body, objectName='SectionLabel'))
            grid = QGridLayout()
            for index, room_id in enumerate(key for key in rooms if key in hidden):
                name = str(rooms[room_id].room.get('uname') or room_id)
                face = faces.get(room_id) or images.load_room_avatar(room_id)
                button = ReplayPaneChoice(name, body, available=True, portrait=(name, index, face))
                button.setMinimumHeight(32)
                button.setChecked(room_id in selected)
                self.checks[room_id] = button
                grid.addWidget(button, index // 2, index % 2)
            layout.addLayout(grid)

        self.minutes = {}
        self._rooms = rooms
        self._rates = {}
        self.estimates = {}
        self.total_estimate = QLabel(self, wordWrap=True, objectName='SettingsHint')
        options = QHBoxLayout()
        options.addWidget(QLabel('缓存时长（分钟）', body, objectName='SectionLabel'), 1)
        individual_label = QLabel('逐路设置', body)
        self.individual = ToggleSwitch('按主播逐路设置缓存时长', body)
        self.individual.setChecked(individual)
        individual_label.setBuddy(self.individual)
        options.addWidget(individual_label)
        options.addWidget(self.individual)
        layout.addLayout(options)

        shared_row = QWidget(body)
        shared = QHBoxLayout(shared_row)
        shared.setContentsMargins(0, 0, 0, 0)
        shared_label = QLabel('统一时长', shared_row)
        self.shared_minutes = QSpinBox(shared_row)
        self.shared_minutes.setRange(1, MAX_MINUTES)
        self.shared_minutes.setValue(shared_minutes)
        self.shared_minutes.setAccessibleName('统一缓存时长（分钟）')
        shared_label.setBuddy(self.shared_minutes)
        shared.addWidget(shared_label, 1)
        shared.addWidget(StepperControl(self.shared_minutes))
        layout.addWidget(shared_row)
        shared_row.setVisible(not individual)
        self.individual.toggled.connect(lambda checked: shared_row.setVisible(not checked))
        for room_id, button in self.checks.items():
            name = str(rooms[room_id].room.get('uname') or room_id)
            row_widget = QWidget(body)
            duration = QHBoxLayout(row_widget)
            duration.setContentsMargins(0, 0, 0, 0)
            text = ElidedLabel(name, row_widget)
            text.setTextFormat(Qt.PlainText)
            spin = QSpinBox(row_widget)
            spin.setRange(1, MAX_MINUTES)
            spin.setValue(durations.get(room_id, DEFAULT_MINUTES))
            spin.setAccessibleName(f'{name} 的缓存时长（分钟）')
            text.setBuddy(spin)
            detail = QVBoxLayout()
            detail.setSpacing(2)
            detail.addWidget(text)
            estimate = QLabel(row_widget, objectName='SettingsHint')
            detail.addWidget(estimate)
            duration.addLayout(detail, 1)
            stepper = StepperControl(spin)
            duration.addWidget(stepper)
            stepper.setVisible(individual)
            self.individual.toggled.connect(stepper.setVisible)
            self.minutes[room_id] = spin
            self.estimates[room_id] = estimate
            layout.addWidget(row_widget)
            row_widget.setVisible(button.isChecked())
            button.toggled.connect(row_widget.setVisible)
            button.toggled.connect(self._update_estimates)
            spin.valueChanged.connect(self._update_estimates)
        self.shared_minutes.valueChanged.connect(self._update_estimates)
        self.individual.toggled.connect(self._update_estimates)
        hint = QLabel('确认后每路会额外拉取一个直播流用于缓存。点击直播格控制栏的回放图标打开时间轴，'
                      '取消勾选或下墙会清理缓存。',
                      wordWrap=True, objectName='SettingsHint')
        layout.addWidget(hint)

        outer.addWidget(self.total_estimate)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('拖动边缘调整大小', self, objectName='SettingsHint'))
        controls.addStretch()
        cancel = ActionButton('取消', self)
        self.confirm = ActionButton('确认', self)
        self.confirm.setObjectName('PrimaryButton')
        self.confirm.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.confirm.clicked.connect(self.accept)
        controls.addWidget(cancel)
        controls.addWidget(self.confirm)
        outer.addLayout(controls)
        self._update_estimates()

    def _update_estimates(self):
        selected = self.selected_durations()
        total = 0
        fallback_count = 0
        for room_id, minutes in selected.items():
            if room_id not in self._rates:
                player = self.parentWidget().players.get(self._rooms[room_id])
                info = player.stream_info() if player is not None else {}
                video, audio = (info.get(key) for key in ('video_bitrate', 'audio_bitrate'))
                video = video if isinstance(video, (int, float)) and math.isfinite(video) and video > 0 else 0
                audio = audio if isinstance(audio, (int, float)) and math.isfinite(audio) and audio > 0 else 0
                self._rates[room_id] = ((video + audio) / 1_000_000 if video else FALLBACK_MBPS, not video)
            mbps, fallback = self._rates[room_id]
            megabytes = mbps * minutes * 60 / 8
            self.estimates[room_id].setText(f'约 {_disk_size(megabytes)}')
            total += megabytes
            fallback_count += fallback
        note = (f' · {"部分直播" if fallback_count < len(selected) else "每路"}按 {FALLBACK_MBPS} Mbps 估算'
                if fallback_count else '')
        self.total_estimate.setText(f'缓存存满预计占用 {_disk_size(total)}{note}')

    def _add_wall_cells(self, wall, rooms, selected, faces):
        for index, tile in enumerate(wall.tiles, 1):
            if tile.isHidden() or tile.property('pictureInPictureTemporary'):
                continue
            rect = QRect(tile.mapTo(wall, QPoint()), tile.size()).intersected(wall.rect())
            if rect.isEmpty():
                continue
            room_id = str(tile.room.get('room_id') or '')
            name = str(tile.room.get('uname') or room_id or '空格')
            available = rooms.get(room_id) is tile
            portrait = (name, index, faces.get(room_id) or images.load_room_avatar(room_id)) if room_id else None
            button = self.preview.add_cell(f'{index} · {name}', rect, available=available, portrait=portrait)
            if available:
                button.setChecked(room_id in selected)
                self.checks[room_id] = button
        for pane in wall.pane_danmaku.wall_widgets():
            if not pane.isHidden() and wall.isAncestorOf(pane):
                rect = QRect(pane.mapTo(wall, QPoint()), pane.size()).intersected(wall.rect())
                if not rect.isEmpty():
                    self.preview.add_cell('弹幕', rect)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 22)
        painter.fillPath(path, theme.qcolor(theme.BG))
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.drawPath(path)

    def selected_rooms(self):
        return tuple(room_id for room_id, check in self.checks.items() if check.isChecked())

    def selected_durations(self):
        if self.individual.isChecked():
            return {room_id: self.minutes[room_id].value() for room_id in self.selected_rooms()}
        return dict.fromkeys(self.selected_rooms(), self.shared_minutes.value())
