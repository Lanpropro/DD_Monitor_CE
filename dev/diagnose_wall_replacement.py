"""Read-only real-click trace while live-notice replacement is active."""
import ctypes
import functools
import json
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication


class ReplacementTrace(QObject):
    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.selection = None
        self.down = False
        self.count = 0
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self.poll)

    def mark(self, stage, **extra):
        if self.count >= 300:
            return
        self.count += 1
        position = QCursor.pos()
        selection = self.selection
        tiles = selection.host.wall.visible_tiles() if selection else []
        hit = next((index for index, tile in enumerate(tiles)
                    if tile.video.rect().contains(tile.video.mapFromGlobal(position))), None)
        widget = QApplication.widgetAt(position)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(dict(time=time.time(), stage=stage, hit=hit,
                widget=type(widget).__name__ if widget else None, **extra)) + '\n')

    def poll(self):
        down = bool(ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000)
        if down != self.down:
            self.down = down
            self.mark('physical:press' if down else 'physical:release')

    def install(self):
        from ddm.wall_replacement import WallReplacement
        trace = self
        for name in ('place', 'cancel_replacement', 'eventFilter'):
            original = getattr(WallReplacement, name)
            def wrap(method, label):
                @functools.wraps(method)
                def call(selection, *args, **kwargs):
                    trace.selection = selection
                    relevant = (label == 'eventFilter' and selection.replacement_rooms and
                        args[1].type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease))
                    if relevant:
                        trace.mark('qt:before', event=args[1].type().name,
                                   watched=type(args[0]).__name__,
                                   hasPressed=selection._replacement_target is not None)
                    result = method(selection, *args, **kwargs)
                    if label == 'place' and selection.replacement_rooms:
                        trace.count = 0
                        trace.down = bool(ctypes.windll.user32.GetAsyncKeyState(1) & 0x8000)
                        trace.mark('mode:started', pending=len(selection.replacement_rooms))
                        trace.timer.start()
                    elif label == 'cancel_replacement':
                        trace.timer.stop()
                        trace.mark('mode:cancelled')
                    elif relevant:
                        trace.mark('qt:after', event=args[1].type().name, consumed=bool(result),
                                   hasPressed=selection._replacement_target is not None,
                                   pending=len(selection.replacement_rooms))
                    return result
                return call
            setattr(WallReplacement, name, wrap(original, name))
