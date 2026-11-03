"""Interactive bottom bar with per-pixel alpha above native video on Windows."""
import ctypes
from ctypes import wintypes
import logging
import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget


class FullscreenBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setProperty('fullscreen', False)
        self._masked_labels = set()
        self._label_mask_pending = False
        self._tile_rect = QRect()
        self._owner_window = parent.window()
        self._owner_hidden_visible = False
        self._owner_window.installEventFilter(self)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._input_trace_until = 0.0
        self._input_trace_count = 0

    def _trace_input(self, stage, watched=None, event=None):
        if os.environ.get('DDM_FULLSCREEN_INPUT_CAPTURE') != '1' or not self.property('fullscreen'):
            return
        now = time.monotonic()
        if event is not None and event.type() in (QEvent.KeyPress, QEvent.InputMethod):
            if not self._input_trace_until:
                self._input_trace_until = now + 20
        if now > self._input_trace_until or self._input_trace_count >= 300:
            return
        self._input_trace_count += 1
        focus = QApplication.focusWidget()
        logging.getLogger(__name__).info(
            'fullscreen-input stage=%s event=%s widget=%s native=%s focus=%s visible=%s composition=%s',
            stage, event.type().name if event is not None else '',
            type(watched).__name__ if watched is not None else '',
            watched.testAttribute(Qt.WA_NativeWindow) if isinstance(watched, QWidget) else False,
            type(focus).__name__ if focus is not None else '', self.isVisible(),
            'Qt' if self.qt_composited else 'child')

    @property
    def qt_composited(self):
        return (self.property('fullscreen') and sys.platform == 'win32'
                and QApplication.platformName() == 'windows')

    def set_fullscreen(self, enabled):
        if enabled == self.property('fullscreen'):
            return
        if self.qt_composited:
            self.setWindowOpacity(1.0)
        # The tile is temporarily hidden while promoted to a fullscreen window.
        # Preserve the bar's own visibility intent, not its ancestor's state.
        visible = not self.isHidden()
        local = QRect(self.parentWidget().mapFromGlobal(self.mapToGlobal(QPoint())), self.size())
        focus = QApplication.focusWidget()
        restore_focus = focus is not None and (focus is self or self.isAncestorOf(focus))
        owner = self.parentWidget().window()
        if owner is not self._owner_window:
            self._owner_window.removeEventFilter(self)
            self._owner_window = owner
            owner.installEventFilter(self)
        if not enabled:
            self._mask_label_windows(False)
        self.setProperty('fullscreen', enabled)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            # Recreate this backing store (and its native input children) when
            # changing alpha modes; Qt can retain layered HWNDs after reparenting.
            self.destroy()
            # A child HWND shares the main window's opaque backing store. Give
            # the complete interactive bar its own Qt-managed alpha backing store.
            self.setAttribute(Qt.WA_TranslucentBackground, enabled)
            self.setAttribute(Qt.WA_NoSystemBackground, enabled)
            self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint if enabled else Qt.Widget)
            self.set_tile_geometry(local.x(), local.y(), local.width(), local.height())
        for widget in (self, *self.findChildren(QWidget)):
            widget.setProperty('fullscreen', enabled)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.setVisible(visible)
        if restore_focus:
            focus.setFocus(Qt.OtherFocusReason)
        self.refresh_theme()

    def set_tile_geometry(self, x, y, width, height):
        self._tile_rect = QRect(x, y, width, height)
        position = self.parentWidget().mapToGlobal(QPoint(x, y)) if self.qt_composited else QPoint(x, y)
        self.setGeometry(QRect(position, self._tile_rect.size()))
        if self.qt_composited:
            visible = self._tile_rect.intersected(self.parentWidget().rect())
            self.setMask(QRegion(visible.translated(-self._tile_rect.topLeft())))
        else:
            self.clearMask()

    def tile_y(self):
        return self.parentWidget().mapFromGlobal(self.mapToGlobal(QPoint())).y()

    def _follow_owner(self):
        if self.qt_composited:
            self.set_tile_geometry(*self._tile_rect.getRect())

    def refresh_theme(self):
        self.update()

    def _render_badge(self, painter):
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0, 150))
        painter.fillRect(self.rect(), shade)

    def _mask_label_windows(self, hide):
        if sys.platform != 'win32' or QApplication.platformName() != 'windows':
            return
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HRGN
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HRGN, wintypes.BOOL)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        for label in self.findChildren(QLabel):
            if not (label.testAttribute(Qt.WA_NativeWindow)
                    and label.testAttribute(Qt.WA_TransparentForMouseEvents)):
                continue
            hwnd = int(label.winId())
            if hide and hwnd not in self._masked_labels:
                region = gdi32.CreateRectRgn(0, 0, 0, 0)
                if user32.SetWindowRgn(hwnd, region, True):
                    self._masked_labels.add(hwnd)
                elif region:
                    gdi32.DeleteObject(region)
            elif not hide and hwnd in self._masked_labels:
                user32.SetWindowRgn(hwnd, None, True)
            if not hide and not label.findChildren(QWidget):
                # Tool-window composition made these passive labels native.
                # Return their text to the ordinary bar's backing store instead
                # of leaving opaque child HWNDs across the status/input region.
                label.destroy()
                label.setAttribute(Qt.WA_NativeWindow, False)
        if not hide:
            self._masked_labels.clear()

    def _schedule_label_mask(self):
        if self.qt_composited and not self._label_mask_pending:
            self._label_mask_pending = True
            QTimer.singleShot(0, self, self._flush_label_mask)

    def _flush_label_mask(self):
        self._label_mask_pending = False
        if self.qt_composited and self.isVisible():
            self._mask_label_windows(True)

    def paintEvent(self, event):
        self._trace_input('bar-paint', self, event)
        if not self.property('fullscreen'):
            QWidget.paintEvent(self, event)
            return
        painter = QPainter(self)
        self._render_badge(painter)
        painter.end()
        self._schedule_label_mask()

    def event(self, event):
        if event.type() == QEvent.ChildAdded and isinstance(event.child(), QWidget):
            event.child().installEventFilter(self)
        return QWidget.event(self, event)

    def eventFilter(self, watched, event):
        self._trace_input('child-event', watched, event)
        if event.type() == QEvent.ChildAdded and isinstance(event.child(), QWidget):
            event.child().installEventFilter(self)
        if self.qt_composited and watched is self._owner_window:
            if event.type() == QEvent.Hide:
                self._owner_hidden_visible = self.isVisible()
                self.hide()
            elif event.type() == QEvent.Show and self._owner_hidden_visible:
                self.show()
                self._owner_hidden_visible = False
            elif event.type() == QEvent.Move:
                QTimer.singleShot(0, self, self._follow_owner)
        return super().eventFilter(watched, event)
