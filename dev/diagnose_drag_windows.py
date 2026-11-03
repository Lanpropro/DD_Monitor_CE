"""Temporary BUG-001 recurrence trace, enabled by the source run.cmd launcher.

Remove this entry and the launcher redirect once the native drag cause is fixed.
"""
import ctypes
from ctypes import wintypes
from datetime import datetime
import functools
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import runpy
import sys
import threading
import time
import traceback
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / 'main.py'), run_name='diagnostic_bootstrap')
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid
from ddm.app import MainWindow

user32 = ctypes.WinDLL('user32', use_last_error=True)
ole32 = ctypes.WinDLL('ole32')
EnumWindowProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumPropertyProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, ctypes.c_void_p,
                                     wintypes.HANDLE, ctypes.c_size_t)
user32.EnumWindows.argtypes = [EnumWindowProc, wintypes.LPARAM]
user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumWindowProc, wintypes.LPARAM]
user32.EnumPropsExW.argtypes = [wintypes.HWND, EnumPropertyProc, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
ole32.CoGetApartmentType.argtypes = [ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
ole32.CoGetApartmentType.restype = ctypes.c_long


def native_window(hwnd, *, properties=True):
    pid = wintypes.DWORD()
    thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, name, len(name))
    result = dict(hwnd=hex(hwnd), pid=pid.value, thread=thread, cls=name.value,
                  parent=hex(user32.GetParent(hwnd) or 0), valid=bool(user32.IsWindow(hwnd)),
                  visible=bool(user32.IsWindowVisible(hwnd)))
    if properties and pid.value == os.getpid():
        props = {}
        @EnumPropertyProc
        def each_property(window, key, value, unused):
            if key and key > 65535:
                text = ctypes.wstring_at(key)
                if any(token in text.lower() for token in ('ole', 'drop', 'marshal')):
                    props[text] = hex(value or 0)
            return True
        user32.EnumPropsExW(hwnd, each_property, 0)
        result['oleProperties'] = props
    return result


def windows():
    handles = set()
    @EnumWindowProc
    def visit(hwnd, unused):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            handles.add(hwnd)
        return True
    @EnumWindowProc
    def top(hwnd, unused):
        visit(hwnd, unused)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            user32.EnumChildWindows(hwnd, visit, 0)
        return True
    user32.EnumWindows(top, 0)
    previous = None
    while True:
        hwnd = user32.FindWindowExW(wintypes.HWND(-3), previous, None, None)
        if not hwnd:
            break
        visit(hwnd, 0)
        previous = hwnd
    return [native_window(hwnd) for hwnd in sorted(handles)]


class DragStallProbe:
    """Sample only the GUI Python stack during one drag; never read Qt or locals."""

    def __init__(self):
        self.thread_id = threading.get_ident()
        self.last_tick = time.perf_counter()
        self.samples = []
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._sample, name='drag-stall-probe', daemon=True)
        self.thread.start()

    def pulse(self):
        self.last_tick = time.perf_counter()

    def _sample(self):
        released_at, sampled_at = None, 0.0
        while not self.stopped.wait(.05):
            now = time.perf_counter()
            down = bool(user32.GetAsyncKeyState(1) & 0x8000)
            released_at = None if down else released_at or now
            reason = ('heartbeat-delay' if now - self.last_tick >= .15 else
                      'left-released' if released_at is not None and now - released_at >= .15 else None)
            if reason is None or now - sampled_at < .2 or len(self.samples) >= 8:
                continue
            frames = []
            frame = sys._current_frames().get(self.thread_id)
            try:
                while frame is not None and len(frames) < 16:
                    frames.append(dict(file=Path(frame.f_code.co_filename).name,
                                       function=frame.f_code.co_name, line=frame.f_lineno))
                    frame = frame.f_back
            finally:
                del frame
            self.samples.append(dict(time=time.time(), phase='drag:stall-stack', reason=reason,
                gapMs=round((now - self.last_tick) * 1000, 3), nativeLeftDown=down, frames=frames))
            sampled_at = now

    def finish(self):
        self.stopped.set()
        self.thread.join(.2)
        return list(self.samples)


