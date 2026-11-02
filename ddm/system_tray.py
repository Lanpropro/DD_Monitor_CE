"""System tray controls and the remembered window-close choice."""
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QMenu, QPushButton,
    QStyle, QSystemTrayIcon, QVBoxLayout,
)

from . import config, theme, version


class CloseWindowDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("关闭窗口")
        self.setMinimumWidth(420)
        self.choice = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(18)
        label = QLabel("关闭窗口后，你希望程序如何运行？")
        layout.addWidget(label)
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
        self.exit_requested = False
        self.playback_suspended = False
        self._saved_playback = {}
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = window.windowIcon()
        if icon.isNull():
            icon = window.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.icon = QSystemTrayIcon(icon, window)
        self.icon.setToolTip(f"{version.DISPLAY_NAME}：双击显示或隐藏窗口")
        self.menu = QMenu(window)
        self.toggle_action = self.menu.addAction("显示/隐藏窗口", self.toggle)
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("退出", self.request_exit)
        self.menu.aboutToShow.connect(self.update_menu)
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self.activate)
        self.icon.messageClicked.connect(self.restore)
        self.icon.show()

    def available(self):
        return bool(self.icon is not None and self.icon.isVisible()
                    and QSystemTrayIcon.isSystemTrayAvailable())

    def update_menu(self):
        self.toggle_action.setText("隐藏窗口" if self.window.isVisible()
                                   and not self.window.isMinimized() else "显示窗口")

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
        self.window.hover_preview.stop()
        self.window._fullscreen_cursor.stop()
        if not self.playback_suspended and self.window.settings.get("tray_pause_playback", True):
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
        if not self.playback_suspended or tile in self.window._pending_capture:
            return False
        room_id = str(tile.room.get("room_id") or "")
        if not room_id:
            return False
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
            self.icon.hide()
