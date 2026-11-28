"""Bounded measurements of real sidebar gestures on a running host."""
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer

from .heartbeat_stacks import HeartbeatStacks
from .sidebar_drag import ROOM_MIME
from .sidebar_item import NavItem
from .startup_scroll_diagnostics import ScrollCapture


class SidebarPerformance(QObject):
    def __init__(self, window, emit, done, seconds):
        super().__init__(window)
        self.sidebar, self.emit, self.done = window.sidebar, emit, done
        self.seconds = seconds
        self.stopped = threading.Event()
        self.scroll = None
        self.hooks = []
        self.phases, self.heartbeat, self.scrolling = {}, {}, {}
        self.outcomes = dict(accepted=0, rejected=0, cancelled=0)
        self.activities = set()
        self.dropping = False
        self.sampler = HeartbeatStacks()
        self.slow_intervals = {}
        self.picker_started = None
        self.picker_paints = []
        self.returning_wall = False
        self.beat = QTimer(self)
        self.beat.setTimerType(Qt.PreciseTimer)
        self.beat.timeout.connect(self.pulse)
        self.limit = QTimer(self)
        self.limit.setSingleShot(True)
        self.limit.timeout.connect(self.finish)

    def start(self):
        self.scroll = ScrollCapture(self.sidebar, self)
        session = self.sidebar.drag_session
        def card_drag():
            return session.mime is not None and session.mime.hasFormat(ROOM_MIME) and session.plugin_owner is None

        self.hook(NavItem, '_drag_pixmap', 'card-pixmap', lambda item, *_: item.drop_host is self.sidebar)
        self.hook(session, 'start', 'drag-start', lambda source, mime, *a, **kw:
                  not session.active and mime.hasFormat(ROOM_MIME) and kw.get('plugin_owner') is None)
        for name, label in (('_update_target', 'drag-target'), ('finish', 'drop'), ('_cleanup', 'drag-cleanup')):
            self.hook(session, name, label, card_drag)
        self.hook(self.sidebar.items_control, 'refresh_visible_covers', 'scroll-covers',
                  lambda: self.scroll.record is not None)
        pip = getattr(self.sidebar.window(), 'picture_in_picture', None)
        if pip is not None:
            from .pip_picker import PictureInPictureDialog
            self.hook(pip, 'restore', 'pip-return', lambda **_: pip.moves_main_wall)
            wall = pip.host.wall
            def returning(*_args, **_kwargs):
                return self.returning_wall
            for owner, method, label in ((pip.host._content.layout(), 'insertWidget', 'attach'),
                                         (wall, 'set_picture_in_picture', 'layout'),
                                         (wall, 'show', 'show'), (pip, '_sync_overlays', 'overlays'),
                                         (pip.host._tray, 'restore', 'activate')):
                self.hook(owner, method, 'pip-return-' + label, returning)
            self.hook(pip, 'manage', 'picker-open', lambda **kw: kw.get('anchor') is not None and pip.dialog is None)
            self.hook(PictureInPictureDialog, '__init__', 'picker-build',
                      lambda dialog, controller, **kw: controller is pip and kw.get('compact'))
            def own_dialog(dialog, *args, **kwargs):
                return (getattr(dialog, 'controller', None) is pip and dialog._compact
                        and self.picker_started is not None)
            for method, label in (('_create_choice', 'picker-choice'), ('_arrange_choices', 'picker-grid'),
                                  ('_refresh', 'picker-preview'), ('attach_to_toolbar', 'picker-attach'),
                                  ('show', 'picker-show'), ('paintEvent', 'picker-paint')):
                self.hook(PictureInPictureDialog, method, label, own_dialog)
        self.sampler.pulse(time.perf_counter())
        self.sampler.worker.start()
        self.beat.start(16)
        self.limit.start(self.seconds * 1000)

    def hook(self, owner, name, label, relevant):
        original = getattr(owner, name)
        existed = name in vars(owner)
        if label.startswith('pip-return'):
            activity = 'pip-return'
        elif label.startswith('picker-'):
            activity = 'picker'
        else:
            activity = 'scroll' if label == 'scroll-covers' else 'drag'

        def measured(*args, **kwargs):
            if self.stopped.is_set() or not relevant(*args, **kwargs):
                return original(*args, **kwargs)
            self.activities.add(activity)
            if label == 'pip-return':
                self.returning_wall = True
            if label == 'drop':
                self.dropping = True
            started = time.perf_counter()
            if label == 'picker-open':
                self.picker_started = started
            try:
                result = original(*args, **kwargs)
                if label == 'drop':
                    self.outcomes['accepted' if result else 'rejected'] += 1
                elif label == 'drag-cleanup' and not self.dropping:
                    self.outcomes['cancelled'] += 1
                return result
            finally:
                if label == 'pip-return':
                    self.returning_wall = False
                if label == 'drop':
                    self.dropping = False
                elapsed = round((time.perf_counter() - started) * 1000, 3)
                phase = self.phases.setdefault(label, dict(calls=0, max_ms=0, total_ms=0))
                phase['calls'] += 1
                phase['total_ms'] = round(phase['total_ms'] + elapsed, 3)
                phase['max_ms'] = max(phase['max_ms'], elapsed)
                if label == 'picker-paint' and self.picker_started is not None:
                    self.picker_paints.append(round((time.perf_counter() - self.picker_started) * 1000, 3))
                    self.picker_started = None
        setattr(owner, name, measured)
        self.hooks.append((owner, name, measured, original, existed))

    def write(self, stage, **values):
        self.activities.add('scroll')
        if stage == 'sidebar-scroll-end':
            axis = self.scrolling.setdefault(values['axis'], dict(bursts=0, changes=0, active_ms=0,
                                                                   max_change_gap_ms=0))
            axis['bursts'] += 1
            axis['changes'] += values['changes']
            axis['active_ms'] += values['active_ms']
            axis['max_change_gap_ms'] = max(axis['max_change_gap_ms'], values['max_change_gap_ms'])

    def pulse(self):
        now = time.perf_counter()
        elapsed, samples = self.sampler.pulse(now)
        session = self.sidebar.drag_session
        if session.mime is not None and session.mime.hasFormat(ROOM_MIME) and session.plugin_owner is None:
            self.activities.add('drag')
        if self.scroll.timer.isActive():
            self.activities.add('scroll')
        label = '+'.join(sorted(self.activities)) or 'idle'
        self.activities.clear()
        stats = self.heartbeat.setdefault(label, dict(intervals=0, max_ms=0, over_50_ms=0, over_250_ms=0))
        stats['intervals'] += 1
        stats['max_ms'] = max(stats['max_ms'], elapsed)
        stats['over_50_ms'] += elapsed >= 50
        stats['over_250_ms'] += elapsed >= 250
        if elapsed >= 50:
            longest = self.slow_intervals.setdefault(label, [])
            longest.append(dict(duration_ms=elapsed, samples=samples))
            longest.sort(key=lambda entry: entry['duration_ms'], reverse=True)
            del longest[3:]

    def finish(self):
        self.pulse()
        self.scroll.finish()
        self.emit('sidebar-performance', phases=self.phases, drag_outcomes=self.outcomes,
                  scroll=self.scrolling, viewport_wheels=self.scroll.total_wheels, heartbeat=self.heartbeat,
                  slow_intervals=self.slow_intervals, picker_first_paint_ms=self.picker_paints)
        self.done('window-ended')

    def stop(self):
        if self.stopped.is_set():
            return
        self.stopped.set()
        self.sampler.stop()
        self.limit.stop()
        self.beat.stop()
        if self.scroll is not None:
            self.scroll.detach()
        for owner, name, measured, original, existed in reversed(self.hooks):
            if getattr(owner, name) is measured:
                if existed:
                    setattr(owner, name, original)
                else:
                    delattr(owner, name)
        self.hooks.clear()
        self.deleteLater()
