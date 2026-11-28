"""Bounded numeric motion/ownership evidence, without message text or screenshots."""
import functools
import json
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import time
import traceback
import weakref

from PySide6.QtCore import QTimer, Qt
from shiboken6 import isValid


@dataclass
class _RasterCadence:
    started: float
    last_paint: float | None = None
    ticks: list = field(default_factory=list)
    paints: list = field(default_factory=list)
    scan: list = field(default_factory=list)
    draw: list = field(default_factory=list)


def _milliseconds(values):
    values = sorted(values)
    if not values:
        return None
    return dict(p50=round(values[(len(values) - 1) // 2] * 1000, 3),
                p95=round(values[int((len(values) - 1) * .95)] * 1000, 3),
                max=round(values[-1] * 1000, 3))


class _LayeredPaintTrace:
    def __init__(self, trace, overlay):
        self.trace = trace
        self.overlay = id(overlay)
        self.queued_at = None
        self.last_upload = None
        self.bucket_started = None
        self.frames = []

    def queue(self):
        if self.trace.count < self.trace.LIMIT:
            self.queued_at = time.perf_counter()

    def begin(self):
        if self.trace.count >= self.trace.LIMIT:
            return None
        self.started = time.perf_counter()
        self.frame = {}
        self.size = None
        if self.queued_at is not None:
            self.frame['queue_ms'] = self.started - self.queued_at
            self.queued_at = None
        return self

    def set_size(self, width, height, ratio):
        self.size = (width, height, ratio)
        self.start_phase()

    def start_phase(self):
        self.phase_started = time.perf_counter()

    def mark(self, name):
        now = time.perf_counter()
        self.frame[name] = now - self.phase_started
        self.phase_started = now

    def finish(self, uploaded, fallback, comments):
        self.frame['total_ms'] = time.perf_counter() - self.started
        if uploaded:
            completed = self.phase_started
            if self.last_upload is not None:
                self.frame['refresh_gap_ms'] = completed - self.last_upload
            self.last_upload = completed
        if self.bucket_started is None:
            self.bucket_started = self.started
        self.frames.append(dict(metrics=self.frame, size=self.size, uploaded=uploaded,
                                fallback=fallback, comments=comments))
        if fallback or self.started - self.bucket_started >= 1:
            self.flush()

    def flush(self):
        if not self.frames:
            return
        metrics = {}
        for frame in self.frames:
            for name, value in frame['metrics'].items():
                metrics.setdefault(name, []).append(value)
        self.trace.write('layered-cadence',
                         time=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                         overlay=self.overlay, attempts=len(self.frames),
                         uploads=sum(frame['uploaded'] for frame in self.frames),
                         fallbacks=sum(frame['fallback'] for frame in self.frames),
                         comments_min=min(frame['comments'] for frame in self.frames),
                         comments_max=max(frame['comments'] for frame in self.frames),
                         sizes=sorted({frame['size'] for frame in self.frames if frame['size'] is not None}),
                         **{name: _milliseconds(values) for name, values in metrics.items()})
        self.frames.clear()
        self.bucket_started = self.started


class MotionTrace:
    LIMIT = 2400

    def __init__(self, path, *, emit=None):
        self.path = Path(path)
        self.emit = emit
        self.count = 0
        self.started = None
        self.session = f'{os.getpid()}-{time.time_ns()}'
        self.timers = []

    def arm(self):
        self.count = 0
        self.started = None
        self.timers = [reference for reference in self.timers
                       if reference() is not None and isValid(reference())]
        for reference in self.timers:
            reference().start()

    def write(self, stage, **state):
        if self.count >= self.LIMIT:
            return
        if self.started is None:
            self.started = time.perf_counter()
        self.count += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(stage=stage, session=self.session,
                   at_ms=round((time.perf_counter() - self.started) * 1000, 3), **state)
        if self.emit is not None:
            self.emit(row.pop('stage'), **row)
        else:
            with self.path.open('a', encoding='utf-8') as output:
                output.write(json.dumps(row) + '\n')

    def attach(self, layer):
        timer = QTimer(layer)
        timer.setInterval(100)
        self.timers.append(weakref.ref(timer))
        quick_frames = None

        def sample_quick():
            nonlocal quick_frames
            if quick_frames is None:
                quick_frames = _QuickCadence(layer, self.write)
                timer.setInterval(1000)
                return
            quick_frames.sample()

        def sample():
            if self.count >= self.LIMIT:
                timer.stop()
                if quick_frames is not None:
                    quick_frames.stop()
                return
            if layer.property('matchWindowedDanmaku'):
                sample_quick()
                return
            rows = []
            for identifier, record in list(layer.items.items())[:4]:
                group = layer.groups[record['group']]
                rows.append(dict(id=identifier, group=record['group'], speed=record['speed'],
                                 held=record.get('held', False), active=record['group'] in layer._active_groups,
                                 paused=record['item'].property('motionPaused'),
                                 offset=round(group.x() + layer.stage.x(), 3)))
            self.write('sample', visible=layer.window.isVisible(), exposed=layer.window.isExposed(),
                       fullscreen=layer._presentation_window is not None, rows=rows)

        self.started = self.started or time.perf_counter()
        timer.timeout.connect(sample)
        timer.start()

    def install(self):
        from ddm.danmaku_float_window import DanmakuFloatWindow
        from ddm.video_danmaku_quick import QuickDanmakuLayer
        self.install_raster()
        trace = self
        original_init = QuickDanmakuLayer.__init__

        @functools.wraps(original_init)
        def initialize(layer, *args, **kwargs):
            original_init(layer, *args, **kwargs)
            trace.attach(layer)
        QuickDanmakuLayer.__init__ = initialize

        original_move = QuickDanmakuLayer.move

        @functools.wraps(original_move)
        def move(layer, identifier, x, y, speed=None):
            record = layer.items.get(identifier)
            if record is not None and not layer.property('matchWindowedDanmaku'):
                trace.write('set-motion', id=identifier, x=x, y=y, speed=speed,
                            held=record.get('held', False), active=record['group'] in layer._active_groups,
                            callers=[f'{Path(frame.filename).name}:{frame.name}:{frame.lineno}'
                                     for frame in traceback.extract_stack(limit=4)[:-1]])
            return original_move(layer, identifier, x, y, speed)
        QuickDanmakuLayer.move = move

        groups = weakref.WeakKeyDictionary()
        original_group_move = DanmakuFloatWindow._move_group
        original_finish_move = DanmakuFloatWindow._finish_move

        @functools.wraps(original_group_move)
        def move_group(window, delta):
            now = time.perf_counter()
            sample = groups.get(window)
            if sample is None:
                sample = groups[window] = dict(windows=1 + len(window._move_followers), updates=0,
                                                last=now, maxGapMs=0.0, maxMoveMs=0.0)
            try:
                return original_group_move(window, delta)
            finally:
                sample['updates'] += 1
                sample['maxGapMs'] = max(sample['maxGapMs'], (now - sample['last']) * 1000)
                sample['maxMoveMs'] = max(sample['maxMoveMs'], (time.perf_counter() - now) * 1000)
                sample['last'] = now

        @functools.wraps(original_finish_move)
        def finish_move(window):
            sample = groups.pop(window, None)
            start = time.perf_counter()
            result = original_finish_move(window)
            if sample is not None:
                trace.write('float-group-move', windows=sample['windows'], pointerUpdates=sample['updates'],
                            maxPointerGapMs=round(sample['maxGapMs'], 3),
                            maxMoveMs=round(sample['maxMoveMs'], 3),
                            finishMs=round((time.perf_counter() - start) * 1000, 3),
                            glass=bool(window.property('danmakuFloatGlass')))
            return result

        DanmakuFloatWindow._move_group = move_group
        DanmakuFloatWindow._finish_move = finish_move

    def install_raster(self):
        from ddm.video_danmaku import VideoDanmaku

        trace = self
        cadence = weakref.WeakKeyDictionary()
        original_tick = VideoDanmaku._tick
        original_paint = VideoDanmaku.paintEvent
        original_stop = VideoDanmaku._stop_timer
        original_surface = VideoDanmaku.set_native_video

        @functools.wraps(original_surface)
        def set_native_video(overlay, native, *, allow_quick=True, per_pixel=False):
            original_surface(overlay, native, allow_quick=allow_quick, per_pixel=per_pixel)
            if overlay.native_alpha:
                if overlay._layered_paint_trace is None:
                    overlay._layered_paint_trace = _LayeredPaintTrace(trace, overlay)
            elif overlay._layered_paint_trace is not None:
                overlay._layered_paint_trace.flush()
                overlay._layered_paint_trace = None

        @functools.wraps(original_tick)
        def tick(overlay):
            if (trace.count >= trace.LIMIT or (overlay.native_video and overlay._raster_frame_interval is None)
                    or overlay._quick_requested or not overlay.comments):
                return original_tick(overlay)
            started = time.perf_counter()
            interval = started - overlay._last_tick if overlay._last_tick else 0
            state = cadence.get(overlay)
            if state is None:
                state = cadence[overlay] = _RasterCadence(started)
            result = original_tick(overlay)
            if interval > 0:
                state.ticks.append(interval)
            state.scan.append(time.perf_counter() - started)
            if started - state.started >= 1:
                motion = getattr(overlay, 'raster_control', None)
                joined = getattr(motion, 'joined_motion_updates', None)
                coalescing = {}
                if isinstance(joined, int) and motion.motion_flush_timer is not None:
                    coalescing = dict(joined_updates=joined, standalone_updates=motion.standalone_motion_updates)
                trace.write('raster-cadence',
                            time=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                            overlay=id(overlay), timer_ms=overlay.timer.interval(), comments=len(overlay.comments),
                            ticks=len(state.scan), paints=len(state.draw), tick_gap_ms=_milliseconds(state.ticks),
                            paint_gap_ms=_milliseconds(state.paints), tick_ms=_milliseconds(state.scan),
                            paint_ms=_milliseconds(state.draw), **coalescing)
                cadence[overlay] = _RasterCadence(started, state.last_paint)
            return result

        @functools.wraps(original_paint)
        def paint(overlay, event):
            state = cadence.get(overlay)
            if (state is None or trace.count >= trace.LIMIT
                    or (overlay.native_video and overlay._raster_frame_interval is None)
                    or overlay._quick_requested or not overlay.comments or not overlay.timer.isActive()):
                return original_paint(overlay, event)
            started = time.perf_counter()
            result = original_paint(overlay, event)
            painted = time.perf_counter()
            if state.last_paint is not None:
                state.paints.append(painted - state.last_paint)
            state.last_paint = painted
            state.draw.append(painted - started)
            return result

        @functools.wraps(original_stop)
        def stop(overlay):
            state = cadence.get(overlay)
            if state is not None:
                state.last_paint = None
            layered = getattr(overlay, '_layered_paint_trace', None)
            if layered is not None:
                layered.last_upload = None
            return original_stop(overlay)

        VideoDanmaku._tick = tick
        VideoDanmaku.paintEvent = paint
        VideoDanmaku._stop_timer = stop
        VideoDanmaku.set_native_video = set_native_video


class _QuickCadence:
    """The render callback records a timestamp only; the GUI timer aggregates it."""

    def __init__(self, layer, write):
        self.layer = layer
        self.write = write
        self.timestamps = deque(maxlen=1024)
        self.previous = None
        self.connection = None
        self.desktop_only = os.environ.get('DDM_MATCH_DESKTOP_CADENCE') == '1'
        if not self.desktop_only:
            self.connect()

    def connect(self):
        self.connection = self.layer.window.frameSwapped.connect(self.mark, Qt.DirectConnection)

    def mark(self):
        self.timestamps.append(time.perf_counter())

    def stop(self):
        if self.connection is not None:
            self.layer.window.disconnect(self.connection)
            self.connection = None

    def sample(self):
        if not self.desktop_only and self.connection is None:
            self.timestamps.clear()
            self.previous = None
            self.connect()
        stamps = [self.timestamps.popleft() for _ in range(len(self.timestamps))]
        window = self.layer.window
        if not window.isExposed() or not self.layer._active_groups:
            self.previous = None
            return
        sequence = stamps if self.previous is None else [self.previous, *stamps]
        gaps = [right - left for left, right in zip(sequence, sequence[1:])]
        if stamps:
            self.previous = stamps[-1]
        overlay = self.layer.parent.video_danmaku
        if self.desktop_only:
            # Desktop probes measure the displayed glyphs. The render thread must never
            # enter Python while the GUI waits for the Quick window to hide.
            self.write('quick-window-state', time=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                       comments=len(overlay.comments), window_id=int(window.winId()), dpr=window.devicePixelRatio(),
                       scroll_bottom=overlay.y() + min(overlay.height(), overlay.lane_count() * overlay.lane_height()))
            return
        self.write('quick-cadence', time=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                   comments=len(overlay.comments), swaps=len(stamps), swap_gap_ms=_milliseconds(gaps),
                   gap_count=len(gaps),
                   over_50_ms=sum(gap > .05 for gap in gaps), over_100_ms=sum(gap > .1 for gap in gaps),
                   window_id=int(window.winId()), dpr=window.devicePixelRatio(),
                   scroll_bottom=overlay.y() + min(overlay.height(), overlay.lane_count() * overlay.lane_height()))
