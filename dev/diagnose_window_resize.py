"""Opt-in, bounded native move/resize timings; buffer until mouse release."""
import ctypes
from ctypes import wintypes
import functools
import json
import os
from pathlib import Path
import time


class WindowResizeTrace:
    def __init__(self, path):
        self.path = Path(path)
        self.originals = []
        self.window = None
        self.calls = []
        self.messages = []
        self.stack = []
        self.started = 0
        self.gesture = 0

    def begin(self, window):
        self.flush()
        self.window = window
        self.started = time.perf_counter()
        self.epoch = time.time()
        self.gesture += 1
        self.initial = self.state()

    def state(self):
        w = self.window
        return dict(geometry=list(w.geometry().getRect()),
                    wall=list(w.wall.geometry().getRect()),
                    interactive=w._interactive_resize,
                    wallInteractive=w.wall._interactive_resize,
                    idleTimer=w._resize_idle_timer.isActive(),
                    wallTimer=w.wall._resize_timer.isActive(),
                    maximized=w.isMaximized(), scale=w.devicePixelRatioF())

    def flush(self):
        if self.window is None:
            return
        row = dict(pid=os.getpid(), gesture=self.gesture, time=self.epoch,
                   durationMs=round((time.perf_counter()-self.started)*1000, 3),
                   initial=self.initial, final=self.state(),
                   calls=self.calls, messages=self.messages)
        self.window = None
        self.calls, self.messages = [], []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row) + '\n')

    def install(self):
        from ddm.app import MainWindow
        from ddm.wall_widgets import WallGrid
        from ddm.tile_widgets import Tile
        from ddm.video_surface import VideoSurface
        from ddm.fullscreen_bar import FullscreenBar
        from ddm.danmaku_widgets import DanmakuTextBrowser
        from ddm.video_danmaku_quick import QuickDanmakuLayer
        from ddm.wall_border import WallPaneBorder
        from ddm.badge_surface import BadgeSurface

        trace = self
        native = MainWindow.nativeEvent
        @functools.wraps(native)
        def native_event(window, event_type, message):
            msg = wintypes.MSG.from_address(int(message))
            code, value = msg.message, int(msg.wParam)
            if code == 0x0231:
                trace.begin(window)
            result = native(window, event_type, message)
            if trace.window is window and code in (0x0231, 0x0232, 0x0005, 0x02e0):
                trace.messages.append(dict(atMs=round((time.perf_counter()-trace.started)*1000, 3),
                                           message=code, wParam=value, **trace.state()))
                if code == 0x0232:
                    trace.flush()
            return result
        self.originals.append((MainWindow, 'nativeEvent', native))
        MainWindow.nativeEvent = native_event

        targets = ((MainWindow, ('_begin_interactive_resize', '_finish_interactive_resize', 'resizeEvent')),
                   (WallGrid, ('resizeEvent', '_flush_resize', '_relayout_corner', '_relayout_preset')),
                   (Tile, ('_layout_areas', '_round_video', '_refresh_moved_overlays',
                           '_layout_bottom_controls', 'raise_overlays')),
                   (VideoSurface, ('_clip_native_video',)),
                   (FullscreenBar, ('set_tile_geometry',)),
                   (DanmakuTextBrowser, ('viewportEvent',)),
                   (QuickDanmakuLayer, ('resize', '_update_occlusion', '_restore_surface')),
                   (WallPaneBorder, ('sync',)),
                   (BadgeSurface, ('_paint_layered',)))
        for owner, names in targets:
            for name in names:
                self.wrap(owner, name)
        return self

    def wrap(self, owner, name):
        original = getattr(owner, name)
        trace = self
        @functools.wraps(original)
        def measured(obj, *args, **kwargs):
            if trace.window is None or len(trace.calls) >= 12000:
                return original(obj, *args, **kwargs)
            started = time.perf_counter()
            frame = [0.0]
            trace.stack.append(frame)
            try:
                return original(obj, *args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                trace.stack.pop()
                if trace.stack:
                    trace.stack[-1][0] += elapsed
                trace.calls.append(dict(method=owner.__name__+'.'+name, instance=id(obj),
                    atMs=round((started-trace.started)*1000, 3),
                    elapsedMs=round(elapsed*1000, 3),
                    selfMs=round(max(0, elapsed-frame[0])*1000, 3)))
        self.originals.append((owner, name, original))
        setattr(owner, name, measured)

    def __enter__(self):
        return self.install()

    def __exit__(self, *_):
        self.flush()
        for owner, name, original in reversed(self.originals):
            setattr(owner, name, original)
        self.originals.clear()
