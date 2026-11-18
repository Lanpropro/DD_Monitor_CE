"""Toolbar menu for the occupied cells of the current video wall."""
from PySide6.QtCore import QPoint, QRect, QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QMenu, QWidget, QWidgetAction

from .ui import SelectControl, SettingsSlider, SettingsValueLabel, ToggleSwitch
from .wall_quality import WALL_QUALITY_CHOICES, closest_wall_quality


class WallQuickSettingsMenu(QMenu):
    volumeChanged = Signal(int)
    qualityChanged = Signal(int)
    danmakuChanged = Signal(bool)
    floatsChanged = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setAccessibleName('画面墙全局设置')
        self.setAttribute(Qt.WA_NoMouseReplay)
        holder = QWidget(self)
        grid = QGridLayout(holder)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.addWidget(QLabel('整体音量'), 0, 0)
        self.volume = SettingsSlider(holder)
        self.volume.setRange(0, 100)
        self.volume.setAccessibleName('整体音量')
        self.volume_value = SettingsValueLabel()
        self.volume.valueChanged.connect(self._volume_changed)
        self.volume.sliderReleased.connect(lambda: self._volume_changed(self.volume.value()))
        grid.addWidget(self.volume, 0, 1)
        grid.addWidget(self.volume_value, 0, 2)

        grid.addWidget(QLabel('画质'), 1, 0)
        self.quality = SelectControl(holder)
        self.quality.setAccessibleName('画质')
        self.quality.addItem('选择画质')
        self.quality.model().item(0).setEnabled(False)
        for height, label in WALL_QUALITY_CHOICES:
            self.quality.addItem(label, height)
        self.quality.activated.connect(lambda index: self.qualityChanged.emit(self.quality.itemData(index)))
        grid.addWidget(self.quality, 1, 1, 1, 2, Qt.AlignRight)

        self.danmaku_label = QLabel('画面弹幕')
        self.danmaku = ToggleSwitch('画面弹幕', holder)
        self.danmaku.toggled.connect(self.danmakuChanged.emit)
        grid.addWidget(self.danmaku_label, 2, 0, 1, 2)
        grid.addWidget(self.danmaku, 2, 2, Qt.AlignRight)
        self.floats_label = QLabel('弹幕浮窗')
        self.floats = ToggleSwitch('弹幕浮窗', holder)
        self.floats.toggled.connect(self.floatsChanged.emit)
        grid.addWidget(self.floats_label, 3, 0, 1, 2)
        grid.addWidget(self.floats, 3, 2, Qt.AlignRight)

        self.status = QLabel(holder)
        self.status.setObjectName('SettingsHint')
        self.status.setWordWrap(True)
        grid.addWidget(self.status, 4, 0, 1, 3)
        wrapper = QWidgetAction(self)
        wrapper.setDefaultWidget(holder)
        self.addAction(wrapper)

    def _volume_changed(self, value):
        self.volume_value.setText(str(value))
        self.volumeChanged.emit(value)

    def sync(self, tiles, layers, *, missing_floats, has_floats):
        levels = {tile.volume for tile in tiles}
        with QSignalBlocker(self.volume):
            self.volume.setValue(round(sum(tile.volume for tile in tiles) / len(tiles)) if tiles else 0)
        self.volume_value.setText('混合' if len(levels) > 1 else str(self.volume.value()))
        self.volume.setEnabled(bool(tiles))
        self.quality.setEnabled(bool(tiles))
        self.quality.setCurrentIndex(0)
        self.sync_danmaku(layers)
        self.floats.setEnabled(missing_floats or has_floats)
        self.floats_label.setText('弹幕浮窗 · 部分开启' if has_floats and missing_floats else '弹幕浮窗')
        with QSignalBlocker(self.floats):
            self.floats.setChecked(has_floats and not missing_floats)
        self.set_status('当前没有上墙直播间' if not tiles else '')

    def sync_danmaku(self, layers):
        self.danmaku.setEnabled(bool(layers))
        self.danmaku_label.setText('画面弹幕 · 部分开启' if any(layers) and not all(layers) else '画面弹幕')
        with QSignalBlocker(self.danmaku):
            self.danmaku.setChecked(bool(layers) and all(layers))

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def open_at(self, button):
        self.ensurePolished()
        self.adjustSize()
        screen = button.screen().availableGeometry()
        window = button.window()
        frame = QRect(window.mapToGlobal(QPoint()), window.size()).intersected(screen)
        bounds = frame if frame.width() >= self.width() and frame.height() >= self.height() else screen
        anchor = button.mapToGlobal(QPoint())
        if button.property('dockRail'):
            x, y = anchor.x() + button.width() + 7, anchor.y() + button.height() - self.height()
        else:
            x, y = anchor.x(), anchor.y() + button.height() + 7
        point = QPoint(max(bounds.left(), min(x, bounds.right() - self.width() + 1)),
                       max(bounds.top(), min(y, bounds.bottom() - self.height() + 1)))
        self.popup(point)


