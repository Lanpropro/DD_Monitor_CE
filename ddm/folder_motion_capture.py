"""Folder expansion motion capture and its opt-in window hook."""
import functools
import json
import sys
import time
from .responsiveness_probe import stack_locations, Probe


class FolderMotionCapture:
    """Record bounded layout/position evidence only around a real folder click."""
    def __init__(self, probe, sidebar, *, extended=False):
        from PySide6.QtCore import QTimer
        self.probe, self.sidebar = probe, sidebar
        self.record = None
        self.timer = QTimer(sidebar)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.frame)
        self.toggle = sidebar.toggle_folder
        self.relayout = sidebar.list_box.relayout
        self.evidence = None
        if extended:
            from .sidebar_diagnostics import SidebarEvidence
            self.evidence = SidebarEvidence(sidebar, probe)
            self.timer.setInterval(100)
        sidebar.toggle_folder = self.toggle_folder
        sidebar.list_box.relayout = self.layout
        if extended:
            self.snapshot(action='startup')

    def snapshot(self, *, action='manual-snapshot'):
        """Capture a persistent misalignment even when no folder was just clicked."""
        if self.probe.stopped.is_set():
            return
        self.finish('manual-snapshot')
        self.started = time.perf_counter()
        sidebar = self.sidebar
        self.entries = list(sidebar._items) + list(sidebar._folder_buttons.values())
        self.entries += list(sidebar._smart_cards.values())
        self.record = {'action': action, 'side': sidebar.side,
            'card_mode': sidebar.card_mode, 'collapsed': sidebar.collapsed,
            'collapse_animating': sidebar._collapse_animating,
            'item_size': list(sidebar.list_box.item_size()),
            'visible_items': len(sidebar.visible_items()),
            'folders': [{'index': index, 'collapsed': folder['collapsed'],
                         'member_count': sum(value == folder['id']
                             for value in sidebar._folder_assignments.values())}
                        for index, folder in enumerate(sidebar.folders)],
            'frames': [], 'layouts': []}
        self.begin_evidence()
        self.frame()
        self.timer.start()

    def toggle_folder(self, folder_id, *, animate=False):
        if self.probe.stopped.is_set():
            return self.toggle(folder_id, animate=animate)
        self.finish('superseded')
        folder = self.sidebar.get_folder(folder_id)
        if folder is None:
            return self.toggle(folder_id, animate=animate)
        self.started = time.perf_counter()
        self.record = {'folder_index': self.sidebar.folders.index(folder),
            'opening': bool(folder['collapsed']), 'animate_requested': bool(animate),
            'side': self.sidebar.side, 'card_mode': self.sidebar.card_mode,
            'frames': [], 'layouts': []}
        self.begin_evidence()
        self.entries = list(self.sidebar._items) + list(self.sidebar._folder_buttons.values())
        self.entries += list(self.sidebar._smart_cards.values())
        self.frame()
        try:
            result = self.toggle(folder_id, animate=animate)
        except BaseException:
            self.finish('error')
            raise
        self.record['toggle_ms'] = round((time.perf_counter() - self.started) * 1000, 3)
        for entry in self.sidebar._smart_cards.values():
            if entry not in self.entries:
                self.entries.append(entry)
        self.frame()
        if self.record is not None:
            self.timer.start()
        return result

    def layout(self, *args, **kwargs):
        record = self.record
        if (record is None and self.evidence is None) or self.probe.stopped.is_set():
            return self.relayout(*args, **kwargs)
        evidence = self.evidence
        if evidence is not None:
            evidence.generation += 1
            evidence.depth += 1
            evidence.mark('layout:before', animate=bool(kwargs.get('animate', args[0] if args else False)),
                          skipped_by_collapse=self.sidebar._collapse_animating,
                          callers=stack_locations(sys._getframe(1))[:6])
        running = self.running_animations()
        started = time.perf_counter()
        callers = stack_locations(sys._getframe(1))[:6]
        try:
            return self.relayout(*args, **kwargs)
        finally:
            if record is not None and len(record['layouts']) < 24:
                record['layouts'].append({'at_ms': round((started - self.started) * 1000, 3),
                    'duration_ms': round((time.perf_counter() - started) * 1000, 3),
                    'animate': bool(kwargs.get('animate', args[0] if args else False)),
                    'running_before': running, 'callers': callers})
            if evidence is not None:
                evidence.depth -= 1
                evidence.mark('layout:after', elapsed_ms=round((time.perf_counter() - started) * 1000, 3))
                evidence.sync()

    def begin_evidence(self):
        if self.evidence is not None:
            self.record.update(schema=2, before=list(self.evidence.history),
                               history_interval_ms=500, post_window_ms=2000,
                               evidence_clock=dict(qpc_origin=self.evidence.started,
                                   wall_origin=self.evidence.wall_started,
                                   frame_origin_ms=round((self.started - self.evidence.started) * 1000, 3)),
                               evidence_before=self.evidence.inspect(detail=True))

    def running_animations(self):
        running = 0
        for animation in self.sidebar.list_box._animations.values():
            try:
                running += animation.state().name in ('Running', 'Paused')
            except RuntimeError:  # Removing a room/folder deletes its child animations.
                continue
        return running

    def frame(self):
        record = self.record
        if record is None:
            return
        if self.probe.stopped.is_set():
            self.timer.stop()
            self.record = None
            return
        sidebar = self.sidebar
        elapsed = (time.perf_counter() - self.started) * 1000
        bar = sidebar.scroll.horizontalScrollBar() if sidebar.side == 'top' else sidebar.scroll.verticalScrollBar()
        viewport = sidebar.scroll.viewport()
        # Numbers are capture-local row indexes, never room IDs or folder names.
        rows = []
        stacking = {child: index for index, child in enumerate(sidebar.list_box.children())}
        for index, entry in enumerate(self.entries):
            try:
                if entry.isHidden():
                    continue
                rect = entry.geometry()
                along = rect.x() if sidebar.side == 'top' else rect.y()
                extent = rect.width() if sidebar.side == 'top' else rect.height()
                span = viewport.width() if sidebar.side == 'top' else viewport.height()
                if along + extent < bar.value() or along > bar.value() + span:
                    continue
                animation = sidebar.list_box._animations.get(entry)
                target = animation.endValue() if animation is not None else entry.pos()
                rows.append({'row': index, 'rect': list(rect.getRect()),
                    'stack': stacking.get(entry), 'target': [target.x(), target.y()],
                    'animation_ms': [animation.currentTime(), animation.duration()]
                        if animation is not None else None})
            except RuntimeError:  # A smart-folder copy can be deleted during refresh.
                continue
            if len(rows) == 16:
                break
        record['frames'].append({'at_ms': round(elapsed, 3), 'scroll': bar.value(),
            'scroll_max': bar.maximum(), 'content': [sidebar.list_box.width(), sidebar.list_box.height()],
            'running': self.running_animations(),
            'rows': rows})
        if self.evidence is not None:
            record['frames'][-1].update(generation=self.evidence.generation, depth=self.evidence.depth)
        if elapsed >= (2000 if self.evidence is not None else 600) or len(record['frames']) >= 40:
            self.finish('complete')

    def finish(self, reason='closing'):
        self.timer.stop()
        record, self.record = self.record, None
        if record is not None and not self.probe.stopped.is_set():
            if self.evidence is not None:
                record.update(evidence_after=self.evidence.inspect(detail=True),
                              evidence_samples=[state for state in self.evidence.history
                                  if state['at_ms'] >= record['evidence_before']['at_ms']],
                              events=list(self.evidence.events), motion_events=list(self.evidence.motion_events),
                              ring_dropped_total=max(0, self.evidence.sequence - len(self.evidence.events) - len(self.evidence.motion_events)))
                # Keep a complete JSON line below the collector's 256KiB line limit.
                packing = time.perf_counter()
                size = len(json.dumps(record, ensure_ascii=False).encode('utf-8'))
                trimmed = {}
                for key in ('before', 'frames', 'motion_events', 'events', 'evidence_samples'):
                    while size > 240 * 1024 and len(record[key]) > (1 if key == 'frames' else 0):
                        removed = record[key].pop(0)
                        size -= len(json.dumps(removed, ensure_ascii=False).encode('utf-8')) + 2
                        trimmed[key] = trimmed.get(key, 0) + 1
                record['trimmed'] = trimmed
                record['packing_ms'] = round((time.perf_counter() - packing) * 1000, 3)
            self.probe.write('folder-motion', reason=reason, **record)

    def close(self):
        self.finish()
        if self.evidence is not None:
            self.evidence.stop()


def install_folder_capture(path, *, extended=False):
    """Source launcher: capture folder clicks without the full responsiveness profiler."""
    from . import responsiveness as capture_api
    from PySide6.QtWidgets import QApplication
    from .app import MainWindow

    original = MainWindow.__init__

    @functools.wraps(original)
    def initialize(window, *args, **kwargs):
        original(window, *args, **kwargs)
        probe = capture_api.Probe(path)
        window._folder_motion_probe = capture_api.FolderMotionCapture(probe, window.sidebar, extended=extended)
        QApplication.instance().aboutToQuit.connect(window._folder_motion_probe.close)
        QApplication.instance().aboutToQuit.connect(probe.stop)
        window.destroyed.connect(probe.stop)
        probe.write('start', mode='folders-only')

    MainWindow.__init__ = initialize
