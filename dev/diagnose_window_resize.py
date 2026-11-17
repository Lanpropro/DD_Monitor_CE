"""Opt-in, bounded native move/resize timings; buffer until mouse release."""
import ctypes
from ctypes import wintypes
from collections import Counter
import functools
import json
import os
from pathlib import Path
import time


class WindowResizeTrace:
    MAX_GESTURES = 80
    MAX_CALLS = 12000

    def __init__(self, path):
        self.path = Path(path)
        self.originals = []
        self.window = None
        self.calls = []
        self.messages = []
        self.stack = []
        self.started = 0
        self.gesture = 0

    def begin(self, window, source='native-resize'):
        self.flush()
        if self.gesture >= self.MAX_GESTURES:
            return False
        self.window = window
        self.source = source
        self.started = time.perf_counter()
        self.cpu_started = time.thread_time()
        self.epoch = time.time()
        self.gesture += 1
        self.initial = self.state()
        self.initial_topology = self.topology()
        return True

    def topology(self):
        from PySide6.QtWidgets import QWidget
        widgets = [self.window, *self.window.findChildren(QWidget)]
        native = Counter(type(w).__name__ for w in widgets if w.internalWinId())
        return dict(widgets=len(widgets), nativeWidgets=sum(native.values()), nativeTypes=dict(native))

    def state(self):
        w = self.window
        screen = w.screen()
        return dict(geometry=list(w.geometry().getRect()),
                    screenGeometry=list(screen.geometry().getRect()),
                    screenAvailable=list(screen.availableGeometry().getRect()),
                    screenScale=screen.devicePixelRatio(),
                    wall=list(w.wall.geometry().getRect()),
                    interactive=w._interactive_resize,
                    wallInteractive=w.wall._interactive_resize,
                    idleTimer=w._resize_idle_timer.isActive(),
                    wallTimer=w.wall._resize_timer.isActive(),
                    maximized=w.isMaximized(), scale=w.devicePixelRatioF(),
                    orientation=w.orientation, layout=w.wall.layout_id,
                    sidebarSide=w.sidebar.side, sidebar=list(w.sidebar.geometry().getRect()),
                    cards=len(w.sidebar._items), tiles=len(w.wall.tiles),
                    players=len(w.players))

    def flush(self):
        if self.window is None:
            return
        row = dict(pid=os.getpid(), gesture=self.gesture, time=self.epoch, source=self.source,
                   durationMs=round((time.perf_counter()-self.started)*1000, 3),
                   cpuMs=round((time.thread_time()-self.cpu_started)*1000, 3),
                   initial=self.initial, final=self.state(),
                   initialTopology=self.initial_topology, finalTopology=self.topology(),
                   calls=self.calls, callsCapped=len(self.calls) >= self.MAX_CALLS,
                   messages=self.messages, messagesCapped=len(self.messages) >= self.MAX_CALLS)
        self.window = None
        self.calls, self.messages = [], []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row) + '\n')

    def install(self):
        from PySide6.QtCore import QEvent
        from ddm.app import MainWindow
        from ddm.wall_widgets import WallGrid
        from ddm.tile_widgets import Tile
        from ddm.video_surface import VideoSurface
        from ddm.fullscreen_bar import FullscreenBar
        from ddm.danmaku_widgets import DanmakuTextBrowser
        from ddm.video_danmaku_quick import QuickDanmakuLayer
        from ddm.wall_border import WallPaneBorder
        from ddm.badge_surface import BadgeSurface
        from ddm.window_layout import WindowLayout
        from ddm.sidebar_orientation import SidebarOrientation
        from ddm.sidebar_portrait import PortraitSidebar
        from ddm.sidebar_navigation import SidebarNavigation
        from ddm.sidebar_presentation import SidebarPresentation
        from ddm.sidebar_list import RoomListBox
        from ddm.workspace_controls import WorkspaceControls

        trace = self
        native = MainWindow.nativeEvent
        @functools.wraps(native)
        def native_event(window, event_type, message):
            msg = wintypes.MSG.from_address(int(message))
            code, value = msg.message, int(msg.wParam)
            if code == 0x0231:
                trace.begin(window)
            result = native(window, event_type, message)
            if trace.window is window and code in (0x0231, 0x0232, 0x0003, 0x0005, 0x02e0):
                if len(trace.messages) < trace.MAX_CALLS:
                    trace.messages.append(dict(atMs=round((time.perf_counter()-trace.started)*1000, 3),
                                               cpuAtMs=round((time.thread_time()-trace.cpu_started)*1000, 3),
                                               message=code, wParam=value, **trace.state()))
                if code == 0x0232:
                    trace.flush()
            return result
        self.originals.append((MainWindow, 'nativeEvent', native))
        MainWindow.nativeEvent = native_event

        targets = ((MainWindow, ('_begin_interactive_resize', 'resizeEvent', '_sync_tile_playback')),
                   (WindowLayout, ('build_arrangement', 'reshape_window')),
                   (SidebarOrientation, ('set_side', 'detach_from_rows', 'restore_side_children')),
                   (PortraitSidebar, ('adopt', 'release', 'sync', 'sync_density')),
                   (SidebarNavigation, ('sync', 'release', '_sort_tools')),
                   (SidebarPresentation, ('sync_appearance_row', 'sync_top_mode', 'apply_scroll_axis')),
                   (RoomListBox, ('relayout',)),
                   (WorkspaceControls, ('sync_layout',)),
                   (WallGrid, ('resizeEvent', '_flush_resize', '_relayout_corner', '_relayout_preset', 'relayout', 'set_layout')),
                   (Tile, ('moveEvent', '_layout_areas', '_round_video', '_refresh_moved_overlays',
                           '_layout_bottom_controls', 'raise_overlays')),
                   (VideoSurface, ('_clip_native_video',)),
                   (FullscreenBar, ('set_tile_geometry',)),
                   (DanmakuTextBrowser, ('viewportEvent',)),
                   (QuickDanmakuLayer, ('resize', '_update_occlusion', 'reset_surface', '_restore_surface')),
                   (WallPaneBorder, ('sync',)),
                   (BadgeSurface, ('_paint_layered',)))
        for owner, names in targets:
            for name in names:
                self.wrap(owner, name)
        screen_events = (QEvent.ScreenChangeInternal, QEvent.DevicePixelRatioChange)
        for owner in (Tile, VideoSurface):
            self.wrap(owner, 'event', event_types=screen_events)
        self.wrap(QuickDanmakuLayer, 'eventFilter', event_types=screen_events)
        self.wrap(MainWindow, '_finish_interactive_resize', opens=True)
        for name in ('apply_orientation', 'on_layout_changed'):
            self.wrap(WindowLayout, name, opens=True)
        return self

    def wrap(self, owner, name, *, opens=False, event_types=None):
        original = getattr(owner, name)
        trace = self
        @functools.wraps(original)
        def measured(obj, *args, **kwargs):
            if event_types is not None and args[-1].type() not in event_types:
                return original(obj, *args, **kwargs)
            opened = False
            if opens and trace.window is None:
                window = getattr(obj, 'host', obj)
                if window.isVisible():
                    opened = trace.begin(window, owner.__name__+'.'+name)
            if trace.window is None or len(trace.calls) >= trace.MAX_CALLS:
                return original(obj, *args, **kwargs)
            started = time.perf_counter()
            cpu_started = time.thread_time()
            frame = [0.0, 0.0]
            trace.stack.append(frame)
            try:
                return original(obj, *args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                cpu = time.thread_time() - cpu_started
                trace.stack.pop()
                if trace.stack:
                    trace.stack[-1][0] += elapsed
                    trace.stack[-1][1] += cpu
                if len(trace.calls) < trace.MAX_CALLS:
                    call = dict(method=owner.__name__+'.'+name, instance=id(obj),
                        atMs=round((started-trace.started)*1000, 3),
                        elapsedMs=round(elapsed*1000, 3),
                        selfMs=round(max(0, elapsed-frame[0])*1000, 3),
                        cpuMs=round(cpu*1000, 3),
                        selfCpuMs=round(max(0, cpu-frame[1])*1000, 3))
                    if event_types is not None:
                        call['eventType'] = int(args[-1].type())
                    trace.calls.append(call)
                if opened:
                    trace.flush()
        self.originals.append((owner, name, original))
        setattr(owner, name, measured)

    def __enter__(self):
        return self.install()

    def __exit__(self, *_):
        self.flush()
        for owner, name, original in reversed(self.originals):
            setattr(owner, name, original)
        self.originals.clear()