class WallQuickSettings:
    def __init__(self, host):
        self.host = host
        self.menu = None

    def tiles(self):
        wall = self.host.wall
        if wall.picture_in_picture_tiles is not None:
            return []
        return [tile for tile in wall.visible_tiles() if tile.room.get('room_id')]

    def danmaku_tiles(self):
        return [tile for tile in self.tiles() if tile.room.get('supports_live_danmaku') is not False]

    def floating_rooms(self):
        panes = self.host.wall.pane_danmaku
        return {str(tile.room['room_id']) for panel in panes.floating
                if (tile := panes.target(panel)) is not None}

    def open(self):
        if self.menu is None:
            self.menu = WallQuickSettingsMenu(self.host)
            self.menu.volumeChanged.connect(self.set_volume)
            self.menu.qualityChanged.connect(self.set_quality)
            self.menu.danmakuChanged.connect(self.set_danmaku)
            self.menu.floatsChanged.connect(self.set_floats)
        if self.menu.isVisible():
            self.menu.hide()
            return
        danmaku_tiles = self.danmaku_tiles()
        rooms = {str(tile.room['room_id']) for tile in danmaku_tiles}
        self.menu.sync(self.tiles(), [tile.danmaku_button.isChecked() for tile in danmaku_tiles],
                       missing_floats=bool(rooms - self.floating_rooms()),
                       has_floats=bool(self.host.wall.pane_danmaku.floating))
        self.menu.open_at(self.host.sidebar.wall_settings_button)

    def set_volume(self, value):
        for tile in self.tiles():
            if tile.volume != value or (value > 0 and tile.muted):
                tile.set_volume(value)

    def set_quality(self, height):
        unavailable = 0
        for tile in self.tiles():
            quality = closest_wall_quality(tile, height)
            if quality is None or getattr(tile, 'quality_locked', False) or tile in self.host._capture_quality:
                unavailable += 1
            elif tile.quality != quality:
                tile.set_quality(quality)
        if self.menu is not None:
            self.menu.set_status(f'{unavailable} 路因档位未知或录制锁定保留当前画质' if unavailable else '')

    def set_danmaku(self, enabled):
        tiles = self.danmaku_tiles()
        changed = False
        for tile in tiles:
            if tile.danmaku_button.isChecked() != enabled:
                with QSignalBlocker(tile):
                    tile.danmaku_button.setChecked(enabled)
                changed = True
        if changed:
            self.host._on_video_danmaku_changed(enabled)
        if self.menu is not None:
            self.menu.sync_danmaku([tile.danmaku_button.isChecked() for tile in tiles])

    def set_floats(self, enabled):
        if self.menu is not None:
            self.menu.hide()
        panes = self.host.wall.pane_danmaku
        if enabled:
            opened = self.floating_rooms()
            for tile in self.danmaku_tiles():
                room_id = str(tile.room['room_id'])
                if room_id not in opened:
                    panes.open_for_tile(tile)
                    opened.add(room_id)
        else:
            for panel in tuple(panes.floating):
                panes.return_floating(panel)
