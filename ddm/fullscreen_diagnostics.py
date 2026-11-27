"""Bounded fullscreen evidence; never poll mpv properties on the GUI thread."""
import cProfile
import functools
import sys
import threading
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PySide6.QtGui import QCursor, QKeySequence, QWindow
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QWidget

from .responsiveness import Probe, profile_functions
from . import window_fullscreen


def _key_queue_ms(timestamp):
    if sys.platform != 'win32':
        return None
    return window_fullscreen.key_message_age_ms(timestamp, window_fullscreen.keyboard_tick_ms())


class FullscreenCapture(QObject):
    PROPERTIES = ('time-pos', 'audio-pts', 'pause', 'paused-for-cache',
                  'vo-configured', 'frame-drop-count')

    def __init__(self, probe, window, *, profile_calls=False, native_windows=False):
        super().__init__(window)
        self.probe, self.window = probe, window
        self.profile_calls = profile_calls
        self.native_windows = native_windows
        self.key_samples = 0
        self.record = None
        self.depth = 0
        self.lock = threading.Lock()
        self.observers = []
        self.players = []
        self.geometry_widgets = {}
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.frame)
        self.idle_samples = []
        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(125)
        self.idle_timer.timeout.connect(self.idle_frame)

    def start_idle(self, tile):
        if not hasattr(self.window, '_fullscreen_cursor'):
            return
        self.idle_tile = tile
        self.idle_started = time.monotonic()
        self.idle_samples = []
        self.idle_timer.start()
        self.idle_frame()

    def idle_frame(self):
        tile, cursor = self.idle_tile, self.window._fullscreen_cursor
        now = time.monotonic()
        point = QCursor.pos()
        focus = QApplication.focusWidget()
        self.idle_samples.append({
            'at_ms': round((now-self.idle_started)*1000),
            'cursor_hidden': cursor.hidden, 'cursor_timer': cursor.timer.isActive(),
            'idle_ms': round((now-cursor._last_move)*1000),
            'hide_bar': bool(self.window.settings.get('fullscreen_auto_hide_controls', True)),
            'pointer_video': tile.video.rect().contains(tile.video.mapFromGlobal(point)),
            'focus': type(focus).__name__ if focus is not None else None,
            'interaction': tile.plugin_interaction_active(),
            'controls_hidden': getattr(tile, '_fullscreen_controls_hidden', False),
            'bar_target': tile._bar_target, 'bar_progress': tile._bar_progress,
            'bar_visible': tile.bottom.isVisible(),
            'animation_state': tile._bar_animation.state().name,
            'animation_ms': tile._bar_animation.currentTime(),
            'animation_signals_blocked': tile._bar_animation.signalsBlocked(),
            'bar_clock': tile._bar_clock.isActive(),
            'bar_rect': tile.bottom.geometry().getRect(),
            'bar_translucent': tile.bottom.testAttribute(Qt.WA_TranslucentBackground),
            'input_rects': [[edit.mapTo(tile.bottom, QPoint()).x(),
                             edit.mapTo(tile.bottom, QPoint()).y(), edit.width(), edit.height()]
                            for edit in tile.bottom.findChildren(QLineEdit) if edit.isVisible()],
        })
        if now-self.idle_started >= 8 or len(self.idle_samples) >= 65:
            self.finish_idle('limit')

    def finish_idle(self, reason='exit'):
        self.idle_timer.stop()
        if self.idle_samples:
            self.probe.write('fullscreen-idle', reason=reason, samples=self.idle_samples)
            self.idle_samples = []

    def begin(self, action, tile):
        self.finish_idle('transition')
        self.finish('interrupted')
        self.target = tile
        self.started = time.perf_counter()
        self.returned = None
        self.record = {'action': action, 'frames': [], 'stages': {}, 'events': [], 'geometry': [],
                       'players': [], 'functions': []}
        tiles = self.window.wall.tiles
        watched = [(self.window, 'main'), (self.window.wall, 'wall')]
        sidebar = getattr(self.window, 'sidebar', None)
        if sidebar is not None:
            watched.extend(((sidebar, 'sidebar'), (sidebar.scroll.viewport(), 'sidebar-cards'),
                            (sidebar.account_row, 'sidebar-account'), (sidebar.navigation.rail, 'sidebar-rail')))
        watched += [(pane, 'target' if pane is tile else 'peer') for pane in tiles]
        watched.append((getattr(tile, 'video', None), 'video'))
        watched.append((getattr(tile, 'bottom', None), 'bar'))
        for widget, role in watched:
            if isinstance(widget, QWidget):
                self.geometry_widgets[widget] = role
                if not self.native_windows:
                    widget.installEventFilter(self)
        ordered = ([tile] if tile in tiles else []) + [other for other in tiles if other is not tile]
        for candidate in ordered:
            player = self.window.players.get(candidate)
            core = getattr(player, 'player', None)
            if core is None or getattr(player, '_released', False):
                continue
            item = {'tile': tiles.index(candidate), 'target': candidate is tile, 'values': {}, 'samples': []}
            self.record['players'].append(item)
            self.players.append((player, core, getattr(player, 'play_session', ''), item))
            record = self.record
            def changed(name, value, item=item, record=record):
                if name not in self.PROPERTIES or not isinstance(value, (int, float, bool, type(None))):
                    return
                with self.lock:
                    if self.record is not record:
                        return
                    item['values'][name] = value
                    now = round((time.perf_counter()-self.started)*1000, 3)
                    samples = item['samples']
                    if len(samples) < 120 and (not samples or now-samples[-1]['at_ms'] >= 40):
                        samples.append({'at_ms': now, **item['values']})
            for name in self.PROPERTIES:
                try:
                    core.observe_property(name, changed)
                    self.observers.append((core, name, changed))
                except (RuntimeError, ValueError):
                    continue
            if len(self.players) == 2:
                break
        self.record['observer_setup_ms'] = round((time.perf_counter()-self.started)*1000, 3)
        self.capture_native_windows(self.record, 'before')
        self.timer.start()
        self.frame()

    def capture_native_windows(self, record, stage):
        if not self.native_windows:
            return
        from .on_demand_diagnostics import native_snapshot
        snapshot = native_snapshot()
        if not snapshot['available']:
            return
        bars = {}
        for index, tile in enumerate(self.window.wall.tiles):
            bar = getattr(tile, 'bottom', None)
            if bar is not None and (hwnd := int(bar.internalWinId())):
                bars[hex(hwnd)] = index
        windows = [{key: row.get(key) for key in ('hwnd', 'parent', 'cls', 'rect', 'visible')}
                   for row in snapshot['windows'] if row['visible'] or row['hwnd'] in bars]
        record.setdefault('native_windows', []).append({
            'stage': stage, 'at_ms': round((time.perf_counter()-self.started)*1000, 3),
            'bars': bars, 'windows': windows, 'truncated': snapshot['truncated']})

    def eventFilter(self, watched, event):
        if (self.native_windows and event.type() in (QEvent.ShortcutOverride, QEvent.KeyRelease)
                and isinstance(watched, QWindow)):
            self._record_key(watched, event)
        record = self.record
        if (record is not None and watched in self.geometry_widgets
                and (event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide)
                     or (self.geometry_widgets[watched] in ('bar', 'sidebar', 'sidebar-cards',
                                                           'sidebar-account', 'sidebar-rail')
                         and event.type() == QEvent.Paint))
                and len(record['geometry']) < 96):
            origin = watched.mapToGlobal(QPoint())
            item = {'at_ms': round((time.perf_counter()-self.started)*1000, 3),
                'role': self.geometry_widgets[watched], 'event': event.type().name,
                'visible': watched.isVisible(), 'window': watched.isWindow(),
                'rect': [origin.x(), origin.y(), watched.width(), watched.height()]}
            if item['role'] == 'bar':
                item['opacity'] = watched.windowOpacity()
            record['geometry'].append(item)
        return super().eventFilter(watched, event)

    def _record_key(self, receiver, event):
        if (self.key_samples >= 512 or event.isAutoRepeat() or self.probe.stopped.is_set()
                or isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit, QTextEdit))):
            return
        host = self.window
        for action in ('focus', 'restore'):
            shortcut = QKeySequence(host.shortcuts.get(action, ''))
            if shortcut.count() == 1 and shortcut[0] == event.keyCombination():
                break
        else:
            return
        if receiver is not host.windowHandle() and not any(
                receiver is tile.windowHandle() or receiver is tile.bottom.windowHandle()
                for tile in host.wall.tiles):
            return
        edge = 'press' if event.type() == QEvent.ShortcutOverride else 'release'
        self.key_samples += 1
        self.probe.write('fullscreen-key', action=action, edge=edge, input_tick=event.timestamp(),
                         queue_ms=_key_queue_ms(event.timestamp()))

    def stage(self, name, started):
        record = self.record
        if record is None:
            return
        elapsed = (time.perf_counter()-started)*1000
        item = record['stages'].setdefault(name, {'calls': 0, 'total_ms': 0, 'max_ms': 0})
        item['calls'] += 1
        item['total_ms'] = round(item['total_ms']+elapsed, 3)
        item['max_ms'] = round(max(item['max_ms'], elapsed), 3)
        if len(record['events']) < 64:
            record['events'].append({'stage': name, 'at_ms': round((started-self.started)*1000, 3),
                                     'duration_ms': round(elapsed, 3)})

    def frame(self):
        record = self.record
        if record is None:
            return
        now = time.perf_counter()
        window = self.window
        pending = len(window.wall._pending_reveal)
        overlays = [getattr(tile, 'video_danmaku', None) for tile in window.wall.tiles]
        raster_pending = sum(overlay is not None and (overlay._comment_raster_job is not None
                             or overlay._comment_resize_timer.isActive()) for overlay in overlays)
        if len(record['frames']) < 80:
            record['frames'].append({'at_ms': round((now-self.started)*1000, 3),
                'cover': False, 'cover_opacity': None,  # Retain the previous capture schema for comparison.
                'fullscreen': window._fullscreen_tile is not None, 'pending_reveal': pending,
                'raster_pending': raster_pending,
                'independent': bool(getattr(self.target, 'isWindow', lambda: False)()),
                'resize_pending': window._resize_idle_timer.isActive(),
                'window_size': [window.width(), window.height()]})
        if now-self.started >= 8:
            self.finish('limit')
        elif (self.returned is not None and now-self.returned >= .5
                and not pending and not raster_pending and not window._resize_idle_timer.isActive()):
            self.finish('settled')

    def finish(self, reason='exit'):
        self.timer.stop()
        with self.lock:
            record, self.record = self.record, None
        if record is None:
            return
        self.capture_native_windows(record, reason)
        if not self.native_windows:
            for widget in self.geometry_widgets:
                widget.removeEventFilter(self)
        self.geometry_widgets.clear()
        for core, name, changed in self.observers:
            try:
                core.unobserve_property(name, changed)
            except (RuntimeError, ValueError):
                pass
        self.observers.clear()
        for player, core, session, item in self.players:
            item.update(core_changed=player.player is not core,
                        session_changed=getattr(player, 'play_session', '') != session)
        self.players.clear()
        self.probe.write('fullscreen', reason=reason,
                         duration_ms=round((time.perf_counter()-self.started)*1000, 3), **record)


