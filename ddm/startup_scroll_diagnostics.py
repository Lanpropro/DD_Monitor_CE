"""Opt-in startup/scroll timings; reuse the responsiveness heartbeat and log."""
import functools
from inspect import CO_VARARGS, CO_VARKEYWORDS
import threading
import time

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QWidget


class StartupEvents:
    """Bracket Qt/C++ dispatch that does not appear in Python method timings."""
    def __init__(self, probe):
        self.probe = probe
        self.enabled = False
        self.depth = 0
        self.records = {}

    def start(self, window):
        self.enabled = True
        self.deadline = time.monotonic() + 12
        QTimer.singleShot(12000, window, self.finish)

    def finish(self):
        if not self.enabled:
            return
        self.enabled = False
        if not self.probe.stopped.is_set():
            self.probe.write('startup-qt-summary', events=sorted(self.records.values(),
                key=lambda item: item['total_ms'], reverse=True)[:20])
        self.records.clear()

    def dispatch(self, notify, receiver, event):
        if (not self.enabled or self.probe.stopped.is_set() or self.depth
                or threading.get_ident() != self.probe.main_thread):
            return notify(receiver, event)
        if time.monotonic() >= self.deadline:
            self.finish()
            return notify(receiver, event)
        # Capture type values before delivery: dispatch may delete the receiver/event.
        kind, event_type = type(receiver).__name__, event.type()
        self.depth += 1
        self.probe.active.append('Qt.notify')
        started = time.perf_counter()
        try:
            return notify(receiver, event)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.probe.active.pop()
            self.depth -= 1
            key = (kind, event_type.name)
            record = self.records.setdefault(key, dict(receiver_class=kind,
                event_type=event_type.name, count=0, total_ms=0, max_ms=0))
            record['count'] += 1
            record['total_ms'] += elapsed
            record['max_ms'] = max(record['max_ms'], elapsed)
            if elapsed >= 16:
                self.probe.write('startup-qt-event', receiver_class=kind,
                    event_type=event_type.name, duration_ms=round(elapsed, 3))


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
    from . import app as app_module
    from .app import MainWindow
    from .player import TilePlayer, mpv
    from .preview import HoverPreview
    from .video_surface import VideoSurface
    from .widgets import Sidebar

    events = StartupEvents(probe)
    application_type = app_module.QApplication
    class Application(application_type):
        def notify(self, receiver, event):
            return events.dispatch(super().notify, receiver, event)
    Application._startup_event_capture = events
    if application_type.instance() is None:
        app_module.QApplication = Application

    def timed(method, label, *, binding_only=False):
        wrapped = probe.timed(method, label)
        @functools.wraps(method)
        def gui_only(*args, **kwargs):
            if (threading.get_ident() != probe.main_thread or
                    (binding_only and 'player.bind' not in probe.active)):
                return method(*args, **kwargs)
            return wrapped(*args, **kwargs)
        code = getattr(method, '__code__', None)
        if (code is not None and code.co_argcount == 1 and code.co_kwonlyargcount == 0
                and not code.co_flags & (CO_VARARGS | CO_VARKEYWORDS)):
            # PySide uses the callable's positional arity to drop surplus signal
            # arguments. A *args wrapper would forward valueChanged(int) to a
            # no-argument slot and raise on every scroll.
            @functools.wraps(method)
            def qt_slot(self):
                return gui_only(self)
            return qt_slot
        return gui_only

    # Install before construction so Qt signals connect to the timed slots.
    for owner, names in ((TilePlayer, ('bind', '_destroy_core')),
                         (VideoSurface, ('_clip_native_video',)),
                         (HoverPreview, ('_begin_resolve', '_on_resolved', '_update_popup_position')),
                         (Sidebar, ('_prepare_drag_snapshot', '_refresh_visible_covers', '_sync_pointer_hover')),
                         (MainWindow, ('start_all', '_start_startup_tiles', 'start_tile', '_play_on',
                                       'load_room_avatars'))):
        for name in names:
            label = 'player.bind' if owner is TilePlayer and name == 'bind' else f'{owner.__name__}.{name}'
            setattr(owner, name, timed(getattr(owner, name), label))
    QWidget.winId = timed(QWidget.winId, 'player.native-window', binding_only=True)
    mpv.MPV.__init__ = timed(mpv.MPV.__init__, 'player.core-init', binding_only=True)

    on_player_state = MainWindow._on_player_state
    @functools.wraps(on_player_state)
    def player_state(window, tile, state):
        result = on_player_state(window, tile, state)
        if (threading.get_ident() == probe.main_thread and not probe.stopped.is_set()
                and tile in window.wall.tiles):
            probe.write('startup-player-state', tile_index=window.wall.tiles.index(tile), state=state)
        return result
    MainWindow._on_player_state = player_state

    initialize = MainWindow.__init__
    @functools.wraps(initialize)
    def watch(window, *args, **kwargs):
        initialize(window, *args, **kwargs)
        capture = ScrollCapture(window.sidebar, probe)
        window._startup_scroll_capture = capture
        window._startup_event_capture = events
        events.start(window)
        window.destroyed.connect(capture.finish)
        probe.write('startup-scroll-ready')
    MainWindow.__init__ = watch
