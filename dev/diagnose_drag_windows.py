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

    def write(self, record):
        self.logger.info(json.dumps(dict(record, pid=os.getpid()), ensure_ascii=True))

    def snapshot(self, phase, window, **extra):
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
                    before = apartment()
                    try:
                        return method(player, *args, **kwargs)
                    finally:
                        after = apartment()
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
        original_drag = QDrag.exec
        @functools.wraps(original_drag)
        def execute(drag, *args, **kwargs):
            source = drag.source()
            window = source.window() if isinstance(source, QWidget) else QApplication.activeWindow()
            if not isinstance(window, MainWindow):
                return original_drag(drag, *args, **kwargs)
            self.snapshot('drag:before', window, source=type(source).__name__,
                          mimeFormats=drag.mimeData().formats())
            try:
                action = original_drag(drag, *args, **kwargs)
                self.snapshot('drag:after', window, action=str(action))
                return action
            except BaseException:
                self.snapshot('drag:exception', window)
                raise
        QDrag.exec = execute


if __name__ == '__main__':
    path = ROOT / 'logs' / 'drag-windows.jsonl'
    recorder = Recorder(path)
    recorder.install()
    print('Window diagnostics:', path, file=sys.stderr, flush=True)
    runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
