"""Opt-in timings for actual settings opening, page creation and embedding."""
import atexit
import cProfile
import functools
import os
from pathlib import Path
import time
from logging.handlers import QueueHandler, QueueListener
from queue import SimpleQueue

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from .responsiveness_probe import Probe, profile_functions


class SettingsProbe(Probe):
    def __init__(self, path, *, profile_calls=False):
        self.records = 0
        self.profile_counts = {}
        self.profiling = False
        self.profile_calls = profile_calls
        super().__init__(path)
        # Disk writes must not hold the GUI behind the sampler's log lock.
        self.output_handler = self.handler
        self.logger.removeHandler(self.handler)
        queue = SimpleQueue()
        self.handler = QueueHandler(queue)
        self.logger.addHandler(self.handler)
        self.listener = QueueListener(queue, self.output_handler)
        self.listener.start()

    def stop(self):
        if self.stopped.is_set():
            return
        super().stop()
        self.listener.stop()
        self.output_handler.close()

    def write(self, phase, **values):
        if self.records < 1200 and (not self.stopped.is_set() or phase == 'stop'):
            self.records += 1
            super().write(phase, pid=os.getpid(), **values)

    def wrap(self, cls, name):
        method = getattr(cls, name)

        @functools.wraps(method)
        def measured(owner, *args, **kwargs):
            if self.stopped.is_set():
                return method(owner, *args, **kwargs)
            label = f'{cls.__name__}.{name}'
            count = self.profile_counts.get(label, 0)
            # Nested scopes share the outer profile; never replace its profiler.
            profile = cProfile.Profile() if self.profile_calls and not self.profiling and count < 20 else None
            self.profile_counts[label] = count + 1
            started = time.perf_counter()
            self.active.append(label)
            if profile is not None:
                self.profiling = True
                profile.enable()
            try:
                return method(owner, *args, **kwargs)
            finally:
                if profile is not None:
                    profile.disable()
                    self.profiling = False
                elapsed = (time.perf_counter() - started) * 1000
                self.active.pop()
                if elapsed >= 16 or count == 0:
                    fields = {}
                    if name in ('_page', '_on_page_changed') and args:
                        fields['page'] = int(args[0])
                    if name == 'handle' and args:
                        # Protocol names only; never record settings or input text.
                        kind = args[0].get('kind')
                        if kind in ('open', 'host-page', 'host-ready', 'host-attached',
                                    'host-shown', 'host-state'):
                            fields['message'] = kind
                    self.write('settings-call', function=label, duration_ms=round(elapsed, 3),
                               functions=profile_functions(profile) if profile is not None else [],
                               **fields)

        setattr(cls, name, measured)


class SettingsPaintCapture(QObject):
    def eventFilter(self, widget, event):
        if event.type() not in (QEvent.Show, QEvent.Paint) or not isinstance(widget, QWidget):
            return False
        from .dialogs import SettingsDialog
        from .motion import SettingsStack
        parent = widget.parentWidget()
        if not isinstance(widget, SettingsDialog) and not isinstance(parent, SettingsStack):
            return False
        if event.type() == QEvent.Show:
            widget.setProperty('_settings_capture_show', time.perf_counter())
        else:
            started = widget.property('_settings_capture_show')
            if started is not None:
                widget.setProperty('_settings_capture_show', None)
                self.parent()._settings_performance.write('first-paint',
                    widget=type(widget).__name__,
                    page=parent.indexOf(widget) if isinstance(parent, SettingsStack) else None,
                    show_to_paint_ms=round((time.perf_counter() - started) * 1000, 3))
        return False


def install(role):
    if os.environ.get('DDM_SETTINGS_PERFORMANCE_CAPTURE') != '1':
        return None
    app = QApplication.instance()
    existing = getattr(app, '_settings_performance', None)
    if existing is not None:
        return existing
    from . import config
    from .dialogs import SettingsDialog
    from .settings_window import SettingsWindow
    from .settings_autosave import SettingsAutoSave
    root = os.environ.get('DDM_DIAGNOSTIC_APP_ROOT') or config.data_root()
    directory = os.environ.get('DDM_DIAGNOSTIC_LOG_DIR') or str(Path(root) / 'logs')
    probe = SettingsProbe(Path(directory) / f'settings-performance-{os.getpid()}.jsonl',
                          profile_calls=os.environ.get('DDM_SETTINGS_PERFORMANCE_PROFILE') == '1')
    app._settings_performance = probe
    for cls, names in (
        (SettingsDialog, ('__init__', '_page', '_on_page_changed')),
        (SettingsWindow, ('_sync_frame',)),
        (SettingsAutoSave, ('start', 'watch_page', 'flush')),
    ):
        for name in names:
            probe.wrap(cls, name)
    if role == 'host':
        from .settings_host import SettingsHost
        from .settings_process import SettingsProcess
        for cls, names in ((SettingsHost, ('__init__', 'handle', 'sync')),
                           (SettingsProcess, ('open', '_open_pending', '_read'))):
            for name in names:
                probe.wrap(cls, name)
    app._settings_paint_capture = SettingsPaintCapture(app)
    app.installEventFilter(app._settings_paint_capture)
    timer = QTimer(app)
    timer.setInterval(100)
    timer.timeout.connect(lambda: setattr(probe, 'last_tick', time.monotonic()))
    timer.start()
    app._settings_performance_timer = timer
    app.aboutToQuit.connect(probe.stop)
    app.destroyed.connect(probe.stop)
    atexit.register(probe.stop)
    probe.start()
    probe.write('settings-capture', role=role, profile_calls=probe.profile_calls,
                profile_limit_per_function=20)
    return probe