def install(path, *, profile_calls=False, native_windows=False, window=None, cleanup=None):
    from PySide6.QtWidgets import QApplication
    from .app import MainWindow
    from .fullscreen_bar import FullscreenBar
    from .fullscreen_presentation import FullscreenPresentation
    from .tile_widgets import Tile
    from .wall_widgets import WallGrid
    from .video_danmaku import VideoDanmaku
    from . import window_fullscreen
    from .live_diagnostics import replace_hook

    probe = Probe(path)
    if cleanup is not None:
        cleanup.callback(probe.stop)
    original_init = MainWindow.__init__

    def attach(window):
        capture = window._fullscreen_probe = FullscreenCapture(
            probe, window, profile_calls=profile_calls, native_windows=native_windows)
        application = QApplication.instance()
        if native_windows:
            application.installEventFilter(capture)
        if cleanup is None:
            application.aboutToQuit.connect(capture.finish)
            application.aboutToQuit.connect(capture.finish_idle)
            application.aboutToQuit.connect(probe.stop)
        else:
            def detach():
                try:
                    capture.finish('capture-ended')
                    capture.finish_idle('capture-ended')
                finally:
                    if native_windows:
                        application.removeEventFilter(capture)
                    del window._fullscreen_probe
                    capture.deleteLater()
            cleanup.callback(detach)
            if window._fullscreen_tile is not None:
                capture.start_idle(window._fullscreen_tile)

    if window is None:
        @functools.wraps(original_init)
        def initialize(window, *args, **kwargs):
            original_init(window, *args, **kwargs)
            attach(window)
        MainWindow.__init__ = initialize
    else:
        if getattr(window, '_fullscreen_probe', None) is not None:
            raise ValueError('fullscreen-capture-active')
        attach(window)

    def operation(method, action):
        @functools.wraps(method)
        def wrapped(window, *args, **kwargs):
            capture = getattr(window, '_fullscreen_probe', None)
            if capture is None or capture.depth or probe.stopped.is_set():
                return method(window, *args, **kwargs)
            tile = args[0] if action == 'toggle' and args else window._fullscreen_tile
            if tile not in window.wall.tiles or (action == 'toggle' and not tile.room.get('room_id')):
                return method(window, *args, **kwargs)
            if action == 'toggle' and window._fullscreen_tile is not None and window._fullscreen_tile is not tile:
                return method(window, *args, **kwargs)
            direction = 'exit' if window._fullscreen_tile is tile else 'enter'
            capture.begin(direction, tile)
            capture.depth += 1
            profile = cProfile.Profile() if capture.profile_calls else None
            started = time.perf_counter()
            if profile is not None:
                profile.enable()
            failed = True
            try:
                result = method(window, *args, **kwargs)
                failed = False
                return result
            finally:
                if profile is not None:
                    profile.disable()
                capture.depth -= 1
                if capture.record is not None:
                    capture.record['call_ms'] = round((time.perf_counter()-started)*1000, 3)
                    capture.record['functions'] = profile_functions(profile) if profile is not None else []
                    capture.returned = time.perf_counter()
                    capture.capture_native_windows(capture.record, 'returned')
                    if failed:
                        capture.finish('exception')
                if not failed and direction == 'enter':
                    capture.start_idle(tile)
        return wrapped

    replace_hook(cleanup, MainWindow, '_on_fullscreen', operation(MainWindow._on_fullscreen, 'toggle'))
    replace_hook(cleanup, MainWindow, '_exit_fullscreen', operation(MainWindow._exit_fullscreen, 'exit'))

    def stage(method, label):
        @functools.wraps(method)
        def wrapped(owner, *args, **kwargs):
            window = owner.window if isinstance(owner, FullscreenPresentation) else owner
            while window is not None and not isinstance(window, MainWindow):
                window = window.parentWidget()
            capture = getattr(window, '_fullscreen_probe', None)
            if capture is None or capture.record is None:
                return method(owner, *args, **kwargs)
            started = time.perf_counter()
            try:
                return method(owner, *args, **kwargs)
            finally:
                measured = label
                if label == 'VideoDanmaku._resize_comments' and kwargs.get('redraw') is False:
                    measured += '.geometry'
                capture.stage(measured, started)
        return wrapped

    for owner, names in ((MainWindow, ('sync_danmaku', 'refresh_theme', '_refresh_meta', '_upgrade_fullscreen_quality')),
            (WallGrid, ('set_fullscreen_tile', 'relayout', 'reveal_tiles_staggered', '_sync_danmaku_controls')),
            (FullscreenPresentation, ('enter', 'leave')),
            (FullscreenBar, ('set_fullscreen', 'prepare_fullscreen_frame')),
            (Tile, ('_layout_areas',)),
            (VideoDanmaku, ('_resize_comments', '_queue_comment_raster', '_apply_comment_rasters'))):
        for name in names:
            replace_hook(cleanup, owner, name, stage(getattr(owner, name), owner.__name__+'.'+name))
    for name in ('enter', 'exit'):
        replace_hook(cleanup, window_fullscreen, name,
                     stage(getattr(window_fullscreen, name), 'window_fullscreen.'+name))
    probe.write('start', mode='fullscreen-only', profile_calls=profile_calls,
                frame_limit=80, observer_sample_limit=120, duration_limit_ms=8000)
    return probe
