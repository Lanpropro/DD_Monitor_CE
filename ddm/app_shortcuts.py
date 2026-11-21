"""Main window app shortcuts; window remains the only state and Qt lifetime owner."""
import sys
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit
from .playback_controls import VolumeButton
from .shortcut_actions import (
    DEFAULT_HOVER_WHEEL_VOLUME_STEP, DEFAULT_SHORTCUTS, FULLSCREEN_VOLUME_SHORTCUTS,
    WHEEL_SHORTCUTS, wheel_volume_step
)
from .video_surface import VideoSurface


class AppShortcuts(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host

    def refresh_shortcuts(self) -> None:
        host = self.host
        if not hasattr(host, '_shortcut_wheel_filter'):
            QApplication.instance().installEventFilter(self)
            host._shortcut_wheel_filter = True
        if not hasattr(host, "_shortcut_focus_connected"):
            application = QApplication.instance()
            assert isinstance(application, QApplication)
            application.focusChanged.connect(host._sync_input_shortcuts)
            host._shortcut_focus_connected = True
        for shortcut in getattr(host, "_window_shortcuts", []):
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        host._window_shortcuts = []
        fullscreen_volume = (
            {host.shortcuts.get(key, DEFAULT_SHORTCUTS[key]) for key in FULLSCREEN_VOLUME_SHORTCUTS}
            if host._fullscreen_tile is not None else set()
        )
        sequences = [value for key, value in host.shortcuts.items()
                     if key not in WHEEL_SHORTCUTS + FULLSCREEN_VOLUME_SHORTCUTS and not key.startswith('pip_')]
        sequences.extend(fullscreen_volume)
        if host.shortcuts.get("danmaku_input") == "Return":
            sequences.append("Enter")
        presets = getattr(host, 'layout_presets', None)
        layout_sequences = presets.shortcuts() if presets is not None else {}
        sequences.extend(layout_sequences)
        for sequence in dict.fromkeys(sequences):
            if not sequence:
                continue
            shortcut = QShortcut(QKeySequence(sequence), host._fullscreen_tile or host)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setAutoRepeat(False)
            shortcut.setProperty('folderToggle', sequence == host.shortcuts.get('toggle_folders'))
            shortcut.setProperty('fullscreenVolume', sequence in fullscreen_volume)
            shortcut.setProperty('layoutPreset', sequence in layout_sequences)
            shortcut.setProperty("danmakuInput", sequence in (
                host.shortcuts.get("danmaku_input"),
                "Enter" if host.shortcuts.get("danmaku_input") == "Return" else ""))
            shortcut.activated.connect(lambda key=sequence: host._handle_shortcut(key))
            host._window_shortcuts.append(shortcut)
        host._sync_input_shortcuts()

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Wheel:
            return False
        host = self.host
        window = watched.window() if hasattr(watched, 'window') else None
        if window is not host and window is not host._fullscreen_tile:
            return False
        angle = event.angleDelta().y()
        delta = angle or event.pixelDelta().y()
        if not delta:
            return False
        snap_grid = getattr(host.wall, 'snap_grid', None)
        if (event.modifiers() == Qt.ControlModifier and snap_grid is not None and snap_grid.interactive()
                and QApplication.activePopupWidget() is None):
            point = host.wall.mapFromGlobal(event.globalPosition().toPoint())
            tile = next((tile for tile in host.wall.visible_tiles() if tile.geometry().contains(point)), None)
            if tile is not None and snap_grid.resize_tile(tile, 1 if delta > 0 else -1):
                event.accept()
                return True
        if event.modifiers() == Qt.NoModifier and host.settings.get('hover_wheel_volume', False):
            if (not isinstance(watched, VideoSurface)
                    or not watched.rect().contains(event.position().toPoint())
                    or QApplication.activePopupWidget() is not None):
                return False
            tile = watched.parentWidget()
            if not tile.room.get('room_id'):
                return False
            step = wheel_volume_step(host.settings.get('hover_wheel_volume_step'), DEFAULT_HOVER_WHEEL_VOLUME_STEP)
        else:
            if not self._matches_volume_wheel(event.modifiers(), delta):
                return False
            tile = host._tile_under_cursor()
            if tile is None:
                return False
            step = wheel_volume_step(host.settings.get('wheel_volume_step'))
        step *= max(1, abs(angle) // 120)
        tile.set_volume(tile.volume + (step if delta > 0 else -step))
        event.accept()
        return True

    def _matches_volume_wheel(self, pressed, delta):
        if not pressed:
            return False
        key = 'volume_up' if delta > 0 else 'volume_down'
        shortcut = self.host.shortcuts.get(key, 'Shift+WheelUp' if delta > 0 else 'Shift+WheelDown')
        parts = [part for part in shortcut.split('+') if part]
        wheel = 'WheelUp' if delta > 0 else 'WheelDown'
        if not parts or parts[-1] != wheel:
            return False
        modifiers = Qt.NoModifier
        keys = {'Shift': Qt.ShiftModifier, 'Ctrl': Qt.ControlModifier,
                'Alt': Qt.AltModifier, 'Meta': Qt.MetaModifier}
        for part in parts[:-1]:
            if part not in keys:
                return False
            modifiers |= keys[part]
        return pressed == modifiers

    def sync_input_shortcuts(self, *_args) -> None:
        host = self.host
        editing = isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit))
        for shortcut in host._window_shortcuts:
            sequence = shortcut.key().toString()
            if shortcut.property('layoutPreset'):
                shortcut.setEnabled(not editing and host._fullscreen_tile is None)
            elif (sequence in ("Up", "Down") or shortcut.property("fullscreenVolume")
                    or shortcut.property("danmakuInput") or shortcut.property('folderToggle')):
                shortcut.setEnabled(not editing)

    def tile_under_cursor(self):
        """鼠标现在压在哪一格的画面上（没有就 None）。

        **不能用 QApplication.widgetAt**：格子的画面区是 播放器 的原生窗口，不是 Qt
        控件；鼠标停在画面上时 widgetAt 拿不到那一格（顶多给回主窗口），
        于是 F（全屏）/ M / Alt+M 全都按不动 —— 用户报的「切换画布完全失效」
        就是这个。改成拿光标全局坐标和每个格子的矩形比，跟画面是不是原生窗口无关。
        """
        host = self.host
        point = QCursor.pos()
        tiles = ([host._fullscreen_tile] if host._fullscreen_tile is not None else
                 host.wall.tiles if hasattr(host, "wall") else [])
        for tile in tiles:
            if not tile.isVisible():
                continue
            if tile.rect().contains(tile.mapFromGlobal(point)):
                return tile
        return None

    def handle_shortcut(self, pressed: str) -> bool:
        host = self.host
        if any(tile.plugin_interaction_active() for tile in host.wall.tiles if tile.isVisible()):
            return False
        shortcuts = host.shortcuts
        volume_up, volume_down = (shortcuts.get(key, DEFAULT_SHORTCUTS[key]) for key in FULLSCREEN_VOLUME_SHORTCUTS)
        if pressed and pressed == shortcuts.get('toggle_folders'):
            if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit)):
                return False
            host.sidebar.toggle_all_folders()
        elif pressed and pressed in (volume_up, volume_down) and host._fullscreen_tile is not None:
            if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit)):
                return False
            tile = host._fullscreen_tile
            tile.set_volume(tile.volume + (10 if pressed == volume_up else -10))
        elif pressed and pressed == shortcuts.get("focus"):
            if host._fullscreen_tile is not None:
                host._exit_fullscreen()
            else:
                tile = host._tile_under_cursor()
                if tile is not None and tile.room.get("room_id"):
                    host._on_fullscreen(tile)
        elif pressed and pressed == shortcuts.get("mute"):
            host._toggle_mute_under_cursor()
        elif pressed and pressed == shortcuts.get("audio_cycle"):
            host._cycle_audio_under_cursor()
        elif pressed and pressed == shortcuts.get("record"):
            tile = host._tile_under_cursor()
            if tile is not None and tile.room.get("room_id"):
                host._toggle_recording(tile)
        elif pressed and pressed == shortcuts.get("video_danmaku"):
            tile = host._tile_under_cursor()
            if tile is not None:
                tile.danmaku_button.toggle()
        elif pressed and pressed == shortcuts.get("close_tile"):
            tile = host._tile_under_cursor()
            if tile is not None and tile.room.get("room_id"):
                tile.closeRequested.emit(tile.room)
        elif pressed and (pressed == shortcuts.get("danmaku_input") or (
                pressed == "Enter" and shortcuts.get("danmaku_input") == "Return")):
            for panel in host.wall.pane_danmaku.all_panels():
                if panel.isVisible() and panel.rect().contains(panel.mapFromGlobal(QCursor.pos())):
                    controls = getattr(panel, "_linked_controls", None) or panel._tile_controls
                    if controls is not None:
                        controls.focus_input()
                    return True
            tile = host._fullscreen_tile or host._tile_under_cursor()
            if tile is not None and tile.room.get("room_id"):
                if tile is host._fullscreen_tile:
                    host._fullscreen_cursor.start()
                    tile.set_fullscreen_controls_hidden(False)
                tile.focus_danmaku_input()
        elif pressed and pressed == shortcuts.get("solo"):
            host._toggle_solo_audio()
        elif pressed and pressed == shortcuts.get("restore") and host._fullscreen_tile:
            host._exit_fullscreen()
        else:
            presets = getattr(host, 'layout_presets', None)
            if pressed and presets is not None and (key := presets.shortcuts().get(pressed)):
                if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit)):
                    return False
                return presets.apply(key)
            return False
        return True

    def toggle_mute_under_cursor(self) -> None:
        """M：静音 / 取消静音鼠标所在的那一路（只动这一路，别的格子不变）。"""
        host = self.host
        target = host._tile_under_cursor()
        if target is None:
            return
        target.set_muted(not target.muted)
        print(f"[快捷键] {target.room.get('uname')} "
              f"{'已静音' if target.muted else '已取消静音'}",
              file=sys.stderr, flush=True)

    def cycle_audio_under_cursor(self) -> None:
        """E：鼠标所在格子依次启用双声道、左声道、右声道、静音。"""
        host = self.host
        target = host._tile_under_cursor()
        if target is None or not target.room.get("room_id"):
            return
        if target.muted:
            target.set_audio_channel(0)
        elif target.audio_channel == VolumeButton.CHANNEL_RIGHT:
            target.set_muted(True)
        else:
            target.set_audio_channel(VolumeButton.CHANNEL_RIGHT
                                     if target.audio_channel == VolumeButton.CHANNEL_LEFT
                                     else VolumeButton.CHANNEL_LEFT)

    def toggle_solo_audio(self) -> None:
        """Alt+M：只让鼠标悬停的那一路有声，其他格子一律静音。

        鼠标不在任何格子上时等于「全部静音」——这也是想安静下来时最顺手的按法。
        """
        host = self.host
        target = host._tile_under_cursor()
        if target is not None and not target.room.get("room_id"):
            target = None
        for tile in host.wall.tiles:
            tile.set_muted(tile is not target)
        if target is not None:
            print(f"[快捷键] 只保留 {target.room.get('uname')} 的声音",
                  file=sys.stderr, flush=True)
        else:
            print("[快捷键] 全部静音", file=sys.stderr, flush=True)
