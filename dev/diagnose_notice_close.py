"""Opt-in GUI-only notice lifecycle capture; no message text or account data."""
import ctypes
from ctypes import wintypes
import functools
import json
import os
from pathlib import Path
import time
import weakref

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QPushButton
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
        self.capture_until = 0
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
        kind = {'开播提醒': 'live', '版本更新': 'update', '操作提示': 'info',
                '需要留意': 'warning'}.get(notice.category.text(), 'other')
        artwork = getattr(getattr(notice, 'artwork', None), 'source', None)
        row = dict(session=self.session, at_ms=round((time.perf_counter() - self.started) * 1000, 3),
                   stage=stage, kind=kind, id=id(notice), hwnd=hex(hwnd), visible=notice.isVisible(),
                   native_visible=native_visible, opacity=notice.windowOpacity(),
                   geometry=list(notice.geometry().getRect()), leaving=notice._leaving,
                   progress=notice._progress, animation=notice._motion.state().name,
                   animation_ms=notice._motion.currentTime(), duration_ms=notice._motion.duration(),
                   timer=notice.timer.isActive(), timer_remaining_ms=notice.timer.remainingTime(),
                   stack_size=len(getattr(notice.parentWidget(), '_notices', [])),
                   history_links=len(notice._history_entries), updates=notice.updatesEnabled(),
                   artwork_key=artwork.cacheKey() if artwork is not None else None,
                   **extra)
        self.count += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row) + '\n')

    def watch(self, notice, *, trigger=True):
        if self.count >= self.LIMIT:
            return
        if trigger:
            self.capture_until = time.perf_counter() + 5
        elif time.perf_counter() >= self.capture_until:
            return
        if len(self.targets) >= 6:
            self.targets.pop(next(iter(self.targets)))
        self.targets[id(notice)] = (weakref.ref(notice), self.capture_until)
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

    def eventFilter(self, watched, event):
        if (event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
                and event.button() == Qt.LeftButton):
            notice = watched.window()
            self.watch(notice)
            self.record('button:' + event.type().name, notice,
                        button_down=watched.isDown(), inside=watched.rect().contains(event.position().toPoint()),
                        global_position=[event.globalPosition().x(), event.globalPosition().y()])
        return False

    def install(self):
        from ddm.online_ui import UpdateNotice, ResultNotice
        trace = self
        original_init = UpdateNotice.__init__
        @functools.wraps(original_init)
        def initialize(notice, *args, **kwargs):
            original_init(notice, *args, **kwargs)
            button = notice.findChild(QPushButton, 'NoticeClose')
            button.installEventFilter(trace)
            reference = weakref.ref(notice)
            def clicked():
                item = reference()
                if item is not None:
                    trace.record('button:clicked', item)
            button.clicked.connect(clicked)
        UpdateNotice.__init__ = initialize
        hooks = ((UpdateNotice, ('dismiss', '_motion_frame', '_motion_finished', 'showEvent', 'hideEvent')),
                 (ResultNotice, ('show_message', 'set_room_artwork', 'set_room_avatar',
                                 '_motion_frame', 'reposition', 'paintEvent')))
        def wrap(method, label):
            @functools.wraps(method)
            def call(notice, *args, **kwargs):
                if label.endswith('.dismiss') and kwargs.get('handled', False):
                    trace.watch(notice)
                elif label.endswith('.show_message'):
                    trace.watch(notice, trigger=False)
                trace.record(label + ':before', notice,
                             handled=bool(kwargs.get('handled', False)))
                started = time.perf_counter()
                try:
                    return method(notice, *args, **kwargs)
                finally:
                    trace.record(label + ':after', notice,
                                 method_ms=round((time.perf_counter() - started) * 1000, 3))
            return call
        for owner, names in hooks:
            for name in names:
                setattr(owner, name, wrap(getattr(owner, name), owner.__name__ + '.' + name))
