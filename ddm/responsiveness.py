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


def install_theme_capture(path, *, profile_calls=False):
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
        profile = cProfile.Profile() if profile_calls else None
        started = time.perf_counter()
        transition._theme_request_started = started
        if profile is not None:
            profile.enable()
        try:
            return original(transition, mode, *args, **kwargs)
        finally:
            if profile is not None:
                profile.disable()
            probe.write('theme-switch', mode=theme.normalize_mode(mode),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                functions=profile_functions(profile) if profile is not None else [])

    ThemeTransition.change = change
    atexit.register(probe.stop)
    probe.write('start', mode='theme-switches-only')
    return probe


def install_theme_animation_capture(probe):
    """Bounded GUI-thread frame timings, separate from preparation costs."""
    from .theme_transition import ThemeTransition, WaveOverlay

    original_start = ThemeTransition._start_animation
    original_frame = ThemeTransition._frame
    original_finish = ThemeTransition.finish
    original_paint = WaveOverlay.paintEvent

    def start(transition):
        result = original_start(transition)
        if not probe.stopped.is_set() and transition.animation.state().name == 'Running':
            started = time.perf_counter()
            requested = getattr(transition, '_theme_request_started', None)
            record = {'started': started, 'frames': [], 'bitmap_paints': 0,
                'ready_ms': round((started - requested) * 1000, 3) if requested is not None else None}
            transition._motion_capture = record
            for overlay in transition.overlays:
                overlay._motion_capture = record
        return result

    def frame(transition, progress):
        record = getattr(transition, '_motion_capture', None)
        started = time.perf_counter()
        try:
            return original_frame(transition, progress)
        finally:
            if record is not None and len(record['frames']) < 40:
                record['frames'].append({'at_ms': round((started - record['started']) * 1000, 3),
                    'work_ms': round((time.perf_counter() - started) * 1000, 3),
                    'progress': round(float(progress), 5), 'overlays': len(transition.overlays),
                    'quick_overlays': sum(getattr(overlay, 'render_thread', False) for overlay in transition.overlays),
                    'caption_overlays': sum(getattr(overlay, 'caption_height', 0) > 0 for overlay in transition.overlays),
                    'native_overlays': sum(overlay._native_clip for overlay in transition.overlays)})

    def paint(overlay, event):
        record = getattr(overlay, '_motion_capture', None)
        if record is not None:
            record['bitmap_paints'] += 1
        return original_paint(overlay, event)

    def finish(transition):
        record = getattr(transition, '_motion_capture', None)
        transition._motion_capture = None
        progress = transition.progress
        try:
            return original_finish(transition)
        finally:
            if record is not None and not probe.stopped.is_set():
                probe.write('theme-animation', reason='complete' if progress >= 1 else 'interrupted',
                    duration_ms=round((time.perf_counter() - record['started']) * 1000, 3),
                    ready_ms=record['ready_ms'], frames=record['frames'], bitmap_paints=record['bitmap_paints'])

    ThemeTransition._start_animation = start
    ThemeTransition._frame = frame
    ThemeTransition.finish = finish
    WaveOverlay.paintEvent = paint


