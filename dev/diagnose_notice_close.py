"""Opt-in GUI-only notice lifecycle capture; no message text or account data."""
import ctypes
from ctypes import wintypes
import functools
import json
import os
from pathlib import Path
import time
import weakref

from PySide6.QtCore import QObject, QTimer
from shiboken6 import isValid


class NoticeCloseTrace(QObject):
    LIMIT = 2000

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.session = f'{os.getpid()}-{time.time_ns()}'
        self.started = time.perf_counter()
        self.count = 0
        self.targets = {}
        self.last_sample = None
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.sample)

    def record(self, stage, notice, **extra):
        if self.count >= self.LIMIT or id(notice) not in self.targets or not isValid(notice):
            return
        hwnd = int(notice.internalWinId())  # Read only; never create a native handle.
        native_visible = None
        if hwnd and os.name == 'nt':
            function = ctypes.windll.user32.IsWindowVisible
            function.argtypes = (wintypes.HWND,)
            native_visible = bool(function(hwnd))
        row = dict(session=self.session, at_ms=round((time.perf_counter() - self.started) * 1000, 3),
                   stage=stage, id=id(notice), hwnd=hex(hwnd), visible=notice.isVisible(),
                   native_visible=native_visible, opacity=notice.windowOpacity(),
                   geometry=list(notice.geometry().getRect()), leaving=notice._leaving,
                   progress=notice._progress, animation=notice._motion.state().name,
                   animation_ms=notice._motion.currentTime(), duration_ms=notice._motion.duration(),
                   timer=notice.timer.isActive(), stack_size=len(getattr(notice.parentWidget(), '_notices', [])),
                   **extra)
        self.count += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row) + '\n')

    def watch(self, notice):
        if self.count >= self.LIMIT:
            return
        if len(self.targets) >= 6:
            self.targets.pop(next(iter(self.targets)))
        self.targets[id(notice)] = (weakref.ref(notice), time.perf_counter() + 5)
        if not self.timer.isActive():
            self.last_sample = time.perf_counter()
            self.timer.start()

    def sample(self):
        now = time.perf_counter()
        gap = round((now - self.last_sample) * 1000, 3)
        self.last_sample = now
        for identifier, (reference, until) in list(self.targets.items()):
            notice = reference()
            if notice is None or not isValid(notice) or now >= until or self.count >= self.LIMIT:
                self.targets.pop(identifier)
            else:
                self.record('sample', notice, event_loop_gap_ms=gap)
        if not self.targets:
            self.timer.stop()

    def install(self):
        from ddm.online_ui import UpdateNotice
        trace = self
        for name in ('dismiss', '_motion_frame', '_motion_finished', 'showEvent', 'hideEvent'):
            original = getattr(UpdateNotice, name)
            def wrap(method, label):
                @functools.wraps(method)
                def call(notice, *args, **kwargs):
                    started = time.perf_counter()
                    if label == 'dismiss' and kwargs.get('handled', False):
                        trace.watch(notice)
                    trace.record(label + ':before', notice,
                                 handled=bool(kwargs.get('handled', False)))
                    try:
                        return method(notice, *args, **kwargs)
                    finally:
                        trace.record(label + ':after', notice,
                                     method_ms=round((time.perf_counter() - started) * 1000, 3))
                return call
            setattr(UpdateNotice, name, wrap(original, name))
