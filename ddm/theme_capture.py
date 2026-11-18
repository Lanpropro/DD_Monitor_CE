"""Opt-in theme-switch and animation capture hooks."""
import cProfile
import functools
import sys
import time
from .responsiveness_probe import profile_functions, Probe


def install_theme_capture(path, *, profile_calls=False):
    """Measure actual theme changes without a continuous sampler."""
    from . import responsiveness as capture_api
    import atexit
    from .theme_transition import ThemeTransition
    from . import theme

    probe = capture_api.Probe(path)
    original = ThemeTransition.change
    apply_theme = theme.apply
    transition_depth = 0

    @functools.wraps(apply_theme)
    def apply(mode):
        if probe.stopped.is_set():
            return apply_theme(mode)
        started = time.perf_counter()
        source = 'transition' if transition_depth else 'direct'
        profile = cProfile.Profile() if profile_calls and not transition_depth and sys.getprofile() is None else None
        if profile is not None:
            profile.enable()
        try:
            return apply_theme(mode)
        finally:
            if profile is not None:
                profile.disable()
            probe.write('theme-apply', mode=theme.normalize_mode(mode), source=source,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                functions=capture_api.profile_functions(profile) if profile is not None else [])

    @functools.wraps(original)
    def change(transition, mode, *args, **kwargs):
        nonlocal transition_depth
        if probe.stopped.is_set():
            return original(transition, mode, *args, **kwargs)
        profile = cProfile.Profile() if profile_calls else None
        started = time.perf_counter()
        transition._theme_request_started = started
        if profile is not None:
            profile.enable()
        transition_depth += 1
        try:
            return original(transition, mode, *args, **kwargs)
        finally:
            transition_depth -= 1
            if profile is not None:
                profile.disable()
            probe.write('theme-switch', mode=theme.normalize_mode(mode),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                functions=capture_api.profile_functions(profile) if profile is not None else [])

    ThemeTransition.change = change
    theme.apply = apply
    _install_settings_paint_capture(probe)
    atexit.register(probe.stop)
    probe.write('start', mode='theme-switches-only')
    return probe


def _install_settings_paint_capture(probe):
    from PySide6.QtCore import QEvent, QObject
    from .settings_appearance import AppearanceSettingsPage

    class FirstPaint(QObject):
        button = None

        def cancel(self):
            if self.button is not None:
                self.button.removeEventFilter(self)
                self.button = None

        def arm(self, button, mode):
            self.cancel()
            self.button, self.mode = button, mode
            self.started = time.perf_counter()
            self.returned = None
            button.installEventFilter(self)

        def eventFilter(self, button, event):
            if event.type() == QEvent.Hide or probe.stopped.is_set():
                self.cancel()
            elif event.type() == QEvent.Paint and self.returned is not None:
                painted = time.perf_counter()
                self.cancel()
                probe.write('settings-theme-paint', mode=self.mode,
                    request_to_paint_ms=round((painted - self.started) * 1000, 3),
                    returned_to_paint_ms=round((painted - self.returned) * 1000, 3))
            return False

    original = AppearanceSettingsPage._choose

    @functools.wraps(original)
    def choose(page, mode):
        if probe.stopped.is_set():
            return original(page, mode)
        capture = getattr(page, '_theme_paint_capture', None)
        if capture is None:
            capture = page._theme_paint_capture = FirstPaint(page)
        button = page.buttons.get(mode)
        if button is None or not button.isVisible():
            capture.cancel()
            return original(page, mode)
        capture.arm(button, mode)
        try:
            result = original(page, mode)
        except BaseException:
            capture.cancel()
            raise
        capture.returned = time.perf_counter()
        return result

    AppearanceSettingsPage._choose = choose


def install_theme_animation_capture(probe):
    """Bounded GUI-thread frame timings, separate from preparation costs."""
    from .theme_transition import ThemeTransition, WaveOverlay

    original_start = ThemeTransition._start_animation
    original_frame = ThemeTransition._frame
    original_finish = ThemeTransition.finish
    original_paint = WaveOverlay.paintEvent

    def start(transition):
        result = original_start(transition)
        if not probe.stopped.is_set() and transition.animation.state().name == 'Running':
            started = time.perf_counter()
            requested = getattr(transition, '_theme_request_started', None)
            record = {'started': started, 'frames': [], 'bitmap_paints': 0,
                'ready_ms': round((started - requested) * 1000, 3) if requested is not None else None}
            transition._motion_capture = record
            for overlay in transition.overlays:
                overlay._motion_capture = record
        return result

    def frame(transition, progress):
        record = getattr(transition, '_motion_capture', None)
        started = time.perf_counter()
        try:
            return original_frame(transition, progress)
        finally:
            if record is not None and len(record['frames']) < 40:
                record['frames'].append({'at_ms': round((started - record['started']) * 1000, 3),
                    'work_ms': round((time.perf_counter() - started) * 1000, 3),
                    'progress': round(float(progress), 5), 'overlays': len(transition.overlays),
                    'quick_overlays': sum(getattr(overlay, 'render_thread', False) for overlay in transition.overlays),
                    'caption_overlays': sum(getattr(overlay, 'caption_height', 0) > 0 for overlay in transition.overlays),
                    'native_overlays': sum(overlay._native_clip for overlay in transition.overlays)})

    def paint(overlay, event):
        record = getattr(overlay, '_motion_capture', None)
        if record is not None:
            record['bitmap_paints'] += 1
        return original_paint(overlay, event)

    def finish(transition):
        record = getattr(transition, '_motion_capture', None)
        transition._motion_capture = None
        progress = transition.progress
        try:
            return original_finish(transition)
        finally:
            if record is not None and not probe.stopped.is_set():
                probe.write('theme-animation', reason='complete' if progress >= 1 else 'interrupted',
                    duration_ms=round((time.perf_counter() - record['started']) * 1000, 3),
                    ready_ms=record['ready_ms'], frames=record['frames'], bitmap_paints=record['bitmap_paints'])

    ThemeTransition._start_animation = start
    ThemeTransition._frame = frame
    ThemeTransition.finish = finish
    WaveOverlay.paintEvent = paint
