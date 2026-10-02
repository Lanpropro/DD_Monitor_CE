"""Hide the idle fullscreen cursor, including over VLC's native video child."""
import ctypes
import sys
import time

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class FullscreenCursor(QObject):
    IDLE_SECONDS = 3.0

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.hidden = False
        self._position = None
        self._last_move = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_cursor)

    def start(self):
        self.stop()
        self._position = QCursor.pos()
        self._last_move = time.monotonic()
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self._show()

    def _show(self):
        if self.hidden:
            QApplication.restoreOverrideCursor()
            self.hidden = False
            if sys.platform == "win32" and QApplication.platformName() == "windows":
                widget = QApplication.widgetAt(QCursor.pos())
                shape = widget.cursor().shape() if widget else Qt.ArrowCursor
                resource = {Qt.PointingHandCursor: 32649, Qt.IBeamCursor: 32513}.get(shape, 32512)
                user32 = ctypes.windll.user32
                user32.LoadCursorW.restype = ctypes.c_void_p
                user32.SetCursor.argtypes = (ctypes.c_void_p,)
                user32.SetCursor(user32.LoadCursorW(None, resource))

    def update_cursor(self):
        tile = self.window._fullscreen_tile
        position = QCursor.pos()
        now = time.monotonic()
        # Poll the global position: VLC's child HWND does not send Qt mouse moves.
        eligible = (tile is not None and self.window.isActiveWindow()
                    and QApplication.activePopupWidget() is None
                    and QApplication.activeModalWidget() is None
                    and not QApplication.mouseButtons()
                    and tile.video.rect().contains(tile.video.mapFromGlobal(position)))
        if eligible:
            for widget in (tile.controls, tile.stream_badge, tile.title_badge):
                if widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(position)):
                    eligible = False
                    break
        if position != self._position or not eligible:
            self._position = position
            self._last_move = now
            self._show()
            return
        if now - self._last_move < self.IDLE_SECONDS:
            return
        if not self.hidden:
            QApplication.setOverrideCursor(Qt.BlankCursor)
            self.hidden = True
        if sys.platform == "win32" and QApplication.platformName() == "windows":
            # Qt's override alone cannot change VLC's native child cursor.
            ctypes.windll.user32.SetCursor(None)
