"""Opt-in pointer and Qt hover evidence for the sidebar's function rail."""
import os
import sys
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QAbstractButton, QApplication
from shiboken6 import isValid

from .dock_feedback import active, hovered


def native_hit():
    if sys.platform != 'win32' or QApplication.platformName() != 'windows':
        return None
    from ctypes import byref, wintypes
    from .drag_diagnostics import native_window, user32

    point = wintypes.POINT()
    if user32.GetCursorPos(byref(point)) and (hwnd := user32.WindowFromPoint(point)):
        info = native_window(hwnd, properties=False)
        return dict(hwnd=info['hwnd'], windowClass=info['cls'], sameProcess=info['pid'] == os.getpid())
    return None


class DockHoverTrace(QObject):
    MAX_RECORDS = 5000
    EVENTS = (QEvent.Enter, QEvent.Leave, QEvent.HoverEnter, QEvent.HoverLeave,
              QEvent.Show, QEvent.Hide, QEvent.ActionChanged, QEvent.Paint)

    def __init__(self, window, emit, done=None):
        super().__init__(window)
        self.window = window
        self.rail = window.sidebar.navigation.rail
        self.record = emit
        self.done = done
        self.count = 0
        self.closed = False
        self.button = None
        self.saw_hover = False
        self.misses = 0
        self.last_sample = None
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.sample_pointer)

    def start(self):
        self.started = self.last_tick = time.monotonic()
        self.emit('dock-hover-armed')
        QApplication.instance().installEventFilter(self)
        self.timer.start()

    def emit(self, stage, **data):
        self.count += 1
        self.record(stage, **data)
        if self.count >= self.MAX_RECORDS:
            self.record('dock-hover-limit', limit=self.MAX_RECORDS)
            self.finish('limit')

    def button_at(self, widget):
        if widget is None or not self.rail.isAncestorOf(widget):
            return None
        while widget is not self.rail:
            if isinstance(widget, QAbstractButton) and hasattr(widget, '_dock_feedback'):
                return widget
            widget = widget.parentWidget()
        return None

    def button_state(self, button):
        entries = self.window.sidebar.workspace_controls.entries
        plugin = next((identity for identity, (_, widget) in entries.items() if widget is button), None)
        role = ':'.join(plugin) if plugin else getattr(button, 'kind', type(button).__name__)
        return dict(button=role, buttonId=id(button), underMouse=button.underMouse(),
                    hoverProperty=button.property('hovered'), effectiveHover=hovered(button), selected=active(button),
                    enabled=button.isEnabled(), visible=button.isVisible())

    def sample_pointer(self):
        if self.closed:
            return
        now, previous = time.monotonic(), self.last_tick
        if self.done is not None and now - self.started >= 60:
            self.finish('timeout')
            return
        self.last_tick = now
        app = QApplication.instance()
        point = QCursor.pos()
        local = self.rail.mapFromGlobal(point)
        in_rail = (self.rail.isVisible() and not self.window.isMinimized()
                   and self.rail.rect().contains(local))
        button = self.button_at(self.rail.childAt(local)) if in_rail else None
        if button is not self.button:
            self.button = button
            self.saw_hover = False
            self.misses = 0
        sample = dict(button=None, inRail=in_rail)
        if in_rail:
            sample['position'] = local.toTuple()
        if button is not None:
            hit = app.widgetAt(point)
            actual = self.button_at(hit)
            if actual is button:
                qt_hit = 'button'
            elif actual is not None:
                qt_hit = 'other-button'
            elif hit is None:
                qt_hit = 'none'
            else:
                qt_hit = 'owner' if hit.window() is self.window else 'other-window'
            sample.update(self.button_state(button),
                          rect=(*button.mapTo(self.rail, QPoint()).toTuple(), *button.size().toTuple()),
                          qtHit=qt_hit, nativeHit=native_hit(), scale=self.rail.devicePixelRatioF(),
                          windowActive=self.window.isActiveWindow(), popup=app.activePopupWidget() is not None,
                          modal=app.activeModalWidget() is not None, pressed=bool(app.mouseButtons()))
            eligible = (actual is button and sample['enabled'] and not sample['selected']
                        and not (sample['popup'] or sample['modal'] or sample['pressed']))
            self.saw_hover |= eligible and sample['effectiveHover']
            self.misses = self.misses + 1 if eligible and not sample['effectiveHover'] else 0
        if sample != self.last_sample:
            self.last_sample = sample
            self.emit('dock-hover-pointer', gapMs=round((now - previous) * 1000, 1), **sample)
        if not self.closed and self.misses == 2:
            reason = 'lost-while-inside' if self.saw_hover else 'missing-on-entry'
            self.emit('dock-hover-mismatch', reason=reason, **sample)
            if self.done is not None:
                self.finish('mismatch-found')

    def eventFilter(self, watched, event):
        kind = event.type()
        if (not self.closed and kind in self.EVENTS and isinstance(watched, QAbstractButton)
                and self.button_at(watched) is watched
                and (kind not in (QEvent.ActionChanged, QEvent.Paint) or watched is self.button)):
            self.emit('dock-hover-event', event=kind.name, **self.button_state(watched))
        return False

    def stop(self):
        if self.closed:
            return
        self.closed = True
        if isValid(self.timer):
            self.timer.stop()
        app = QApplication.instance()
        if app is not None and isValid(app) and isValid(self):
            app.removeEventFilter(self)
        self.deleteLater()

    def finish(self, reason):
        if self.closed:
            return
        self.stop()
        if self.done is not None:
            self.done(reason)
