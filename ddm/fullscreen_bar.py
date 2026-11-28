"""Interactive bottom bar with per-pixel alpha above native video on Windows."""
import ctypes
from ctypes import wintypes
import logging
import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from .badge_surface import BadgeSurface
from .corner_geometry import continuous_path
from .theme import VIDEO_CONTROL_BACKING, VIDEO_CONTROL_RADIUS
from .window_fullscreen import raise_below_native_windows


class FullscreenBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            # The bar overlaps native video in fullscreen; its Qt children
            # share this window instead of each requiring a separate HWND.
            self.setAttribute(Qt.WA_NativeWindow, True)
        self.setProperty('fullscreen', False)
        self.setProperty('overVideo', False)
        self.contrast_groups = ()
        self._masked_labels = set()
        self._label_mask_pending = False
        self._tile_rect = QRect()
        self._owner_window = parent.window()
        self._owner_hidden_visible = False
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
        return (self.property('overVideo') and sys.platform == 'win32'
                and QApplication.platformName() == 'windows')

    @property
    def windowed_overlay(self):
        return self.property('overVideo') and not self.property('fullscreen')

    def controls_exposed(self):
        return self.isVisible() and self.windowOpacity() > 0

    def set_fullscreen(self, enabled, *, windowed_overlay=False):
        over_video = enabled or windowed_overlay
        if enabled == self.property('fullscreen') and over_video == self.property('overVideo'):
            return
        was_composited = self.qt_composited
        if was_composited:
            self.setWindowOpacity(1.0)
        # The presentation may keep the bar hidden until its new geometry is ready.
        visible = not self.isHidden()
        local = QRect(self.parentWidget().mapFromGlobal(self.mapToGlobal(QPoint())), self.size())
        focus = QApplication.focusWidget()
        restore_focus = focus is not None and (focus is self or self.isAncestorOf(focus))
        owner = self.parentWidget().window()
        self._owner_window.removeEventFilter(self)
        self._owner_window = owner
        if over_video:
            owner.installEventFilter(self)
        if not over_video:
            self._mask_label_windows(False)
        self.setProperty('fullscreen', enabled)
        self.setProperty('overVideo', over_video)
        # The gradient owns the video overlay. A normal theme or
        # skin fill under it would turn the alpha layer into a solid rectangle.
        self.setProperty('customControlSurface', over_video)
        self.setAttribute(Qt.WA_StyledBackground, not over_video)
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            if was_composited or not over_video:
                self._release_owned_windows()
                self._masked_labels.clear()
            # Recreate this backing store (and its native input children) when
            # changing alpha modes; Qt can retain layered HWNDs after reparenting.
            self.destroy()
            # A child HWND shares the main window's opaque backing store. Give
            # the complete interactive bar its own Qt-managed alpha backing store.
            self.setAttribute(Qt.WA_TranslucentBackground, over_video)
            self.setAttribute(Qt.WA_NoSystemBackground, over_video)
            if over_video:
                # Qt.Tool uses CS_SAVEBITS on Windows. A fullscreen-width bar
                # must not ask Windows to restore the pixels it covered.
                window_type = Qt.Dialog if enabled and not self.parentWidget().isWindow() else Qt.Tool
                self.setWindowFlags(window_type | Qt.FramelessWindowHint)
            else:
                self.setWindowFlags(Qt.Widget)
            self.set_tile_geometry(local.x(), local.y(), local.width(), local.height())
        for widget in (self, *self.findChildren(QWidget)):
            widget.setProperty('fullscreen', enabled)
            widget.setProperty('overVideo', over_video)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        self.setVisible(visible and (not windowed_overlay or self.parentWidget().isVisible()))
        if restore_focus:
            focus.setFocus(Qt.OtherFocusReason)
        self.refresh_theme()

    def _release_owned_windows(self):
        # Qt keeps these widgets when the bar changes flags, but Windows drops
        # their native owner when the old bar HWND is destroyed.
        owner = self.windowHandle()
        owned = []
        for widget in self.findChildren(QWidget):
            if not widget.isWindow() or not widget.internalWinId():
                continue
            parent = widget.windowHandle().transientParent()
            while parent is not None and parent is not owner:
                parent = parent.transientParent()
            if parent is not None:
                owned.append(widget)
        for widget in reversed(owned):
            widget.hide()
            widget.destroy()

    def set_tile_geometry(self, x, y, width, height):
        self._tile_rect = QRect(x, y, width, height)
        tile = self.parentWidget()
        position = QPoint(x, y)
        if self.qt_composited:
            # An independent tile already has global geometry before Qt exposes it.
            position += tile.geometry().topLeft() if tile.isWindow() else tile.mapToGlobal(QPoint())
        self.setGeometry(QRect(position, self._tile_rect.size()))
        if not self.windowed_overlay:
            if self.qt_composited:
                visible = self._tile_rect.intersected(tile.rect())
                self.setMask(QRegion(visible.translated(-self._tile_rect.topLeft())))
            else:
                self.clearMask()

    def prepare_fullscreen_frame(self):
        if not self.qt_composited:
            return
        # repaint() alone is ignored until the new QWindow receives exposure.
        user32 = ctypes.windll.user32
        user32.RedrawWindow.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT),
                                       wintypes.HRGN, wintypes.UINT)
        # RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW
        user32.RedrawWindow(int(self.winId()), None, None, 0x181)
        self.repaint()

    def tile_y(self):
        return self.parentWidget().mapFromGlobal(self.mapToGlobal(QPoint())).y()

    def sync_owner_position(self):
        if self.qt_composited:
            self.set_tile_geometry(*self._tile_rect.getRect())
        self.sync_windowed_visibility()

    def sync_windowed_visibility(self):
        if not self.windowed_overlay:
            return
        tile = self.parentWidget()
        owner = tile.window()
        auto_hide = getattr(owner, 'settings', {}).get('windowed_auto_hide_controls', False)
        composited = self.qt_composited
        reveal = tile._overlay_visible or not auto_hide
        # A mapped alpha-zero layered window lets pointer input pass through.
        # Keeping the backing store avoids a native show/hide cascade on every
        # tile crossing. A focused bar still unmaps to release keyboard focus.
        keep_mapped = composited and QApplication.activeWindow() is not self
        visible = tile.isVisible() and not owner.isMinimized() and (reveal or keep_mapped)
        settings = getattr(owner, '_settings_process', None) if composited else None
        mask_changed = False
        if visible:
            if composited and self.isHidden():
                self.set_tile_geometry(*self._tile_rect.getRect())
            if tile.wall_seamless:
                region = QRegion(tile.rect())
            else:
                outline = continuous_path(tile.rect().adjusted(1, 1, -1, -1), 9)
                region = QRegion(outline.toFillPolygon().toPolygon())
            region &= self._tile_rect
            region.translate(-self._tile_rect.topLeft())
            if settings is not None and settings.visible and not settings.closing:
                if settings.window_hwnd:
                    region -= QRegion(settings.occlusion.translated(-self.geometry().topLeft()))
                else:
                    region = QRegion()
            dialog = getattr(owner, '_local_settings_dialog', None) if composited else None
            if dialog is not None and dialog.isVisible() and not dialog.isMinimized():
                region -= QRegion(dialog.frameGeometry().translated(-self.geometry().topLeft()))
            # Qt treats an empty window mask as unmasked, so hide a fully covered bar.
            visible = not region.isEmpty()
            mask_changed = visible and region != self.mask()
            if mask_changed:
                self.setMask(region)
        opacity_changed = composited and visible and self.windowOpacity() != float(reveal)
        if opacity_changed:
            self.setWindowOpacity(float(reveal))
        visibility_changed = self.isHidden() == visible
        if visibility_changed:
            self.setVisible(visible)
        if mask_changed or visibility_changed or opacity_changed:
            tile._update_quick_danmaku_mask()

    def refresh_theme(self):
        self.update()

    def _raise_below_owned_windows(self):
        if not self.qt_composited or not self.isVisible():
            return False
        owners = set()
        owner = self._owner_window.windowHandle()
        while owner is not None:
            owners.add(owner)
            owner = owner.transientParent()

        anchors = []
        for widget in QApplication.topLevelWidgets():
            # Video overlays, input-transparent transitions and unpinned
            # fullscreen chats keep their own playback stacking rules.
            if (isinstance(widget, (FullscreenBar, BadgeSurface))
                    or not widget.isVisible() or widget.isMinimized()
                    or widget.testAttribute(Qt.WA_DontShowOnScreen)
                    or widget.windowFlags() & Qt.WindowTransparentForInput
                    or widget.property('behindFullscreen')):
                continue
            window = widget.windowHandle()
            if window is None or window in owners:
                continue
            parent = window.transientParent()
            while parent is not None:
                if parent in owners:
                    anchors.append(int(window.winId()))
                    break
                parent = parent.transientParent()

        host = self._owner_window
        while host.parentWidget() is not None:
            host = host.parentWidget().window()
        settings = getattr(host, '_settings_process', None)
        if settings is not None and settings.visible and not settings.closing and settings.window_hwnd:
            anchors.append(settings.window_hwnd)
        owner = self._owner_window if self.windowed_overlay else None
        return raise_below_native_windows(self, anchors, owner=owner)

    def raise_(self):
        if not self._raise_below_owned_windows():
            super().raise_()

    def _render_badge(self, painter):
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(.32, QColor(0, 0, 0, 12))
        shade.setColorAt(.72, QColor(0, 0, 0, 68))
        shade.setColorAt(1, QColor(0, 0, 0, 146))
        painter.fillRect(self.rect(), shade)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*VIDEO_CONTROL_BACKING))
        for group in self.contrast_groups:
            bounds = QRect()
            for widget in group:
                if not widget.isHidden():
                    bounds = bounds.united(widget.geometry())
            if not bounds.isEmpty():
                inset = self.rect().adjusted(3, 3, -3, -3)
                surface = bounds.adjusted(-5, 0, 5, 0).intersected(inset)
                painter.drawRoundedRect(QRectF(surface), VIDEO_CONTROL_RADIUS, VIDEO_CONTROL_RADIUS)
        painter.restore()

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
        if not self.property('overVideo'):
            QWidget.paintEvent(self, event)
            return
        painter = QPainter(self)
        self._render_badge(painter)
        painter.end()
        self._schedule_label_mask()

    def event(self, event):
        if event.type() == QEvent.ChildAdded and isinstance(event.child(), QWidget):
            event.child().installEventFilter(self)
        elif event.type() in (QEvent.Show, QEvent.WindowActivate) and self.qt_composited:
            # Qt and Windows can raise an owned HWND when mapping or activating it.
            QTimer.singleShot(0, self, self._raise_below_owned_windows)
        return QWidget.event(self, event)

    def eventFilter(self, watched, event):
        if watched is not self._owner_window:
            self._trace_input('child-event', watched, event)
            if event.type() == QEvent.ChildAdded and isinstance(event.child(), QWidget):
                event.child().installEventFilter(self)
        elif self.qt_composited:
            if event.type() == QEvent.Move:
                QTimer.singleShot(0, self, self.sync_owner_position)
            elif self.windowed_overlay and event.type() == QEvent.WindowStateChange:
                QTimer.singleShot(0, self, self.sync_windowed_visibility)
            elif not self.windowed_overlay and event.type() == QEvent.Hide:
                self._owner_hidden_visible = self.isVisible()
                self.hide()
            elif not self.windowed_overlay and event.type() == QEvent.Show and self._owner_hidden_visible:
                self.show()
                self._owner_hidden_visible = False
        return super().eventFilter(watched, event)
