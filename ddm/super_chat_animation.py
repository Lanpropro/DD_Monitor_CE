"""Super Chat runtime reveal and collapse deadlines; original QObject owns timers."""
from __future__ import annotations
import time
import math
from PySide6.QtCore import QObject, QTimer, QVariantAnimation, Signal
from . import motion
from .super_chat_model import _number


class SuperChatPresentation(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.progress = 1.0
        self.delay = 7
        self.ids = set()
        self.collapsed_ids = set()
        self.deadlines = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._expire)
        self.entrance = QVariantAnimation(self)
        self.entrance.setDuration(180)
        self.entrance.setEasingCurve(motion.THEME_WAVE_EASING)
        self.entrance.setStartValue(0.0)
        self.entrance.setEndValue(1.0)
        self.entrance.valueChanged.connect(self._reveal)

    @property
    def collapsed(self):
        return bool(self.ids) and self.ids <= self.collapsed_ids

    def is_collapsed(self, event):
        key = str(event.get('id') or event.get('super_chat_id') or '') if isinstance(event, dict) else str(event)
        return key in self.collapsed_ids

    def configure(self, settings):
        delay = max(1, min(60, _number(settings.get('super_chat_collapse_delay'), 7)))
        if self.delay != delay:
            self.delay = delay
            now = time.monotonic()
            self.deadlines = {key: now + delay for key in self.deadlines}
            self._schedule()

    def _schedule(self):
        self.timer.stop()
        if self.deadlines:
            self.timer.start(max(1, math.ceil((min(self.deadlines.values()) - time.monotonic()) * 1000)))

    def _expire(self):
        now = time.monotonic()
        expired = {key for key, deadline in self.deadlines.items() if deadline <= now}
        self.collapsed_ids.update(expired)
        for key in expired:
            self.deadlines.pop(key, None)
        self._schedule()
        if expired:
            self.changed.emit()

    def set_events(self, events):
        ids = {str(item.get('id') or item.get('super_chat_id') or '') for item in events}
        added = ids - self.ids
        self.ids = ids
        self.collapsed_ids.intersection_update(ids)
        self.deadlines = {key: deadline for key, deadline in self.deadlines.items() if key in ids}
        if not ids:
            self.entrance.stop()
            self.progress = 1.0
        for key in added:
            self.deadlines[key] = time.monotonic() + self.delay
        self._schedule()
        if added and motion.enabled():
            self.entrance.stop()
            self.entrance.start()

    def expand(self, chat_id=None, *, animate=False):
        keys = self.ids if chat_id is None else {str(chat_id)} & self.ids
        self.collapsed_ids.difference_update(keys)
        for key in keys:
            self.deadlines[key] = time.monotonic() + self.delay
        self._schedule()
        self.entrance.stop()
        self.progress = 1.0
        if animate and motion.enabled():
            self.entrance.start()
        self.changed.emit()

    def collapse(self, chat_id=None):
        self.entrance.stop()
        self.progress = 1.0
        keys = self.ids if chat_id is None else {str(chat_id)} & self.ids
        self.collapsed_ids.update(keys)
        for key in keys:
            self.deadlines.pop(key, None)
        self._schedule()
        self.changed.emit()

    def _reveal(self, value):
        self.progress = float(value)
        self.changed.emit()