class FolderMotionCapture:
    """Record bounded layout/position evidence only around a real folder click."""
    def __init__(self, probe, sidebar):
        from PySide6.QtCore import QTimer
        self.probe, self.sidebar = probe, sidebar
        self.record = None
        self.timer = QTimer(sidebar)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.frame)
        self.toggle = sidebar.toggle_folder
        self.relayout = sidebar.list_box.relayout
        sidebar.toggle_folder = self.toggle_folder
        sidebar.list_box.relayout = self.layout

    def toggle_folder(self, folder_id, *, animate=False):
        if self.probe.stopped.is_set():
            return self.toggle(folder_id, animate=animate)
        self.finish('superseded')
        folder = self.sidebar.get_folder(folder_id)
        if folder is None:
            return self.toggle(folder_id, animate=animate)
        self.started = time.perf_counter()
        self.record = {'folder_index': self.sidebar.folders.index(folder),
            'opening': bool(folder['collapsed']), 'animate_requested': bool(animate),
            'side': self.sidebar.side, 'card_mode': self.sidebar.card_mode,
            'frames': [], 'layouts': []}
        self.entries = list(self.sidebar._items) + list(self.sidebar._folder_buttons.values())
        self.entries += list(self.sidebar._smart_cards.values())
        self.frame()
        try:
            result = self.toggle(folder_id, animate=animate)
        except BaseException:
            self.finish('error')
            raise
        self.record['toggle_ms'] = round((time.perf_counter() - self.started) * 1000, 3)
        for entry in self.sidebar._smart_cards.values():
            if entry not in self.entries:
                self.entries.append(entry)
        self.frame()
        if self.record is not None:
            self.timer.start()
        return result

    def layout(self, *args, **kwargs):
        record = self.record
        if record is None or self.probe.stopped.is_set():
            return self.relayout(*args, **kwargs)
        running = self.running_animations()
        started = time.perf_counter()
        callers = stack_locations(sys._getframe(1))[:6]
        try:
            return self.relayout(*args, **kwargs)
        finally:
            if len(record['layouts']) < 24:
                record['layouts'].append({'at_ms': round((started - self.started) * 1000, 3),
                    'duration_ms': round((time.perf_counter() - started) * 1000, 3),
                    'animate': bool(kwargs.get('animate', args[0] if args else False)),
                    'running_before': running, 'callers': callers})

    def running_animations(self):
        running = 0
        for animation in self.sidebar.list_box._animations.values():
            try:
                running += animation.state().name == 'Running'
            except RuntimeError:  # Removing a room/folder deletes its child animations.
                continue
        return running

    def frame(self):
        record = self.record
        if record is None:
            return
        if self.probe.stopped.is_set():
            self.timer.stop()
            self.record = None
            return
        sidebar = self.sidebar
        elapsed = (time.perf_counter() - self.started) * 1000
        bar = sidebar.scroll.horizontalScrollBar() if sidebar.side == 'top' else sidebar.scroll.verticalScrollBar()
        viewport = sidebar.scroll.viewport()
        # Numbers are capture-local row indexes, never room IDs or folder names.
        rows = []
        stacking = {child: index for index, child in enumerate(sidebar.list_box.children())}
        for index, entry in enumerate(self.entries):
            try:
                if entry.isHidden():
                    continue
                rect = entry.geometry()
                along = rect.x() if sidebar.side == 'top' else rect.y()
                extent = rect.width() if sidebar.side == 'top' else rect.height()
                span = viewport.width() if sidebar.side == 'top' else viewport.height()
                if along + extent < bar.value() or along > bar.value() + span:
                    continue
                animation = sidebar.list_box._animations.get(entry)
                target = animation.endValue() if animation is not None else entry.pos()
                rows.append({'row': index, 'rect': list(rect.getRect()),
                    'stack': stacking.get(entry), 'target': [target.x(), target.y()],
                    'animation_ms': [animation.currentTime(), animation.duration()]
                        if animation is not None else None})
            except RuntimeError:  # A smart-folder copy can be deleted during refresh.
                continue
            if len(rows) == 16:
                break
        record['frames'].append({'at_ms': round(elapsed, 3), 'scroll': bar.value(),
            'scroll_max': bar.maximum(), 'content': [sidebar.list_box.width(), sidebar.list_box.height()],
            'running': self.running_animations(),
            'rows': rows})
        if elapsed >= 600 or len(record['frames']) >= 40:
            self.finish('complete')

    def finish(self, reason='closing'):
        self.timer.stop()
        record, self.record = self.record, None
        if record is not None and not self.probe.stopped.is_set():
            self.probe.write('folder-motion', reason=reason, **record)


def install_folder_capture(path):
    """Source launcher: capture folder clicks without the full responsiveness profiler."""
    from PySide6.QtWidgets import QApplication
    from .app import MainWindow

    original = MainWindow.__init__

    @functools.wraps(original)
    def initialize(window, *args, **kwargs):
        original(window, *args, **kwargs)
        probe = Probe(path)
        window._folder_motion_probe = FolderMotionCapture(probe, window.sidebar)
        QApplication.instance().aboutToQuit.connect(window._folder_motion_probe.finish)
        QApplication.instance().aboutToQuit.connect(probe.stop)
        window.destroyed.connect(probe.stop)
        probe.write('start', mode='folders-only')

    MainWindow.__init__ = initialize


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
        window._folder_motion_probe = FolderMotionCapture(probe, window.sidebar)
        timer = QTimer(window)
        timer.setInterval(100)
        timer.timeout.connect(lambda: probe.pulse(window))
        QApplication.instance().aboutToQuit.connect(window._folder_motion_probe.finish)
        QApplication.instance().aboutToQuit.connect(probe.stop)
        window.destroyed.connect(probe.stop)
        probe.pulse(window)
        probe.write('window-ready', state=probe.state)
        timer.start()

    MainWindow.__init__ = initialize
