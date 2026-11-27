"""Opt-in evidence for startup geometry and control visibility on the video wall."""
import sys
import time

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


def native_client_size(window):
    if sys.platform != 'win32' or QApplication.platformName() != 'windows':
        return None
    from ctypes import byref, windll, wintypes
    hwnd = window.internalWinId()
    bounds = wintypes.RECT()
    if hwnd and windll.user32.GetClientRect(wintypes.HWND(hwnd), byref(bounds)):
        return bounds.right, bounds.bottom
    return None


class TileTrace(QObject):
    MAX_RECORDS = 5000

    def __init__(self, window, capture):
        super().__init__(window)
        self.window = window
        self.capture = capture
        self.count = 0
        self.startup_until = None
        self.tiles = ()
        self.watched = {}
        self.last_sample = None
        self.last_tick = time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.sample_pointer)
        QApplication.instance().installEventFilter(self)
        self.startup('ready')
        self.timer.start()

    def emit(self, stage, **data):
        if self.count >= self.MAX_RECORDS:
            return
        self.count += 1
        self.capture.emit(stage, **data)
        if self.count == self.MAX_RECORDS:
            self.timer.stop()
            self.capture.emit('tile-trace-limit', limit=self.MAX_RECORDS)

    def startup(self, event, receiver='window'):
        window = self.window
        wall = window.wall
        self.emit('tile-startup', event=event, receiver=receiver,
                  windowSize=window.size().toTuple(), nativeClientSize=native_client_size(window),
                  wallGeometry=wall.geometry().getRect(),
                  tileGeometry=[tile.geometry().getRect() for tile in wall.tiles if not tile.isHidden()],
                  scale=window.devicePixelRatioF(), visible=window.isVisible(),
                  maximized=window.isMaximized(), geometryRestored=window._geometry_restored,
                  layoutPending=window._startup_layout_pending)

    @staticmethod
    def tile_state(tile):
        return dict(overlay=tile._overlay_visible, controlsVisible=tile.controls.isVisible(),
                    barExposed=tile.bottom.controls_exposed(), titleVisible=tile.title_badge.isVisible(),
                    hoverActive=tile._normal_hover_active, polling=tile._control_hover_timer.isActive(),
                    fullscreen=bool(tile.property('fullscreen')),
                    pictureInPicture=bool(tile.property('pictureInPicture')))

    def sample_pointer(self):
        now, previous_tick = time.monotonic(), self.last_tick
        self.last_tick = now
        window = self.window
        tiles = tuple(window.wall.tiles)
        if tiles != self.tiles:
            self.tiles = tiles
            self.watched = {widget: (index, tile, role)
                            for index, tile in enumerate(tiles)
                            for widget, role in ((tile, 'tile'), (tile.video, 'video'),
                                                 (tile.controls, 'controls'),
                                                 (tile._control_hover_timer, 'poll'))}
        point = QCursor.pos()
        for index, tile in enumerate(tiles):
            if not tile.isVisible():
                continue
            local = tile.mapFromGlobal(point)
            if not tile.rect().contains(local):
                continue
            sample = dict(tile=index, position=local.toTuple(), **self.tile_state(tile),
                          windowActive=window.isActiveWindow(),
                          popup=QApplication.activePopupWidget() is not None,
                          modal=QApplication.activeModalWidget() is not None,
                          buttons=bool(QApplication.mouseButtons()),
                          override=QApplication.overrideCursor() is not None,
                          pluginInteraction=tile.plugin_interaction_active())
            break
        else:
            sample = dict(tile=None)
        if sample != self.last_sample:
            self.last_sample = sample
            self.emit('tile-pointer', gapMs=round((now - previous_tick) * 1000, 1), **sample)

    def eventFilter(self, watched, event):
        if self.count >= self.MAX_RECORDS:
            return False
        kind = event.type()
        window = self.window
        if watched is window and kind == QEvent.Show and self.startup_until is None:
            self.startup_until = time.monotonic() + 2
        if (kind in (QEvent.Show, QEvent.Resize, QEvent.Paint, QEvent.WindowStateChange)
                and (watched is window or watched is window.wall)
                and (self.startup_until is None or time.monotonic() <= self.startup_until)):
            self.startup(kind.name, 'window' if watched is window else 'wall')
        if kind not in (QEvent.Enter, QEvent.Leave, QEvent.Show, QEvent.Hide, QEvent.Paint, QEvent.Timer):
            return False
        target = self.watched.get(watched)
        if target is None:
            return False
        index, tile, role = target
        if ((role in ('tile', 'video') and kind in (QEvent.Enter, QEvent.Leave))
                or (role == 'controls' and kind in (QEvent.Show, QEvent.Hide, QEvent.Paint))
                or (role == 'poll' and kind == QEvent.Timer)):
            self.emit('tile-event', tile=index, receiver=role, event=kind.name, **self.tile_state(tile))
        return False
