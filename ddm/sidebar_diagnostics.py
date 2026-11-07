"""GUI-thread evidence for issue 149; never lay out, paint or create native windows."""
from collections import deque
import ctypes
from ctypes import wintypes
import functools
import sys
import time
import weakref

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid


class SidebarEvidence(QObject):
    ROW_LIMIT = 16
    MODEL_LIMIT = 512

    def __init__(self, sidebar, probe):
        super().__init__(sidebar)
        self.sidebar, self.probe = sidebar, probe
        self.started = time.perf_counter()
        self.wall_started = time.time()
        self.events = deque(maxlen=96)
        self.motion_events = deque(maxlen=64)
        self.history = deque(maxlen=20)
        self.stats = weakref.WeakKeyDictionary()
        self.animations = weakref.WeakKeyDictionary()
        self.originals = []
        self.generation = self.sequence = self.depth = 0
        self.next_row = 0
        self.closed = False
        self.preview_timers = []
        self.user32 = None
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self.user32 = ctypes.WinDLL('user32', use_last_error=True)
            self.user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
            self.user32.GetParent.argtypes = (wintypes.HWND,)
            self.user32.GetParent.restype = wintypes.HWND
            self.user32.IsWindowVisible.argtypes = (wintypes.HWND,)
            self.user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
            if hasattr(self.user32, 'GetDpiForWindow'):
                self.user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
        for name in ('resort', 'refresh_filter', 'start_folder_drag', 'end_folder_drag',
                     'end_drag', 'set_collapsed', 'set_compact_policy'):
            self.wrap(sidebar, name, 'sidebar.' + name)
        # cancel is also a Qt signal slot; keep its identity stable for disconnect().
        for name in ('start', 'finish', '_cleanup'):
            self.wrap(sidebar.drag_session, name, 'drag.' + name)
        self.wrap(sidebar.list_box, '_glide_to', 'row-target', target=True)
        preview = getattr(sidebar.window(), 'hover_preview', None)
        if preview is not None:
            for name in ('_show_now', '_stop_now', '_on_resolved'):
                self.wrap(preview, name, 'preview.' + name)
            for timer, stage in ((preview._delay, 'preview:delay-fired'), (preview._grace, 'preview:grace-fired')):
                timer.timeout.connect(self.preview_tick)
                self.preview_timers.append((timer, stage))
        self.sync()
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.poll()

    def mark(self, stage, **values):
        if self.closed or self.probe.stopped.is_set():
            return
        self.sequence += 1
        journal = self.motion_events if stage.startswith(('widget:Move', 'widget:Resize', 'row-target', 'animation:state')) else self.events
        journal.append(dict(seq=self.sequence, at_ms=self.milliseconds(),
                            stage=stage, generation=self.generation, **values))

    def preview_tick(self):
        for timer, stage in self.preview_timers:
            if timer is self.sender():
                self.mark(stage)

    def milliseconds(self):
        return round((time.perf_counter() - self.started) * 1000, 3)

    def watch(self, widget, role):
        if widget is not None and isValid(widget) and widget not in self.stats:
            self.stats[widget] = dict(row=self.next_row, role=role, paints=0,
                                      updates=0, last_paint_ms=None, last_geometry_ms=-1000)
            self.next_row += 1
            widget.installEventFilter(self)

    def sync(self):
        sidebar = self.sidebar
        for widget, role in ((sidebar, 'sidebar'), (sidebar.window(), 'owner'), (sidebar.scroll.viewport(), 'viewport'),
                             (sidebar.list_box, 'content')):
            self.watch(widget, role)
        for entry in sidebar._items + list(sidebar._folder_buttons.values()) + list(sidebar._smart_cards.values()):
            self.watch(entry, 'folder' if entry in sidebar._folder_buttons.values() else 'card')
            thumb = getattr(entry, 'thumb', None)
            if thumb is not None:
                self.watch(thumb, 'thumbnail')
                self.watch(thumb.video, 'preview-video')
        preview = getattr(sidebar.window(), 'hover_preview', None)
        if preview is not None:
            self.watch(preview._popup, 'preview-popup')
            self.watch(preview._popup_video, 'popup-video')

    def wrap(self, owner, name, label, *, target=False):
        original = getattr(owner, name)
        @functools.wraps(original)
        def call(*args, **kwargs):
            if self.closed or self.probe.stopped.is_set():
                return original(*args, **kwargs)
            self.depth += 1
            started = time.perf_counter()
            extra = {}
            if target:
                self.watch(args[0], 'card')
                extra = dict(row=self.stats[args[0]]['row'], target=[args[1], args[2]])
            elif label == 'drag._cleanup':
                from .responsiveness import stack_locations
                extra = dict(callers=stack_locations(sys._getframe(1))[:5])
            self.mark(label + ':before', **extra)
            try:
                return original(*args, **kwargs)
            except BaseException as error:
                self.mark(label + ':error', error_type=type(error).__name__)
                raise
            finally:
                self.depth -= 1
                self.mark(label + ':after', elapsed_ms=round((time.perf_counter() - started) * 1000, 3), **extra)
                if not target:
                    self.sync()
                if target:
                    animation = self.sidebar.list_box._animations.get(args[0])
                    if animation is not None and animation not in self.animations:
                        self.animations[animation] = (weakref.ref(args[0]), self.generation)
                        animation.stateChanged.connect(self.animation_state)
                        animation.finished.connect(self.animation_finished)
                        self.animation_record(animation, 'animation:attached')
        setattr(owner, name, call)
        self.originals.append((owner, name, original, call))

    def animation_record(self, animation, stage):
        if self.closed or animation is None or not isValid(animation):
            return
        observed = self.animations.get(animation)
        entry = observed[0]() if observed else None
        if entry is not None and isValid(entry) and entry in self.stats:
            target = animation.endValue()
            self.mark(stage, row=self.stats[entry]['row'], state=animation.state().name,
                      born_generation=observed[1],
                      position=[entry.x(), entry.y()], target=[target.x(), target.y()],
                      animation_ms=[animation.currentTime(), animation.duration()])

    def animation_state(self, *_args):
        self.animation_record(self.sender(), 'animation:state')

    def animation_finished(self):
        self.animation_record(self.sender(), 'animation:finished')

    def eventFilter(self, watched, event):
        if self.closed or self.probe.stopped.is_set():
            return False
        state = self.stats.get(watched)
        if state is None:
            return False
        kind = event.type()
        if kind == QEvent.Paint:
            state['paints'] += 1
            state['last_paint_ms'] = self.milliseconds()
            state['paint_region'] = list(event.region().boundingRect().getRect())
        elif kind == QEvent.UpdateRequest:
            state['updates'] += 1
        elif kind in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide,
                      QEvent.WinIdChange, QEvent.ParentChange, QEvent.WindowDeactivate,
                      QEvent.UngrabMouse, QEvent.UngrabKeyboard, QEvent.Close,
                      QEvent.StyleChange, QEvent.FontChange, QEvent.WindowStateChange):
            now = self.milliseconds()
            if kind not in (QEvent.Move, QEvent.Resize) or now - state['last_geometry_ms'] >= 50:
                state['last_geometry_ms'] = now
                self.mark('widget:' + kind.name, row=state['row'], role=state['role'],
                          rect=list(watched.geometry().getRect()), hidden=watched.isHidden())
        return False

    def expected_layout(self):
        """Derive slots from model state, without calling folder_entries/relayout."""
        from . import follow_folders
        from .widget_support import (CAROUSEL_WIDTH, PORTRAIT_LIST_WIDTH, PORTRAIT_LIST_HEIGHT,
                              NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT, NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_GAP)
        sidebar = self.sidebar
        items = list(sidebar._items)
        assignments = follow_folders.assign_folders(sidebar.rooms(), sidebar.folders, sidebar._folder_pending)
        words = sidebar.filter_text.split()
        horizontal = sidebar.side == 'top'
        width = (CAROUSEL_WIDTH if sidebar.card_mode else PORTRAIT_LIST_WIDTH) if horizontal else sidebar.list_box.width()
        height = ((NAV_ITEM_HEIGHT if sidebar.card_mode else PORTRAIT_LIST_HEIGHT) if horizontal else
                  NAV_COMPACT_ITEM_HEIGHT if sidebar.collapsed else
                  NAV_ITEM_HEIGHT if sidebar.card_mode else NAV_LIST_ITEM_HEIGHT)
        order, missing = [], 0
        for folder in sidebar.folders:
            fid = folder['id']
            copies = folder['type'] == 'smart' and folder['rule'].get('display') == 'copy'
            matched = follow_folders.smart_members(sidebar.rooms(), sidebar.folders, folder, sidebar._folder_pending) if copies else None
            members = [item for item in items if (str(item.room['room_id']) in matched if copies else
                       assignments.get(str(item.room['room_id'])) == fid) and sidebar.matches(item, words, fid)]
            if words and not members:
                continue
            button = sidebar._folder_buttons.get(fid)
            if button is None:
                missing += 1
            order.append((button, True))
            folded = folder['collapsed'] and (not words or fid in sidebar._folders_folded_by_drag)
            if folded:
                continue
            if copies:
                positions = {rid: i for i, rid in enumerate(sidebar.import_order if folder['sort'] == 'imported' else sidebar.custom_order)}
                pins = {rid: i for i, rid in enumerate(sidebar.pinned)}
                def key(item):
                    rid = str(item.room['room_id'])
                    index = positions.get(rid, len(positions))
                    if folder['sort'] == 'frequent':
                        return ((False, pins.get(rid, index), 0, 0) if item.is_pinned else
                                (True, not bool(item.room.get('live')), -sidebar._frequent_scores.get(rid, 0), index))
                    value = (str(item.room.get('uname') or '').casefold() if folder['sort'] == 'name' else
                             bool(item.room.get('live')) != (folder['sort'] == 'live') if folder['sort'] in ('live', 'offline') else index)
                    return (not item.is_pinned, value, index)
                members.sort(key=key)
            for item in members:
                entry = sidebar._smart_cards.get((fid, str(item.room['room_id']))) if copies else item
                missing += entry is None
                order.append((entry, False))
        if not sidebar.folders:
            order = [(item, False) for item in items if sidebar.matches(item, words)]
        rectangles, run = {}, 0
        for entry, folder in order[:self.MODEL_LIMIT]:
            extent = max(36, entry.minimumSizeHint().height()) if folder and entry is not None else 36 if folder else (width if horizontal else height)
            rectangle = QRect(run if horizontal else 0, 0 if horizontal else run,
                              extent if folder and horizontal else width,
                              extent if folder and not horizontal else height)
            if entry is not None:
                rectangles[entry] = rectangle
            run += extent + NAV_ITEM_GAP
        return rectangles, dict(order_basis='current-model-order', extent=run if order else sidebar.list_box.EMPTY_HINT_HEIGHT,
            count=len(order), truncated=len(order) > self.MODEL_LIMIT, missing_widgets=missing,
            assignment_mismatches=sum(sidebar._folder_assignments.get(key) != value for key, value in assignments.items()))

    def widget_state(self, widget, *, native=False):
        state = self.stats.get(widget, {})
        result = {key: value for key, value in state.items() if key != 'last_geometry_ms'}
        point = widget.mapToGlobal(QPoint())
        parent = widget.parentWidget()
        result.update(rect=list(widget.geometry().getRect()), global_rect=[point.x(), point.y(), widget.width(), widget.height()],
                      hidden=widget.isHidden(), visible=widget.isVisible(), updates_enabled=widget.updatesEnabled(),
                      parent_row=self.stats.get(parent, {}).get('row') if parent is not None else None,
                      dpr=widget.devicePixelRatioF())
        if native:
            hwnd = int(widget.internalWinId())  # Never winId(): it changes the native hierarchy.
            result.update(hwnd=hex(hwnd), native_attribute=widget.testAttribute(Qt.WA_NativeWindow),
                          parent_class=type(parent).__name__ if parent is not None else None,
                          parent_hwnd=hex(int(parent.internalWinId())) if parent is not None else None,
                          is_window=widget.isWindow(),
                          no_native_ancestors=widget.testAttribute(Qt.WA_DontCreateNativeAncestors),
                          visible_region=list(widget.visibleRegion().boundingRect().getRect()),
                          mask=list(widget.mask().boundingRect().getRect()))
            if hwnd and self.user32 is not None:
                rect = wintypes.RECT()
                if hasattr(self.user32, 'GetDpiForWindow'):
                    result['native_dpi'] = self.user32.GetDpiForWindow(hwnd)
                if self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    result['native'] = dict(rect=[rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
                        parent=hex(self.user32.GetParent(hwnd) or 0), visible=bool(self.user32.IsWindowVisible(hwnd)))
        return result

    def inspect(self, *, detail=False):
        started = time.perf_counter()
        self.sync()
        sidebar, box = self.sidebar, self.sidebar.list_box
        expected, model = self.expected_layout()
        viewport = sidebar.scroll.viewport()
        visible = QRect(box.mapFrom(viewport, QPoint()), viewport.size())
        entries = sidebar._items + list(sidebar._folder_buttons.values()) + list(sidebar._smart_cards.values())
        rows, mismatches = [], 0
        for entry in entries:
            if not isValid(entry):
                continue
            rectangle = expected.get(entry)
            mismatch = ((rectangle is not None and (entry.isHidden() or entry.geometry() != rectangle)) or
                        (rectangle is None and not entry.isHidden() and not model['truncated']))
            mismatches += bool(mismatch)
            relevant = (not entry.isHidden() and entry.geometry().intersects(visible)) or (rectangle is not None and rectangle.intersects(visible))
            if relevant and len(rows) < self.ROW_LIMIT:
                row = self.widget_state(entry)
                row.update(expected=list(rectangle.getRect()) if rectangle is not None else None,
                           mismatch=bool(mismatch), filtered=bool(getattr(entry, 'filtered_out', False)))
                rows.append(row)
        drag = sidebar.drag_session
        bar = sidebar.scroll.horizontalScrollBar() if sidebar.side == 'top' else sidebar.scroll.verticalScrollBar()
        running = sum(animation.state().name in ('Running', 'Paused') for animation in box._animations.values() if isValid(animation))
        result = dict(at_ms=self.milliseconds(), generation=self.generation, depth=self.depth,
            model=model, mismatches=mismatches, running=running,
            in_transition=bool(self.depth or running or drag.active or sidebar._collapse_animating),
            side=sidebar.side, card_mode=sidebar.card_mode, collapsed=sidebar.collapsed,
            visible=sidebar.isVisible(),
            compact_policy=dict(preferred=sidebar.preferred_card_mode, automatic=sidebar.auto_compact,
                                threshold=sidebar.compact_threshold, room_count=len(sidebar._items)),
            collapse_animating=sidebar._collapse_animating, rows=rows,
            scroll=[bar.value(), bar.minimum(), bar.maximum(), bar.pageStep()],
            content=dict(rect=list(box.geometry().getRect()), minimum=[box.minimumWidth(), box.minimumHeight()],
                         maximum=[box.maximumWidth(), box.maximumHeight()]),
            drag=dict(active=drag.active, ghost=drag.ghost is not None, target=type(drag.target).__name__ if drag.target else None,
                      restore_count=len(sidebar._folder_drag_previous), temporary_fold_count=len(sidebar._folders_folded_by_drag),
                      mouse_grab=QWidget.mouseGrabber() is sidebar.window(), keyboard_grab=QWidget.keyboardGrabber() is sidebar.window(),
                      qt_left=bool(QApplication.mouseButtons() & Qt.LeftButton)))
        result['folders'] = []
        for index, folder in enumerate(sidebar.folders[:32]):
            button = sidebar._folder_buttons.get(folder['id'])
            rectangle = expected.get(button) if button is not None else None
            result['folders'].append(dict(index=index, collapsed=folder['collapsed'],
                temporary=folder['id'] in sidebar._folders_folded_by_drag,
                restore_to=sidebar._folder_drag_previous.get(folder['id']),
                rect=list(button.geometry().getRect()) if button is not None else None,
                expected=list(rectangle.getRect()) if rectangle is not None else None))
        result['folders_truncated'] = len(sidebar.folders) > 32
        if self.user32 is not None:
            result['drag']['native_left'] = bool(self.user32.GetAsyncKeyState(1) & 0x8000)
        if detail:
            screen = sidebar.screen()
            result['screen'] = dict(rect=list(screen.geometry().getRect()), dpr=screen.devicePixelRatio()) if screen else None
            selected = list(dict.fromkeys((sidebar, sidebar.window(), viewport, box)))
            selected += [entry for entry in entries if not entry.isHidden() and entry.geometry().intersects(visible)][:8]
            selected += [entry.thumb.video for entry in selected[:] if hasattr(entry, 'thumb')]
            hidden_native = []
            for entry in sidebar._items:
                if entry.isHidden() or not entry.geometry().intersects(visible):
                    group = (entry, entry.thumb, entry.thumb.video)
                    if any(widget.internalWinId() for widget in group):
                        hidden_native.append(group)
            for group in hidden_native[:4]:
                selected.extend(widget for widget in group if widget not in selected)
            result['hidden_native_candidates'] = len(hidden_native)
            result['hidden_native_truncated'] = len(hidden_native) > 4
            preview = getattr(sidebar.window(), 'hover_preview', None)
            if preview is not None:
                selected += [preview._popup, preview._popup_video]
                result['preview'] = dict(playing=preview._popup_playing, paused=preview._interaction_paused,
                                         resolving=preview._resolver is not None)
            result['widgets'] = [self.widget_state(widget, native=True) for widget in selected]
        result['capture_ms'] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def poll(self):
        if self.closed or self.probe.stopped.is_set():
            self.stop()
            return
        self.history.append(self.inspect())

    def stop(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        for timer, _stage in self.preview_timers:
            if isValid(timer):
                timer.timeout.disconnect(self.preview_tick)
        self.preview_timers.clear()
        for widget in list(self.stats):
            if isValid(widget):
                widget.removeEventFilter(self)
        for owner, name, original, wrapped in reversed(self.originals):
            if isValid(owner) and getattr(owner, name) is wrapped:
                setattr(owner, name, original)
        self.originals.clear()
