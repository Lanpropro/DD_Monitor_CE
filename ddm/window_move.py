"""Move a single static window preview, then let Qt relocate the live window."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEvent, QEventLoop, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .window_fullscreen import _dwm_set, sync_titlebar


class MovePreview(QWidget):
    def __init__(self, owner, frame):
        super().__init__(None, Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint |
                         Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.owner = owner
        self.frame = frame
        self.physical_size = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setWindowTitle(owner.source.windowTitle())
        self.setWindowIcon(owner.source.windowIcon())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self.frame)

    def nativeEvent(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x02E4 and self.physical_size is not None:  # WM_GETDPISCALEDSIZE
            size = wintypes.SIZE.from_address(msg.lParam)
            size.cx, size.cy = self.physical_size
            return True, 1
        if msg.message == 0x0084 and self.owner.revealing:  # WM_NCHITTEST
            return True, -1  # Pass clicks to the restored live window beneath the cover.
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event):
        self.owner.cancel(restore=False)
        self.owner.source.close()
        event.accept()


class WindowMove(QObject):
    REVEAL_MS = 120

    def __init__(self, source, hwnd):
        super().__init__(source)
        self.source = source
        self.hwnd = hwnd
        self.press = None
        self.preview = None
        self.revealing = False
        self.original_geometry = None
        self.was_maximized = False
        self.caption_anchor = None
        self.destination = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._complete)
        self.user32 = ctypes.windll.user32
        self.user32.GetCursorPos.argtypes = (ctypes.POINTER(wintypes.POINT),)
        self.user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.user32.GetCapture.restype = wintypes.HWND
        self.user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
        self.user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM)
        self.user32.SendMessageW.restype = ctypes.c_ssize_t
        source.installEventFilter(self)
        source.destroyed.connect(lambda *_: self.cancel(restore=False))

    def cursor(self):
        point = wintypes.POINT()
        self.user32.GetCursorPos(ctypes.byref(point))
        return QPoint(point.x, point.y)

    def _release_press(self):
        self.press = None
        if QWidget.mouseGrabber() is self.source:
            self.source.releaseMouse()

    def eventFilter(self, watched, event):
        if self.press is None:
            return False
        if event.type() == QEvent.Type.MouseMove:
            if not event.buttons() & Qt.LeftButton:
                self._release_press()
            elif ((self.cursor()-self.press).manhattanLength()
                  >= QApplication.startDragDistance()*self.source.devicePixelRatioF()):
                self._release_press()
                self.run_move()
            return True
        if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.UngrabMouse,
                            QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            self._release_press()
        return False

    def native_message(self, msg):
        if msg.message == 0x00A3:  # Native caption double-click retains maximize/restore.
            self._release_press()
            return False
        if msg.message == 0x00A1 and msg.wParam == 2:  # WM_NCLBUTTONDOWN / HTCAPTION
            if self.source.isFullScreen() or self.source._fullscreen_tile:
                return False
            if self.revealing:
                self.reveal()
            self.press = self.cursor()
            self.caption_anchor = QCursor.pos() - self.source.geometry().topLeft()
            self.source.grabMouse()
            if self.user32.GetCapture() != self.hwnd:
                self._release_press()
                return False
            return True
        if self.press is None:
            return False
        if msg.message == 0x0215:  # WM_CAPTURECHANGED
            self.press = None
        elif msg.message in (0x0202, 0x00A2, 0x001F):  # release or cancel mode
            self._release_press()
            return True
        return False

    def begin(self):
        if self.revealing:
            self.reveal()
        if self.preview is not None or not self.source.isVisible():
            return None
        screen = self.source.screen()
        # Capture the composed screen pixels in our client rectangle. The window
        # DC alone omits libmpv's D3D11 swapchains and produces black video panes.
        offset = self.source.mapToGlobal(QPoint()) - screen.geometry().topLeft()
        frame = screen.grabWindow(0, offset.x(), offset.y(),
                                  self.source.width(), self.source.height())
        if frame.isNull():
            return None
        self.was_maximized = self.source.isMaximized()
        self.original_geometry = QRect(self.source.normalGeometry() if self.was_maximized
                                       else self.source.geometry())
        geometry = QRect(self.original_geometry)
        if self.was_maximized:
            anchor = self.caption_anchor
            if anchor is None:
                caption = self.source.geometry().top()-self.source.frameGeometry().top()
                anchor = QPoint(self.source.width()//2, -caption//2)
            fraction = max(0.0, min(1.0, anchor.x()/max(1, self.source.width())))
            pointer = QCursor.pos()
            geometry.moveTopLeft(QPoint(pointer.x()-round(geometry.width()*fraction),
                                         pointer.y()-anchor.y()))
        preview = MovePreview(self, frame)
        self.preview = preview
        preview.setGeometry(geometry)
        preview.winId()
        preview.windowHandle().setScreen(screen)
        preview.setGeometry(geometry)
        # These windows exchange one image; independent DWM fades expose the
        # desktop and a scaled/grey intermediate surface during every handoff.
        _dwm_set(int(preview.winId()), 3, 1)  # DWMWA_TRANSITIONS_FORCEDISABLED
        _dwm_set(self.hwnd, 3, 1)
        preview.show()
        sync_titlebar(preview)
        # Deliver the new QWindow's expose event before repainting its backing
        # store; repaint alone does nothing until the first expose is handled.
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        if self.preview is not preview:
            return None
        preview.repaint()
        ctypes.windll.dwmapi.DwmFlush()
        bounds = wintypes.RECT()
        self.user32.GetWindowRect(int(preview.winId()), ctypes.byref(bounds))
        preview.physical_size = bounds.right-bounds.left, bounds.bottom-bounds.top
        self.source.hide()
        return preview

    def run_move(self):
        preview = self.begin()
        if preview is None:
            self.user32.SendMessageW(self.hwnd, 0x0112, 0xF012, 0)  # SC_MOVE | HTCAPTION
            return
        try:
            # WinDLL releases the GIL during the native move loop, so stream workers continue.
            self.user32.SendMessageW(int(preview.winId()), 0x0112, 0xF012, 0)
            if self.preview is preview:
                self.finish(cancelled=bool(self.user32.GetAsyncKeyState(0x1B) & 0x8000))
        except BaseException:
            self.cancel()
            raise

    def finish(self, *, cancelled=False):
        if self.preview is None:
            return
        if cancelled:
            self.cancel()
            return
        preview = self.preview
        self.revealing = True
        maximized = preview.isMaximized()
        bounds = wintypes.RECT()
        self.user32.GetWindowRect(int(preview.winId()), ctypes.byref(bounds))
        resized = (bounds.right-bounds.left, bounds.bottom-bounds.top) != preview.physical_size
        size = preview.size() if resized and not maximized else self.original_geometry.size()
        destination = QRect(preview.geometry().topLeft(), size)
        if not maximized:
            # Cover the destination at its new DPI before exposing the live
            # children. The drag preview still has the old physical size here.
            preview.setGeometry(destination)
        preview.repaint()
        self.user32.SetWindowPos(int(preview.winId()), -1, 0, 0, 0, 0, 0x0013)  # temporary cover
        ctypes.windll.dwmapi.DwmFlush()
        if not maximized:
            # setGeometry clears Qt's maximized flag even while the hidden HWND
            # remains maximized. Restore the native state before that happens.
            self.source.setWindowState(self.source.windowState() & ~Qt.WindowMaximized)
        self.source.setGeometry(destination)
        self.source.showMaximized() if maximized else self.source.showNormal()
        self.source.raise_()
        self.source.activateWindow()
        self.destination = destination
        self.timer.start(self.REVEAL_MS)

    def _complete(self):
        if self.destination is None:
            self.reveal()
            return
        destination, self.destination = self.destination, None
        try:
            # Let Qt deliver the new DPI and frame margins before correcting
            # client geometry; otherwise repeated trips shrink the normal size.
            if not self.source.isMaximized() and self.source.geometry() != destination:
                self.source.setGeometry(destination)
            self.source._resize_dirty = True
            self.source._finish_interactive_resize()
            self.timer.start(self.REVEAL_MS)
        except BaseException:
            self.cancel()
            raise

    def reveal(self):
        self.timer.stop()
        preview, self.preview = self.preview, None
        self.revealing = False
        self.destination = None
        if preview is not None:
            ctypes.windll.dwmapi.DwmFlush()
            preview.hide()
            preview.deleteLater()
            _dwm_set(self.hwnd, 3, 0)

    def cancel(self, *, restore=True):
        self._release_press()
        active = self.preview is not None
        if active and restore:
            self.source.showMaximized() if self.was_maximized else self.source.showNormal()
            self.source.raise_()
            self.source.repaint()
        self.reveal()
