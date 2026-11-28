"""Capture Qt dispatch around match playback in the development diagnostic launch."""
import os
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QTimer


@dataclass
class _WindowUpdate:
    started: tuple
    saw_paint: bool = False
    saw_main_canvas: bool = False
    last_paint_end: tuple | None = None


def install(app_module):
    if os.environ.get('DDM_MATCH_GUI_DISPATCH') == '0':
        return
    base = app_module.QApplication
    gui_thread = threading.get_ident()
    nested_types = {QEvent.Paint, QEvent.LayoutRequest, QEvent.UpdateRequest, QEvent.Timer}

    class Application(base):
        match_gui_timeline = None
        _match_dispatch_depth = 0
        _match_window_update = None

        def notify(self, receiver, event):
            notify = super().notify
            timeline = self.match_gui_timeline
            if timeline is None or threading.get_ident() != gui_thread:
                return notify(receiver, event)

            kind = event.type()
            if self._match_dispatch_depth and kind not in nested_types:
                return notify(receiver, event)
            owner = type(receiver).__name__
            if kind == QEvent.Paint and owner == 'QWidget':
                parent = receiver.parentWidget()
                if type(parent).__name__ == 'DanmakuTextBrowser':
                    owner = 'DanmakuTextViewport'
            if kind == QEvent.Timer and isinstance(receiver, QTimer):
                parent = receiver.parent()
                if parent is not None:
                    owner = type(parent).__name__
            exact = owner == 'VideoDanmaku' and kind in (QEvent.Timer, QEvent.Paint)
            start = timeline.begin()
            main_update = kind == QEvent.UpdateRequest and owner == 'MainWindow'
            previous_update = self._match_window_update
            update = None
            if main_update:
                update = self._match_window_update = _WindowUpdate(start)
            elif kind == QEvent.Paint and previous_update is not None:
                if not previous_update.saw_paint:
                    previous_update.saw_paint = True
                    timeline.end('qt.main_update_before_first_paint', previous_update.started)
                if (not previous_update.saw_main_canvas and owner == 'Canvas'
                        and getattr(receiver, 'paint_probe', None) is not None):
                    previous_update.saw_main_canvas = True
                    timeline.end('qt.main_update_before_canvas_paint', previous_update.started)
            self._match_dispatch_depth += 1
            try:
                return notify(receiver, event)
            finally:
                self._match_dispatch_depth -= 1
                if update is not None:
                    self._match_window_update = previous_update
                    if update.last_paint_end is not None:
                        timeline.end('qt.main_update_after_last_paint', update.last_paint_end)
                elif kind == QEvent.Paint and previous_update is not None:
                    previous_update.last_paint_end = timeline.begin()
                if exact or time.perf_counter() - start[0] >= .0005:
                    timeline.end(f'qt.{owner}.{kind.name}', start, self._match_dispatch_depth)

    if base.instance() is None:
        app_module.QApplication = Application
