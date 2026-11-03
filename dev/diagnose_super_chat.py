"""Bounded SC source-image and native-surface trace; never changes placement."""
import ctypes
from ctypes import wintypes
import functools
import json
from pathlib import Path
import time

from PySide6.QtGui import QImage


class SuperChatTrace:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.count = 0
        self.images = {}
        self._capturing = False

    def mark(self, stage, sc, painter=None):
        if self._capturing or self.count >= 300 or not sc.chats:
            return
        self.count += 1
        hwnd = int(sc.internalWinId())
        native = None
        style = None
        if hwnd:
            user32 = ctypes.windll.user32
            user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
            user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                native = [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
            style = user32.GetWindowLongW(hwnd, -20)
        owner = sc._video_danmaku
        tile = owner.parentWidget() if owner else None
        siblings = {name: list(getattr(tile, name).geometry().getRect())
                    for name in ('stream_badge', 'title_badge', 'controls') if hasattr(tile, name)}
        row = dict(time=time.time(), stage=stage, hwnd=hex(hwnd), visible=sc.isVisible(),
                   geometry=list(sc.geometry().getRect()), nativeRect=native, exStyle=style,
                   qtSurface=sc.qt_composited,
                   contentOrigin=[sc._content_origin.x(), sc._content_origin.y()],
                   scale=sc.devicePixelRatioF(), alphaUploaded=getattr(sc, '_alpha_uploaded', None),
                   cachedAlpha=getattr(sc, '_last_alpha_state', None) is not None,
                   siblings=siblings,
                   buttons=[dict(rect=list(button.geometry().getRect()), hwnd=hex(int(button.internalWinId())))
                            for button in sc.close_buttons if button.isVisible()])
        self.directory.mkdir(parents=True, exist_ok=True)
        if painter is not None:
            side = 'left' if sc._content_origin.x() < owner.width() / 2 else 'right'
            key = (hwnd, side)
            if self.images.get(key, 0) < 2:
                self.images[key] = self.images.get(key, 0) + 1
                name = f'source-{hwnd}-{side}-{self.images[key]}.png'
                self._capturing = True
                try:
                    source = painter.device().copy() if isinstance(painter.device(), QImage) else sc.render_image()
                    source.save(str(self.directory / name))
                finally:
                    self._capturing = False
                row['sourceImage'] = name
        with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps(row) + '\n')

    def install(self):
        from ddm.video_danmaku import SuperChatOverlay
        trace = self
        for name in ('sync', 'paintEvent', '_paint_layered', '_render_layered'):
            original = getattr(SuperChatOverlay, name)
            def wrap(method, label):
                @functools.wraps(method)
                def call(sc, *args, **kwargs):
                    trace.mark(label + ':before', sc)
                    result = method(sc, *args, **kwargs)
                    trace.mark(label + ':after', sc, args[0] if label == '_render_layered' else None)
                    return result
                return call
            setattr(SuperChatOverlay, name, wrap(original, name))
