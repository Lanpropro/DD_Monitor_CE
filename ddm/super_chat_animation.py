"""Super Chat runtime reveal and collapse deadlines; original QObject owns timers."""
from __future__ import annotations
import time
import math
from PySide6.QtCore import QObject, QTimer, QVariantAnimation, Signal
from . import motion
from .super_chat_model import DEFAULT_COLLAPSE_DELAY, _number


FIRST_REOPEN_DELAY = 5


class SuperChatPresentation(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.progress = 1.0
        self.delay = DEFAULT_COLLAPSE_DELAY
        self.ids = set()
        self._manual_reopens = {}
        self.collapsed_ids = set()
        self.compact_ids = set()
        self.compact = False
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

    def stays_expanded(self, chat_id):
        return self._manual_reopens.get(str(chat_id)) == 2

    def configure(self, settings):
        delay = max(1, min(60, _number(settings.get('super_chat_collapse_delay'), DEFAULT_COLLAPSE_DELAY)))
        if self.delay != delay:
            self.delay = delay
            now = time.monotonic()
            for key in self.deadlines:
                if key not in self._manual_reopens:
                    self.deadlines[key] = now + delay
            self._schedule()

    def _restart_deadline(self, key):
        if self.stays_expanded(key):
            self.deadlines.pop(key, None)
        else:
            delay = FIRST_REOPEN_DELAY if key in self._manual_reopens else self.delay
            self.deadlines[key] = time.monotonic() + delay

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
        self._manual_reopens = {key: count for key, count in self._manual_reopens.items() if key in ids}
        self.collapsed_ids.intersection_update(ids)
        self.compact_ids.intersection_update(ids)
        self.deadlines = {key: deadline for key, deadline in self.deadlines.items() if key in ids}
        if not ids:
            self.entrance.stop()
            self.progress = 1.0
        for key in added:
            if self.compact:
                self.collapsed_ids.add(key)
                self.compact_ids.add(key)
            else:
                self.deadlines[key] = time.monotonic() + self.delay
        self._schedule()
        if added and motion.enabled():
            self.entrance.stop()
            self.entrance.start()

    def set_compact(self, compact):
        if self.compact == compact:
            return
        self.compact = compact
        if compact:
            self.compact_ids = self.ids - self.collapsed_ids
            self.collapsed_ids.update(self.compact_ids)
            for key in self.compact_ids:
                self.deadlines.pop(key, None)
        else:
            self.collapsed_ids.difference_update(self.compact_ids)
            for key in self.compact_ids:
                self._restart_deadline(key)
            self.compact_ids.clear()
        self._schedule()
        if self.ids:
            self.changed.emit()

    def expand(self, chat_id=None, *, animate=False, manual=False):
        keys = self.ids if chat_id is None else {str(chat_id)} & self.ids
        if self.compact and chat_id is not None:
            others = self.ids - keys
            self.compact_ids.update(others - self.collapsed_ids)
            self.collapsed_ids.update(others)
            for key in others:
                self.deadlines.pop(key, None)
        for key in keys:
            if manual and key in self.collapsed_ids:
                self._manual_reopens[key] = min(2, self._manual_reopens.get(key, 0) + 1)
            if key not in self._manual_reopens or key in self.collapsed_ids:
                self._restart_deadline(key)
        self.collapsed_ids.difference_update(keys)
        self.compact_ids.difference_update(keys)
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
        self.compact_ids.difference_update(keys)
        for key in keys:
            self.deadlines.pop(key, None)
        self._schedule()
        self.changed.emit()

    def _reveal(self, value):
        self.progress = float(value)
        self.changed.emit()
