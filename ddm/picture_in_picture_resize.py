"""Scale live DWM surfaces during a PiP resize without resizing the players."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QApplication, QWidget


class _ThumbnailProperties(ctypes.Structure):
    _fields_ = [('flags', wintypes.DWORD), ('destination', wintypes.RECT),
                ('source', wintypes.RECT), ('opacity', wintypes.BYTE),
                ('visible', wintypes.BOOL), ('client_only', wintypes.BOOL)]


class LiveResize:
    def __init__(self, source):
        self.source = source
        self.starting = True
        self.finishing = False
        self.thumbnails = {}
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus
        if source.controller.pinned:
            flags |= Qt.WindowStaysOnTopHint
        self.preview = QWidget(None, flags)
        self.preview.setAttribute(Qt.WA_ShowWithoutActivating)
        self.preview.setStyleSheet('background: black;')
        self.preview.setGeometry(source.geometry())
        self.preview.winId()
        self.preview.windowHandle().setTransientParent(source.windowHandle())
        from .window_fullscreen import _dwm_set
        self.native_rounding = _dwm_set(int(self.preview.winId()), 33, 2) == 0
        _dwm_set(int(self.preview.winId()), 34, 0xFFFFFFFE)
        self.dwm = ctypes.windll.dwmapi
        self.dwm.DwmRegisterThumbnail.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.HANDLE))
        self.dwm.DwmUpdateThumbnailProperties.argtypes = (wintypes.HANDLE, ctypes.POINTER(_ThumbnailProperties))
        self.dwm.DwmUnregisterThumbnail.argtypes = (wintypes.HANDLE,)
        self.user32 = ctypes.windll.user32
        self.user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        self.reveal = QTimer(source)
        self.reveal.setSingleShot(True)
        self.reveal.timeout.connect(self.stop)

    def _client_rect(self, window):
        hwnd = int(window.winId())
        rect, point = wintypes.RECT(), wintypes.POINT()
        self.user32.GetClientRect(hwnd, ctypes.byref(rect))
        self.user32.ClientToScreen(hwnd, ctypes.byref(point))
        return QRect(point.x, point.y, rect.right, rect.bottom)

    def _surfaces(self):
        source = self.source
        yield source
        layer = source.controller.host.wall._quick_danmaku_layer
        if layer is not None and layer.window.isVisible():
            yield layer.window
        for widget in QApplication.topLevelWidgets():
            if widget in (source, source.tools, source.audio_tools, source.audio_panel, source.audio_feedback, self.preview) or not widget.isVisible():
                continue
            owner = widget.parentWidget()
            while owner is not None and owner is not source:
                owner = owner.parentWidget()
            if owner is source:
                yield widget

    def sync(self):
        """The thumbnails stay live; only their placement and visibility change."""
        base = self._client_rect(self.source)
        target = self._client_rect(self.preview)
        visible = set()
        for window in self._surfaces():
            hwnd = int(window.winId())
            visible.add(hwnd)
            if hwnd not in self.thumbnails:
                handle = wintypes.HANDLE()
                if self.dwm.DwmRegisterThumbnail(int(self.preview.winId()), hwnd, ctypes.byref(handle)) != 0:
                    return False
                self.thumbnails[hwnd] = handle
            rect = self._client_rect(window)
            left = round((rect.left() - base.left()) * target.width() / base.width())
            top = round((rect.top() - base.top()) * target.height() / base.height())
            right = round((rect.left() - base.left() + rect.width()) * target.width() / base.width())
            bottom = round((rect.top() - base.top() + rect.height()) * target.height() / base.height())
            properties = _ThumbnailProperties(1 | 4 | 8 | 16,
                wintypes.RECT(left, top, right, bottom), wintypes.RECT(), 255, True, True)
            if self.dwm.DwmUpdateThumbnailProperties(self.thumbnails[hwnd], ctypes.byref(properties)) != 0:
                return False
        for hwnd in self.thumbnails.keys() - visible:
            self.dwm.DwmUnregisterThumbnail(self.thumbnails.pop(hwnd))
        return True

    def begin(self):
        if not self.sync():
            self.stop()
            return False
        self.source.tools.hide()
        self.source.hide_audio()
        self.preview.show()
        self.preview.raise_()
        self.dwm.DwmFlush()
        # Keep the original native players visible to DWM at a stable size.
        # No screenshot, frame readback, second decoder or audio instance.
        desktop = QApplication.primaryScreen().virtualGeometry()
        self.source.move(desktop.left() - self.source.width() - 256, self.source.y())
        for tile in self.source.controller.host.wall.visible_tiles():
            tile.video_danmaku.super_chat_overlay.sync(tile.video_danmaku)
        self.starting = False
        if not self.sync():
            self.finish(immediate=True)
            return False
        return True

    def set_geometry(self, rect):
        self.preview.setGeometry(rect)
        if not self.native_rounding:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.preview.rect()), 8, 8)
            self.preview.setMask(QRegion(path.toFillPolygon().toPolygon()))
        if not self.sync():
            self.finish(immediate=True)

    def finish(self, *, immediate=False):
        if not self.finishing:
            self.finishing = True
            self.source.setGeometry(self.preview.geometry())
            for tile in self.source.controller.host.wall.visible_tiles():
                tile.video_danmaku.super_chat_overlay.sync(tile.video_danmaku)
            self.sync()
        if immediate:
            self.stop()
        else:
            # Cover the one final player resize while its swapchains settle.
            self.reveal.start(80)

    def stop(self):
        self.reveal.stop()
        for handle in self.thumbnails.values():
            self.dwm.DwmUnregisterThumbnail(handle)
        self.thumbnails.clear()
        self.preview.hide()
        self.preview.deleteLater()
        self.reveal.deleteLater()
        if self.source._live_resize is self:
            self.source._live_resize = None
            self.source._poll_tools()


class LiveMove(LiveResize):
    """Move one live composition while its native video windows stay still."""
    def __init__(self, source):
        super().__init__(source)
        self.system_moving = False
        self.user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user32.SendMessageW.restype = ctypes.c_ssize_t

    def set_geometry(self, rect):
        self.preview.move(rect.topLeft())

    def run_system_move(self):
        if not self.user32.GetAsyncKeyState(1) & 0x8000:
            return False
        self.system_moving = True
        self.source.releaseMouse()
        try:
            # WinDLL releases the GIL for the native move loop.
            self.user32.SendMessageW(int(self.preview.winId()), 0x0112, 0xF012, 0)
        finally:
            self.system_moving = False
        if (self.source._live_move is self and self.source._gesture is not None
                and self.user32.GetAsyncKeyState(0x1B) & 0x8000):
            self.preview.setGeometry(self.source._gesture[1])
        return True

    def stop(self):
        super().stop()
        if self.source._live_move is self:
            self.source._live_move = None
            self.source._poll_tools()
