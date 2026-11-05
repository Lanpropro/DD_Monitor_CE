"""Opt-in startup/scroll timings; reuse the responsiveness heartbeat and log."""
import functools
import threading
import time

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QWidget


class ScrollCapture(QObject):
    def __init__(self, sidebar, probe):
        super().__init__(sidebar)
        self.sidebar, self.probe = sidebar, probe
        self.record = None
        self.wheels = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.finish)
        sidebar.scroll.viewport().installEventFilter(self)
        for axis, bar in (('vertical', sidebar.scroll.verticalScrollBar()),
                          ('horizontal', sidebar.scroll.horizontalScrollBar())):
            bar.valueChanged.connect(lambda value, axis=axis: self.changed(axis, value))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            self.wheels += 1
        return False

    def changed(self, axis, value):
        if self.probe.stopped.is_set():
            return
        if self.record is not None and self.record['axis'] != axis:
            self.finish()
        if self.record is None:
            self.started = time.perf_counter()
            self.record = dict(axis=axis, first_value=value, last_value=value, changes=0,
                               dragging=self.sidebar.drag_session.active)
            self.probe.write('sidebar-scroll-start', **self.record)
        self.record['last_value'] = value
        self.record['changes'] += 1
        self.timer.start()

    def finish(self):
        self.timer.stop()
        record, self.record = self.record, None
        wheels, self.wheels = self.wheels, 0
        if record is not None and not self.probe.stopped.is_set():
            self.probe.write('sidebar-scroll-end', **record, wheel_events=wheels,
                duration_ms=round((time.perf_counter() - self.started) * 1000, 3))


def install(probe):
    from .app import MainWindow
    from .player import TilePlayer, mpv
    from .preview import HoverPreview
    from .widgets import Sidebar

    def timed(method, label, *, binding_only=False):
        wrapped = probe.timed(method, label)
        @functools.wraps(method)
        def gui_only(*args, **kwargs):
            if (threading.get_ident() != probe.main_thread or
                    (binding_only and 'player.bind' not in probe.active)):
                return method(*args, **kwargs)
            return wrapped(*args, **kwargs)
        return gui_only

    # Install before construction so Qt signals connect to the timed slots.
    for owner, names in ((TilePlayer, ('bind', '_destroy_core')),
                         (HoverPreview, ('_begin_resolve', '_on_resolved', '_update_popup_position')),
                         (Sidebar, ('_prepare_drag_snapshot', '_refresh_visible_covers', '_sync_pointer_hover')),
                         (MainWindow, ('start_all', '_start_startup_tiles', 'start_tile', '_play_on'))):
        for name in names:
            label = 'player.bind' if owner is TilePlayer and name == 'bind' else f'{owner.__name__}.{name}'
            setattr(owner, name, timed(getattr(owner, name), label))
    QWidget.winId = timed(QWidget.winId, 'player.native-window', binding_only=True)
    mpv.MPV.__init__ = timed(mpv.MPV.__init__, 'player.core-init', binding_only=True)

    initialize = MainWindow.__init__
    @functools.wraps(initialize)
    def watch(window, *args, **kwargs):
        initialize(window, *args, **kwargs)
        capture = ScrollCapture(window.sidebar, probe)
        window._startup_scroll_capture = capture
        window.destroyed.connect(capture.finish)
        probe.write('startup-scroll-ready')
    MainWindow.__init__ = watch
