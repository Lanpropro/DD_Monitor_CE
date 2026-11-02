"""Opt-in BUG-070 capture: GUI heartbeat, selected calls and process counters."""
import cProfile
import ctypes
import functools
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def process_counters():
    result = {'cpu_seconds': time.process_time(), 'python_threads': threading.active_count()}
    if sys.platform == 'win32':
        from ctypes import wintypes

        class Memory(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('peak_working', 'working', 'peak_paged',
                    'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]

        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        process = kernel.GetCurrentProcess()
        memory = Memory()
        memory.size = ctypes.sizeof(memory)
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
        if query(process, ctypes.byref(memory), memory.size):
            result.update(working_bytes=memory.working, private_bytes=memory.private)
        handles = wintypes.DWORD()
        kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        if kernel.GetProcessHandleCount(process, ctypes.byref(handles)):
            result['handles'] = handles.value
    return result


def stack_locations(frame):
    locations = []
    while frame is not None and len(locations) < 16:
        path = Path(frame.f_code.co_filename)
        try:
            filename = path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            filename = path.name
        locations.append({'file': filename, 'function': frame.f_code.co_name, 'line': frame.f_lineno})
        frame = frame.f_back
    return locations


def profile_functions(profile):
    """只保留最耗时的函数位置和计数，不记录调用参数或局部变量。"""
    entries = profile.getstats()
    selected = sorted(entries, key=lambda entry: entry.totaltime, reverse=True)[:15]
    for entry in sorted(entries, key=lambda entry: entry.inlinetime, reverse=True)[:15]:
        if entry not in selected:
            selected.append(entry)
    result = []
    for entry in selected:
        code = entry.code
        if isinstance(code, str):
            filename, name, line = '<built-in>', code, 0
        else:
            path = Path(code.co_filename)
            try:
                filename = path.resolve().relative_to(ROOT).as_posix()
            except ValueError:
                filename = path.name
            name, line = code.co_name, code.co_firstlineno
        result.append({'file': filename, 'function': name, 'line': line,
                       'calls': entry.callcount, 'recursive_calls': entry.reccallcount,
                       'self_ms': round(entry.inlinetime * 1000, 3),
                       'total_ms': round(entry.totaltime * 1000, 3)})
    return result


class Probe:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8')
        self.logger = logging.Logger('responsiveness')
        self.logger.addHandler(self.handler)
        self.started = self.last_tick = time.monotonic()
        self.session = str(time.time_ns())
        self.main_thread = threading.get_ident()
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.calls = {}
        self.state = {}
        self.active = []
        self.thread = None

    def write(self, phase, **values):
        self.logger.info(json.dumps({'time': time.time(), 'session': self.session,
            'elapsed_s': round(time.monotonic() - self.started, 3), 'phase': phase, **values}, ensure_ascii=False))

    def pulse(self, window):
        self.last_tick = time.monotonic()
        # Only the Qt thread reads widgets; the sampler reads this plain snapshot.
        self.state = {'tiles': len(window.wall.tiles), 'players': len(window.players),
            'sidebar_items': len(window.sidebar._items), 'layout': window.layout_id,
            'danmaku_clients': len(window._danmaku_clients),
            'retired_clients': len(window._danmaku_retired),
            'snapshot_workers': len(window._super_chat_snapshots)}

    def timed(self, method, label, *, profile_sidebar=False):
        @functools.wraps(method)
        def wrapped(*args, **kwargs):
            if self.stopped.is_set():
                return method(*args, **kwargs)
            started = time.perf_counter()
            self.active.append(label)
            profile = cProfile.Profile() if profile_sidebar else None
            if profile is not None:
                profile.enable()
            try:
                return method(*args, **kwargs)
            finally:
                if profile is not None:
                    profile.disable()
                elapsed = (time.perf_counter() - started) * 1000
                self.active.pop()
                with self.lock:
                    item = self.calls.setdefault(label, {'count': 0, 'total_ms': 0, 'max_ms': 0})
                    item['count'] += 1
                    item['total_ms'] += elapsed
                    item['max_ms'] = max(item['max_ms'], elapsed)
                if elapsed >= 16:
                    self.write('slow-call', function=label, duration_ms=round(elapsed, 3))
                if profile is not None:
                    self.write('sidebar-profile', duration_ms=round(elapsed, 3),
                               functions=profile_functions(profile))
        return wrapped

    def sample(self, now, last_report, last_stack):
        gap = now - self.last_tick
        if gap >= .25 and now - last_stack >= 1:
            frame = sys._current_frames().get(self.main_thread)
            self.write('ui-stall', heartbeat_gap_ms=round(gap * 1000, 3),
                       active=list(self.active), stack=stack_locations(frame))
            del frame
            last_stack = now
        if now - last_report >= 10:
            with self.lock:
                calls, self.calls = self.calls, {}
            self.write('sample', state=self.state, calls=calls, resources=process_counters())
            last_report = now
        return last_report, last_stack

    def start(self):
        self.write('start', interval_ms=100, stall_threshold_ms=250, resources=process_counters())
        self.thread = threading.Thread(target=self._watch, name='responsiveness-probe', daemon=True)
        self.thread.start()

    def _watch(self):
        last_report, last_stack = self.started, 0
        while not self.stopped.wait(.1):
            last_report, last_stack = self.sample(time.monotonic(), last_report, last_stack)

    def stop(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()
        self.write('stop')
        self.handler.close()


def install_theme_capture(path):
    """Measure actual theme changes without a continuous sampler."""
    import atexit
    from .theme_transition import ThemeTransition
    from . import theme

    probe = Probe(path)
    original = ThemeTransition.change

    @functools.wraps(original)
    def change(transition, mode, *args, **kwargs):
        if probe.stopped.is_set():
            return original(transition, mode, *args, **kwargs)
        profile = cProfile.Profile()
        started = time.perf_counter()
        profile.enable()
        try:
            return original(transition, mode, *args, **kwargs)
        finally:
            profile.disable()
            probe.write('theme-switch', mode=theme.normalize_mode(mode),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                functions=profile_functions(profile))

    ThemeTransition.change = change
    atexit.register(probe.stop)
    probe.write('start', mode='theme-switches-only')
    return probe


def install(path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .app import MainWindow
    from .preview import HoverPreview
    from .widgets import Sidebar, WallGrid

    original = MainWindow.__init__
    probe = Probe(path)
    probe.start()
    # Hook before construction: Qt signal connections must receive the wrapped slots.
    for owner, names in ((MainWindow, ('_on_layout_changed', 'sync_danmaku', '_on_status_updated')),
                         (Sidebar, ('set_collapsed', 'set_card_mode', 'refresh_strip', 'reorder_items')),
                         (WallGrid, ('relayout',)), (HoverPreview, ('_check_hover', '_stop_now'))):
        for name in names:
            method = getattr(owner, name)
            label = f'{method.__module__}.{owner.__name__}.{name}'
            setattr(owner, name, probe.timed(method, label,
                    profile_sidebar=owner is Sidebar and name == 'set_collapsed'))

    @functools.wraps(original)
    def initialize(window, *args, **kwargs):
        original(window, *args, **kwargs)
        window._responsiveness_probe = probe
        timer = QTimer(window)
        timer.setInterval(100)
        timer.timeout.connect(lambda: probe.pulse(window))
        QApplication.instance().aboutToQuit.connect(probe.stop)
        window.destroyed.connect(probe.stop)
        probe.pulse(window)
        probe.write('window-ready', state=probe.state)
        timer.start()

    MainWindow.__init__ = initialize
