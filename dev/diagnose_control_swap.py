"""Bounded, read-only Qt/native geometry trace for a real tile swap."""
import ctypes
from ctypes import wintypes
import functools
import json
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class SwapTrace(QObject):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.current = None
        self.sequence = 0

    def state(self, widget):
        hwnd = int(widget.internalWinId())  # Never promote an alien widget.
        native_rect = None
        if hwnd:
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                native_rect = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
        point = widget.mapToGlobal(QPoint())
        return dict(geometry=list(widget.geometry().getRect()), globalPosition=[point.x(), point.y()],
                    scale=widget.devicePixelRatioF(),
                    nativeRect=native_rect, hwnd=hex(hwnd), visible=widget.isVisible(),
                    native=widget.testAttribute(Qt.WA_NativeWindow), updates=widget.updatesEnabled())

    def record(self, stage, widget=None, event=None):
        current = self.current
        if current is None or len(current['events']) >= 1500:
            return
        row = dict(stage=stage, ms=round((time.perf_counter() - current['started']) * 1000, 3))
        if widget is not None:
            row.update(widget=current['widgets'][widget], **self.state(widget))
        if event is not None and event.type() == QEvent.Paint:
            row['paintRect'] = list(event.region().boundingRect().getRect())
        current['events'].append(row)

    def snapshot(self, stage):
        if self.current is not None:
            for widget in self.current['widgets']:
                if isValid(widget):
                    self.record(stage, widget)

    def eventFilter(self, widget, event):
        if self.current is not None and widget in self.current['widgets'] and event.type() in (
                QEvent.Paint, QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide, QEvent.WinIdChange):
            self.record(event.type().name, widget, event)
        return False

    def begin(self, tiles):
        self.finish()
        self.sequence += 1
        widgets = {}
        for index, tile in enumerate(tiles):
            for name in ('bottom', 'pause_button', 'volume_button', 'volume_slider', 'volume_label',
                         'status_label', 'danmaku_button', 'fullscreen_button'):
                widgets[getattr(tile, name)] = f'{index}:{name}'
        self.current = dict(sequence=self.sequence, time=time.time(), started=time.perf_counter(),
                            volume=[tile.volume for tile in tiles], widgets=widgets, events=[])
        self.snapshot('swap:before')

    def finish(self):
        if self.current is None:
            return
        self.snapshot('settled')
        record, self.current = self.current, None
        record.pop('widgets')
        record.pop('started')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(record, ensure_ascii=True) + '\n')

    def install(self):
        from ddm.room_placement import RoomPlacement
        from ddm.widgets import Tile
        trace = self
        original_swap = RoomPlacement.hot_swap

        @functools.wraps(original_swap)
        def swap(placement, source, target):
            app = QApplication.instance()
            app.installEventFilter(trace)
            trace.begin((source, target))
            try:
                return original_swap(placement, source, target)
            finally:
                trace.snapshot('swap:return')
                sequence = trace.sequence
                def settled():
                    if trace.sequence == sequence:
                        trace.finish()
                QTimer.singleShot(300, trace, settled)
        RoomPlacement.hot_swap = swap
        for name in ('_layout_bottom_controls', '_refresh_moved_overlays'):
            original = getattr(Tile, name)
            def wrap(method, label):
                @functools.wraps(method)
                def measured(tile, *args, **kwargs):
                    if trace.current is not None and tile.bottom in trace.current['widgets']:
                        trace.record(label + ':before', tile.bottom)
                    try:
                        return method(tile, *args, **kwargs)
                    finally:
                        if trace.current is not None and tile.bottom in trace.current['widgets']:
                            trace.record(label + ':after', tile.bottom)
                return measured
            setattr(Tile, name, wrap(original, name))
