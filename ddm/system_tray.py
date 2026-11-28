"""System tray controls and the remembered window-close choice."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QMenu, QPushButton,
    QStyle, QSystemTrayIcon, QVBoxLayout, QWidgetAction,
)

from . import config, theme, version
from .window_chrome import install_window_chrome


class CloseWindowDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关闭窗口后，你希望程序如何运行？")
        title_bar = install_window_chrome(self)
        title_bar.breadcrumb.setObjectName('SettingsTitle')
        title_bar.row.setContentsMargins(24, 4, 8, 4)
        self.setMinimumWidth(max(420, title_bar.breadcrumb.sizeHint().width() + 78))
        self.choice = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 6, 24, 20)
        layout.setSpacing(18)
        detail = QLabel("隐藏后的播放行为可在设置 → 托盘行为中调整，录制会继续运行。双击托盘图标可恢复窗口。")
        detail.setWordWrap(True)
        detail.setObjectName("NavSub")
        layout.addWidget(detail)
        buttons = QHBoxLayout()
        self.remember = QCheckBox("记住我的选择")
        buttons.addWidget(self.remember)
        buttons.addStretch(1)
        self.hide_button = QPushButton("隐藏到托盘")
        self.hide_button.setObjectName("PrimaryButton")
        self.hide_button.setDefault(True)
        self.hide_button.clicked.connect(self.choose_tray)
        self.exit_button = QPushButton("退出程序")
        self.exit_button.setObjectName("IconButton")
        self.exit_button.clicked.connect(self.choose_exit)
        for button in (self.hide_button, self.exit_button):
            button.setFixedHeight(theme.CONTROL_HEIGHT + 2)
        buttons.addWidget(self.hide_button)
        buttons.addWidget(self.exit_button)
        layout.addLayout(buttons)

    def choose_tray(self):
        self.choice = "tray"
        self.accept()

    def choose_exit(self):
        self.choice = "exit"
        self.accept()


class SystemTray(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.icon = None
        self.monitor_panel = None
        self.exit_requested = False
        self.playback_suspended = False
        self._saved_playback = {}
        self._pip_resumed = set()
        self._layout_snapshot = None
        self._preview_audio_key = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.icon = QSystemTrayIcon(self._window_tray_icon(), window)
        self.icon.setToolTip(f"{version.DISPLAY_NAME}：双击显示或隐藏窗口")
        self.menu = QMenu(window)
        from .tray_preview import TrayLayoutPreview, TrayPreviewAudio
        self.layout_preview = TrayLayoutPreview(self.menu)
        self.layout_preview.clicked.connect(self._restore_from_preview)
        self.layout_preview.paneSelected.connect(self._select_preview_audio)
        self.preview_action = QWidgetAction(self.menu)
        self.preview_action.setDefaultWidget(self.layout_preview)
        self.menu.addAction(self.preview_action)
        self.preview_audio = TrayPreviewAudio(self.menu)
        self.preview_audio.volumeChanged.connect(self._set_preview_volume)
        self.preview_audio.muteChanged.connect(self._set_preview_mute)
        self.audio_action = QWidgetAction(self.menu)
        self.audio_action.setDefaultWidget(self.preview_audio)
        self.audio_action.setVisible(False)
        from .tray_monitor_overview import TrayMonitorOverview
        self.monitor_panel = TrayMonitorOverview(self.menu)
        self.monitor_panel.read_rows = window.capture_control.monitor_rows
        self.monitor_action = QWidgetAction(self.menu)
        self.monitor_action.setDefaultWidget(self.monitor_panel)
        self.monitor_action.setEnabled(False)
        self.monitor_action.setVisible(False)
        self.menu.addAction(self.monitor_action)
        self.toggle_action = self.menu.addAction("显示/隐藏窗口", self.toggle)
        self.layout_pip_action = self.menu.addAction("当前布局画中画", self.open_layout_picture_in_picture)
        self.pip_action = self.menu.addAction("画中画…", self.open_picture_in_picture)
        self.exit_action = self.menu.addAction("退出", self.request_exit)
        self.menu_actions = dict(layout_preview=self.preview_action, streamer_monitor=self.monitor_action,
                                 toggle=self.toggle_action, layout_pip=self.layout_pip_action,
                                 pip=self.pip_action, exit=self.exit_action)
        self.menu_separators = [QAction(self.menu) for _ in range(len(self.menu_actions) - 1)]
        for separator in self.menu_separators:
            separator.setSeparator(True)
        self.menu.aboutToShow.connect(self.update_menu)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self.activate)
        self.icon.messageClicked.connect(self.restore)
        window.installEventFilter(self)
        self.icon.show()

    def available(self):
        return bool(self.icon is not None and self.icon.isVisible()
                    and QSystemTrayIcon.isSystemTrayAvailable())

    def update_menu(self):
        self.toggle_action.setText("隐藏窗口" if self.window.isVisible()
                                   and not self.window.isMinimized() else "显示窗口")
        pip = self.window.picture_in_picture
        self.pip_action.setText('管理画中画…' if pip.active else '画中画…')
        self.pip_action.setEnabled(not self.window._closing)
        if self._layout_snapshot is None or (self.window.isVisible()
                and not self.window.isMinimized() and not pip.active):
            self.remember_layout()
        rooms = {pane['room_id'] for pane in (self._layout_snapshot or {}).get('panes', ()) if 'room_id' in pane}
        self.layout_preview.avatars = {
            room_id: item.thumb.face_pixmap() for item in self.window.sidebar.items()
            if (room_id := str(item.room.get('room_id') or '')) in rooms
        } if rooms else {}
        tiles = self._preview_tiles()
        from .images import load_cached_avatar
        for _, tile in tiles.values():
            room_id, face = str(tile.room['room_id']), tile.room.get('face')
            if face and self.layout_preview.avatars.get(room_id) is None:
                self.layout_preview.avatars[room_id] = load_cached_avatar(face)
        self.layout_preview.set_snapshot(self._layout_snapshot)
        self._arrange_menu()
        self.layout_pip_action.setEnabled(bool(tiles) and not pip.active and not self.window._closing)
        self._sync_preview_audio(tiles)
        if self.monitor_action.isVisible():
            # QMenu disables the widget when adding a disabled action. Keep its scrollbar usable.
            self.monitor_panel.setEnabled(True)
            self.monitor_panel.refresh()

    def _arrange_menu(self):
        from .tray_menu import tray_menu_choices
        for action in self.menu.actions():
            self.menu.removeAction(action)
        groups = dict(layout_preview=0, streamer_monitor=0, toggle=1, layout_pip=1, pip=1, exit=2)
        previous, separator_index = None, 0
        for entry in tray_menu_choices(self.window.settings.get('tray_context_menu')):
            key = entry['id']
            action = self.menu_actions[key]
            action.setVisible(entry['enabled'])
            if entry['enabled']:
                if previous is not None and groups[key] != previous:
                    self.menu.addAction(self.menu_separators[separator_index])
                    separator_index += 1
                previous = groups[key]
            self.menu.addAction(action)
            if key == 'layout_preview':
                self.menu.addAction(self.audio_action)

    def _preview_tiles(self):
        panes = (self._layout_snapshot or {}).get('panes', ())
        if not any('tile_key' in pane for pane in panes):
            return {}
        wall = self.window.wall
        bound = wall.pane_danmaku.bindings()
        chat_tiles = {tile for cell, tile in wall.pane_danmaku.cell_tiles().items() if cell in bound}
        tiles = {id(tile): (index, tile) for index, tile in enumerate(wall.tiles)
                 if tile.room.get('room_id') and tile not in chat_tiles
                 and not tile.property('pictureInPictureTemporary')}
        result = {}
        for index, pane in enumerate(panes):
            match = tiles.get(pane.get('tile_key'))
            if match is not None and str(match[1].room['room_id']) == pane['room_id']:
                result[index] = match
        return result

    def _sync_preview_audio(self, tiles):
        enabled = self.preview_action.isVisible() and self.window.settings.get('tray_preview_audio', False)
        available = tiles if enabled else {}
        selected = next((index for index, (_, tile) in available.items()
                         if id(tile) == self._preview_audio_key), next(iter(available), None))
        self.audio_action.setVisible(selected is not None)
        self.layout_preview.set_audio_selection(available, selected)
        if selected is not None:
            _, tile = available[selected]
            self._preview_audio_key = id(tile)
            self.preview_audio.setEnabled(True)
            self.preview_audio.sync(tile)

    def _select_preview_audio(self, index):
        tiles = self._preview_tiles()
        if index in tiles:
            self._preview_audio_key = id(tiles[index][1])
        self._sync_preview_audio(tiles)

    def _preview_audio_tile(self):
        if self.audio_action.isVisible() and not self.window._closing:
            match = self._preview_tiles().get(self.layout_preview.selected)
            if match is not None and id(match[1]) == self._preview_audio_key:
                return match[1]
        return None

    def _set_preview_volume(self, value):
        if (tile := self._preview_audio_tile()) is not None:
            tile.set_volume(value)
            self.preview_audio.sync(tile)
        else:
            self.preview_audio.setEnabled(False)

    def _set_preview_mute(self, muted):
        if (tile := self._preview_audio_tile()) is not None:
            tile.set_muted(muted)
            self.preview_audio.sync(tile)
        else:
            self.preview_audio.setEnabled(False)

    def remember_layout(self):
        if not self.window.picture_in_picture.active:
            from .tray_preview import capture_layout
            self._layout_snapshot = capture_layout(self.window.wall)

    def _window_tray_icon(self):
        icon = self.window.windowIcon()
        if icon.isNull():
            return self.window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        return icon

    def eventFilter(self, watched, event):
        if watched is self.window:
            if event.type() == QEvent.WindowStateChange and self.window.isMinimized():
                self.remember_layout()
            elif event.type() == QEvent.WindowIconChange and self.icon is not None:
                self.icon.setIcon(self._window_tray_icon())
        return False

    def _restore_from_preview(self):
        self.menu.hide()
        if self.window.picture_in_picture.active:
            self.window.picture_in_picture.restore(activate=True)
        else:
            self.restore()

    def open_picture_in_picture(self):
        if not self.window._closing:
            self.window.picture_in_picture.manage()

    def open_layout_picture_in_picture(self):
        pip = self.window.picture_in_picture
        if pip.active or self.window._closing:
            return
        tiles = self._preview_tiles()
        if not tiles:
            return
        from .pip_composition import FREE_LAYOUT
        panes = self._layout_snapshot['panes']
        width, height = self._layout_snapshot['size']
        selection, placement = [], []
        for pane, (index, _) in tiles.items():
            x, y, w, h = panes[pane]['rect']
            left, top = round(x * width), round(y * height)
            selection.append(index)
            placement.append((left, top, round((x + w) * width) - left, round((y + h) * height) - top))
        self.menu.hide()
        pip.start(selection, FREE_LAYOUT, self.window.wall.main_index(), placement=placement)

    def sync_picture_in_picture(self):
        """Resume selected panes only while the remaining hidden wall stays held."""
        if not self.playback_suspended:
            return
        host = self.window
        pip_tiles = host.wall.picture_in_picture_tiles or []
        for tile in host.wall.tiles:
            if tile in pip_tiles:
                if tile in self._pip_resumed:
                    continue
                saved = self._saved_playback.get(tile)
                if saved is not None and saved[0] == str(tile.room.get('room_id') or ''):
                    self._pip_resumed.add(tile)
                    tile.set_paused(saved[1])
                    if (not saved[1] and tile.room.get('live') and tile not in host.players
                            and tile not in host._resolvers):
                        host.start_tile(tile)
            elif self.hold_playback(tile):
                host._stop_tile(tile)

    def activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle()

    def toggle(self):
        if self.window.isVisible() and not self.window.isMinimized():
            self.hide()
        else:
            self.restore()

    def hide(self):
        if self.icon is None or not self.available() or self.window._closing:
            return
        self.remember_layout()
        self.window.hover_preview.stop()
        self.window._fullscreen_cursor.stop()
        pip = getattr(self.window, 'picture_in_picture', None)
        if (not self.playback_suspended and self.window.settings.get("tray_pause_playback", True)
                and not (pip is not None and pip.moves_main_wall)):
            self.playback_suspended = True
            for tile in self.window.wall.tiles:
                if self.hold_playback(tile):
                    self.window._stop_tile(tile)
        self.window.hide()
        if not self.window._tray_hint_shown:
            self.window._tray_hint_shown = True
            self.icon.showMessage(version.DISPLAY_NAME,
                                  "程序仍在托盘运行，双击托盘图标可恢复窗口。",
                                  QSystemTrayIcon.MessageIcon.Information, 3000)
        config.save(self.window.current_state())

    def hold_playback(self, tile):
        # Pending recordings still need their initial stream resolution. Once
        # recording starts, its independent session survives the watching stop.
        if (not self.playback_suspended or tile in self.window._pending_capture
                or tile.property('pictureInPictureIndependent')):
            return False
        if tile in (self.window.wall.picture_in_picture_tiles or []):
            return False
        room_id = str(tile.room.get("room_id") or "")
        if not room_id:
            return False
        if tile in self._pip_resumed:
            self._saved_playback[tile] = (room_id, tile.paused)
            self._pip_resumed.discard(tile)
        saved = self._saved_playback.get(tile)
        if saved is None or saved[0] != room_id:
            self._saved_playback[tile] = (room_id, tile.paused)
        tile.set_paused(True)
        tile.codec_reconnect_pending = True
        return True

    def restore(self):
        if self.window._closing:
            return
        if self.window.isMinimized():
            self.window.setWindowState(self.window.windowState() & ~Qt.WindowState.WindowMinimized)
        self.window.show()
        self.playback_suspended = False
        for tile in self._pip_resumed:
            if tile in self._saved_playback and tile in self.window.wall.tiles:
                self._saved_playback[tile] = (str(tile.room.get('room_id') or ''), tile.paused)
        self._pip_resumed.clear()
        saved, self._saved_playback = self._saved_playback, {}
        for tile, (room_id, paused) in saved.items():
            if tile not in self.window.wall.tiles or room_id != str(tile.room.get("room_id") or ""):
                continue
            tile.set_paused(paused)
            if not paused and tile.isVisible() and tile.room.get("live"):
                self.window.start_tile(tile)
        self.window.raise_()
        self.window.activateWindow()
        if self.window._fullscreen_tile is not None:
            owner = self.window._fullscreen_tile.window()
            owner.raise_()
            owner.activateWindow()
            self.window._fullscreen_cursor.start()

    def request_exit(self):
        self.exit_requested = True
        self.window.close()

    def handle_close(self, event):
        window = self.window
        if (self.exit_requested or window._restart_requested or window._update_plan
                or not self.available()):
            return False
        choice = window.settings.get("close_behavior", "ask")
        if choice not in ("tray", "exit"):
            dialog = CloseWindowDialog(window)
            try:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    event.ignore()
                    return True
                choice = dialog.choice
                if dialog.remember.isChecked():
                    window.settings["close_behavior"] = choice
            finally:
                dialog.deleteLater()
        if choice == "tray":
            event.ignore()
            self.hide()
            return True
        return False

    def shutdown(self):
        if self.icon is not None:
            self.menu.hide()
            self.icon.hide()
