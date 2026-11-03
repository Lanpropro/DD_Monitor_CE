"""Bounded numeric motion/ownership evidence, without message text or screenshots."""
import functools
import json
import os
from pathlib import Path
import time
import traceback

from PySide6.QtCore import QTimer
from shiboken6 import isValid


class MotionTrace:
    LIMIT = 2400

    def __init__(self, path):
        self.path = Path(path)
        self.count = 0
        self.started = None
        self.session = f'{os.getpid()}-{time.time_ns()}'

    def write(self, stage, **state):
        if self.count >= self.LIMIT:
            return
        if self.started is None:
            self.started = time.perf_counter()
        self.count += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(stage=stage, session=self.session,
                   at_ms=round((time.perf_counter() - self.started) * 1000, 3), **state)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row) + '\n')

    def attach(self, layer):
        timer = QTimer(layer)
        timer.setInterval(100)

        def sample():
            if self.count >= self.LIMIT:
                timer.stop()
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
        from ddm.app import MainWindow
        from ddm.video_danmaku_quick import QuickDanmakuLayer
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
            if record is not None:
                trace.write('set-motion', id=identifier, x=x, y=y, speed=speed,
                            held=record.get('held', False), active=record['group'] in layer._active_groups,
                            callers=[f'{Path(frame.filename).name}:{frame.name}:{frame.lineno}'
                                     for frame in traceback.extract_stack(limit=4)[:-1]])
            return original_move(layer, identifier, x, y, speed)
        QuickDanmakuLayer.move = move

        original_open = MainWindow._open_tile_stream_info

        @functools.wraps(original_open)
        def open_info(window, tile):
            result = original_open(window, tile)
            dialog = window._stream_info_dialogs.get(tile)
            if dialog is not None:
                for delay in (0, 300, 1500):
                    def inspect(dialog=dialog, delay=delay):
                        if not isValid(dialog):
                            trace.write('stream-info', delay=delay, deleted=True)
                            return
                        handle = dialog.windowHandle()
                        owner = handle.transientParent() if handle else None
                        trace.write('stream-info', delay=delay, visible=dialog.isVisible(),
                                    active=dialog.isActiveWindow(), tile_window=tile.isWindow(),
                                    correct_owner=owner is tile.window().windowHandle())
                    QTimer.singleShot(delay, window, inspect)
            return result
        MainWindow._open_tile_stream_info = open_info