class Recorder:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = RotatingFileHandler(self.path, maxBytes=5 * 1024 * 1024,
                                          backupCount=3, encoding='utf-8')
        self.logger = logging.Logger('ddm.dragtrace')
        self.logger.addHandler(self.handler)
        self.sequence = 0
        self._last_com = None
        self._last_write_ms = 0.0
        self._gesture = 0
        self._press_at = None

    def write(self, record):
        started = time.perf_counter()
        self.logger.info(json.dumps(dict(record, pid=os.getpid(),
            previousWriteMs=round(self._last_write_ms, 3)), ensure_ascii=True))
        self._last_write_ms = (time.perf_counter() - started) * 1000

    def mark(self, phase, **extra):
        """Small timing records: no window enumeration, room data or credentials."""
        self.write(dict(time=time.time(), phase=phase, gesture=self._gesture,
            sincePressMs=(round((time.perf_counter() - self._press_at) * 1000, 3)
                          if self._press_at is not None else None),
            nativeLeftDown=bool(user32.GetAsyncKeyState(1) & 0x8000),
            qtLeftDown=bool(QApplication.mouseButtons() & Qt.LeftButton), **extra))

    def snapshot(self, phase, window, **extra):
        started = time.perf_counter()
        try:
            if hasattr(self, "ensure_filter"):
                self.ensure_filter()
            if not isValid(window):
                return
            kind, qualifier = wintypes.DWORD(), wintypes.DWORD()
            apartment = ole32.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier))
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            hit = user32.WindowFromPoint(point)
            self.sequence += 1
            wall = getattr(window, 'wall', None)
            record = dict(sequence=self.sequence, time=time.time(),
                          localTime=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                          phase=phase, pid=os.getpid(),
                          layout=getattr(wall, 'layout_id', None), mainHwnd=hex(int(window.internalWinId())),
                          apartment=[apartment, kind.value, qualifier.value],
                          cursor=[point.x, point.y], hit=native_window(hit, properties=False) if hit else None,
                          nativeWindows=windows(), extra=extra)
            record['tiles'] = [dict(index=i, hwnd=hex(int(tile.internalWinId())),
                                    videoHwnd=hex(int(tile.video.internalWinId())),
                                    visible=tile.isVisible(), acceptsDrops=tile.acceptDrops(),
                                    hasRoom=bool(tile.room.get('room_id')), playing=tile in window.players)
                               for i, tile in enumerate(getattr(wall, 'tiles', []))]
            record['snapshotMs'] = round((time.perf_counter() - started) * 1000, 3)
            self.write(record)
            print('[drag-diag]', self.sequence, phase, record['layout'], flush=True, file=sys.stderr)
        except Exception as error:
            print('[drag-diag-error]', phase, type(error).__name__, str(error), file=sys.stderr, flush=True)

    def install(self):
        recorder = self
        class LifecycleFilter(QObject):
            def eventFilter(self, obj, event):
                if isinstance(obj, QWidget) and event.type() in (
                        QEvent.DragEnter, QEvent.DragLeave, QEvent.Drop):
                    row = dict(time=time.time(), phase='drag:event', event=int(event.type()),
                               cls=type(obj).__name__, name=obj.objectName())
                    if event.type() != QEvent.DragLeave:
                        row['formats'] = event.mimeData().formats()
                    recorder.write(row)
                return False
        self.filter = None
        def poll_com():
            current = apartment()
            if current == self._last_com:
                return
            window = next((widget for widget in QApplication.topLevelWidgets()
                           if isinstance(widget, MainWindow) and
                           not getattr(widget, '_closing', False)), None)
            if window is not None:
                previous, self._last_com = self._last_com, current
                self.snapshot('com:baseline' if previous is None else 'com:changed', window,
                              before=previous, after=current)
        def ensure_filter():
            app = QApplication.instance()
            if self.filter is None and app is not None:
                self.filter = LifecycleFilter(app)
                app.installEventFilter(self.filter)
                # Read-only polling catches changes outside the player wrappers.
                # Write a full snapshot only at baseline or when COM state changes.
                self.com_timer = QTimer(self.filter)
                self.com_timer.setInterval(500)
                self.com_timer.timeout.connect(poll_com)
                self.com_timer.start()
        ensure_filter()
        self.ensure_filter = ensure_filter
        from ddm import motion
        from ddm.preview import HoverPreview
        from ddm.widgets import NavItem, Sidebar
        from ddm.sidebar_drag import SidebarDrag
        original_press = NavItem.mousePressEvent
        @functools.wraps(original_press)
        def press(item, event):
            if event.button() == Qt.LeftButton:
                self._gesture += 1
                self._press_at = time.perf_counter()
                self.mark('drag:press')
            return original_press(item, event)
        NavItem.mousePressEvent = press
        for owner, name, stage in ((NavItem, '_drag_pixmap', 'pixmap'),
                                   (motion, 'lifted_drag', 'lift'),
                                   (Sidebar, 'show_drop_indicator', 'layout'),
                                   (Sidebar, 'finish_drag', 'drop'),
                                   (Sidebar, 'reorder_items', 'reorder'),
                                   (Sidebar, 'refresh_strip', 'strip'),
                                   (HoverPreview, '_stop_now', 'preview-stop'),
                                   (HoverPreview, '_check_hover', 'preview-check'),
                                   (HoverPreview, '_begin_resolve', 'preview-prepare'),
                                   (HoverPreview, '_on_resolved', 'preview-play'),
                                   (MainWindow, '_on_room_dropped', 'drop-to-player')):
            original = getattr(owner, name)
            def timed(method, label):
                @functools.wraps(method)
                def wrapped(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return method(*args, **kwargs)
                    finally:
                        elapsed = (time.perf_counter() - started) * 1000
                        if label in ('pixmap', 'lift', 'hook') or elapsed >= 8:
                            self.mark('drag:stage', stage=label, elapsedMs=round(elapsed, 3))
                return wrapped
            setattr(owner, name, timed(original, stage))
        from ddm.player import TilePlayer
        def apartment():
            kind, qualifier = wintypes.DWORD(), wintypes.DWORD()
            result = ole32.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier))
            return [result, kind.value, qualifier.value]
        for name in ('bind', 'stop', 'release', '_destroy_core'):
            original = getattr(TilePlayer, name)
            def trace_player(method, label):
                @functools.wraps(method)
                def wrapped(player, *args, **kwargs):
                    started = time.perf_counter()
                    before = apartment()
                    try:
                        return method(player, *args, **kwargs)
                    finally:
                        after = apartment()
                        elapsed = (time.perf_counter() - started) * 1000
                        if elapsed >= 8:
                            self.mark('drag:stage', stage='player-' + label, elapsedMs=round(elapsed, 3))
                        if after != before:
                            window = next((widget for widget in QApplication.topLevelWidgets()
                                           if isinstance(widget, MainWindow)), None)
                            if window is not None:
                                self.snapshot('player:' + label + ':com-changed', window,
                                              before=before, after=after, silent=player.silent,
                                              pythonStack=traceback.format_stack(limit=16))
                return wrapped
            setattr(TilePlayer, name, trace_player(original, name))
        for name in ('showEvent', '_on_layout_changed', '_stop_tile', '_clear_tile_room'):
            original = getattr(MainWindow, name)
            def make_wrapper(method, label):
                @functools.wraps(method)
                def wrapper(window, *args, **kwargs):
                    extra = dict(targetLayout=args[0]) if label == '_on_layout_changed' and args else {}
                    self.snapshot(label + ':before', window, **extra)
                    try:
                        return method(window, *args, **kwargs)
                    finally:
                        self.snapshot(label + ':after', window, **extra)
                        if label == '_on_layout_changed':
                            reference = weakref.ref(window)
                            def settled():
                                current = reference()
                                if current is not None and isValid(current) and not current._closing:
                                    self.snapshot(label + ':settled', current, **extra)
                            QTimer.singleShot(250, settled)
                return wrapper
            setattr(MainWindow, name, make_wrapper(original, name))
        original_start = SidebarDrag.start
        @functools.wraps(original_start)
        def start_internal(session, *args, **kwargs):
            if session.active:
                return original_start(session, *args, **kwargs)
            started = time.perf_counter()
            result = original_start(session, *args, **kwargs)
            if session.active:
                self.mark('internal-drag:start', elapsedMs=round((time.perf_counter()-started)*1000, 3),
                          source=type(session.source).__name__)
                session._diagnostic_probe = DragStallProbe()
                session.timer.timeout.connect(session._diagnostic_probe.pulse)
            return result
        SidebarDrag.start = start_internal
        for name in ('finish', 'cancel'):
            original = getattr(SidebarDrag, name)
            def trace_internal_end(method, label):
                @functools.wraps(method)
                def end(session, *args, **kwargs):
                    probe = getattr(session, '_diagnostic_probe', None)
                    session._diagnostic_probe = None
                    if probe is not None:
                        session.timer.timeout.disconnect(probe.pulse)
                    started = time.perf_counter()
                    try:
                        return method(session, *args, **kwargs)
                    finally:
                        if probe is not None:
                            self.mark('internal-drag:' + label,
                                      elapsedMs=round((time.perf_counter()-started)*1000, 3))
                            for sample in probe.finish():
                                self.write(dict(sample, gesture=self._gesture, internal=True))
                return end
            setattr(SidebarDrag, name, trace_internal_end(original, name))
        original_drag = QDrag.exec
        @functools.wraps(original_drag)
        def execute(drag, *args, **kwargs):
            source = drag.source()
            window = source.window() if isinstance(source, QWidget) else QApplication.activeWindow()
            if not isinstance(window, MainWindow):
                return original_drag(drag, *args, **kwargs)
            self.snapshot('drag:before', window, source=type(source).__name__,
                          mimeFormats=drag.mimeData().formats())
            # Sample after the potentially expensive snapshot, immediately before OLE.
            self.mark('drag:exec-enter')
            started = time.perf_counter()
            gesture = self._gesture
            probe = DragStallProbe()
            last_tick = started
            left_down = bool(user32.GetAsyncKeyState(1) & 0x8000)
            def poll_drag():
                nonlocal last_tick, left_down
                probe.pulse()
                now = time.perf_counter()
                if now - last_tick >= .15:
                    self.mark('drag:ui-delay', gapMs=round((now - last_tick) * 1000, 3))
                current = bool(user32.GetAsyncKeyState(1) & 0x8000)
                if left_down and not current:
                    self.mark('drag:left-release')
                last_tick, left_down = now, current
            timer = QTimer(window)
            timer.setInterval(50)
            timer.timeout.connect(poll_drag)
            timer.start()
            try:
                action = original_drag(drag, *args, **kwargs)
                self.mark('drag:exec-return', elapsedMs=round((time.perf_counter() - started) * 1000, 3),
                          action=str(action))
                self.snapshot('drag:after', window, action=str(action))
                return action
            except BaseException:
                self.snapshot('drag:exception', window)
                raise
            finally:
                timer.stop()
                timer.deleteLater()
                for sample in probe.finish():
                    self.write(dict(sample, gesture=gesture))
        QDrag.exec = execute


if __name__ == '__main__':
    path = ROOT / 'logs' / 'drag-windows.jsonl'
    recorder = Recorder(path)
    recorder.install()
    if os.environ.get('DDM_SC_PAINT_CAPTURE') == '1':
        from dev.diagnose_super_chat import SuperChatTrace
        sc_trace = SuperChatTrace(ROOT / 'logs' / 'sc-paint')
        sc_trace.install()
    print('Window diagnostics:', path, file=sys.stderr, flush=True)
    runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
